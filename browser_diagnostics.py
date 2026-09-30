"""Allowlisted technical events only; never URLs, page contents or exception text."""
import hashlib
import json
import logging
from pathlib import Path
import re
import time
import uuid


PHASES = {
    'avvio del browser': 'browser_start',
    'apertura della pagina Libero': 'open_page',
    'gestione del banner cookie': 'cookie_banner',
    'ricerca del campo nome utente': 'username_field',
    'verifica della disponibilità del nome utente': 'username_check',
    'compilazione della password': 'password_fill',
    'gestione dei cookie prima del passaggio alle informazioni personali': 'cookies_before_personal',
    'passaggio alle informazioni personali': 'personal_next',
    'attesa intervento manuale su cookie o CAPTCHA della prima pagina': 'first_manual_wait',
    'verifica di sicurezza prima dei dati anagrafici': 'personal_security',
    'compilazione del nome': 'first_name',
    'compilazione del cognome': 'last_name',
    'compilazione della data di nascita': 'birth_date',
    'selezione del genere': 'gender',
    'compilazione del comune di residenza': 'city',
    "selezione del comune nell'elenco dei suggerimenti": 'city_suggestion',
    'pulsante Avanti delle informazioni personali': 'personal_submit',
    'riconoscimento del passaggio successivo ai dati personali': 'next_step',
    'invio di Protezione Account dopo la conferma amministrativa': 'protection_submit',
    'invio finale della registrazione': 'final_submit',
    "attesa dell'esito della registrazione nel browser aperto": 'outcome_wait',
    'pulsante Avanti dopo i dati personali': 'personal_continue',
    'ricerca del campo Mail o Cellulare': 'recovery_field',
    'compilazione della mail alternativa': 'recovery_fill',
    'scelta Non presto il consenso per pubblicità e personalizzazione': 'consents',
    'compilazione del numero di telefono': 'phone_fill',
    'richiesta del codice SMS': 'sms_request',
    'compilazione del codice SMS': 'otp_fill',
    'verifica del codice SMS': 'otp_check',
    'attesa del campo Codice di conferma SMS': 'otp_wait',
}
EVENTS = {'session_start', 'phase', 'browser_connected', 'context_opened', 'page_opened',
          'page_close', 'page_crash', 'context_close', 'browser_disconnected',
          'operation_error', 'cleanup_start', 'cleanup_error', 'session_end'}
REASONS = {'running', 'completed', 'cancelled', 'error'}
ERRORS = {'target_closed', 'timeout', 'cancelled', 'registration', 'other'}
COMPONENTS = {'browser', 'context', 'page', 'cookies', 'driver'}
RESOURCE_KEYS = {'memory_bytes', 'memory_limit_bytes', 'oom', 'oom_kill'}
LOGGER = logging.getLogger('mulino-browser-diagnostics')
LOGGER.setLevel(logging.INFO)


def error_kind(error):
    return {'TargetClosedError': 'target_closed', 'TimeoutError': 'timeout',
            'CancelledError': 'cancelled', 'RequestCancelled': 'cancelled',
            'RegistrationError': 'registration'}.get(type(error).__name__, 'other')


def resources(root=Path('/sys/fs/cgroup')):
    result = {}
    for filename, key in (('memory.current', 'memory_bytes'), ('memory.max', 'memory_limit_bytes')):
        try:
            value = int((root / filename).read_text().strip())
            if 0 <= value < 2**63:
                result[key] = value
        except (OSError, ValueError):
            pass
    try:
        counters = dict(line.split() for line in (root / 'memory.events').read_text().splitlines())
        for key in ('oom', 'oom_kill'):
            value = int(counters[key])
            if 0 <= value < 2**63:
                result[key] = value
    except (OSError, ValueError, KeyError):
        pass
    return result


def valid_event(value):
    """Shared with the host collector; reject the entire event if unexpected."""
    if not isinstance(value, dict):
        return False
    required = {'schema', 'source', 'session', 'request', 'seq', 'elapsed_ms', 'event', 'phase', 'reason', 'expected'}
    optional = {'component', 'error', 'resources'}
    if not required <= value.keys() or value.keys() - required - optional:
        return False
    if type(value['schema']) is not int or value['schema'] != 1 or value['source'] != 'browser':
        return False
    if any(not isinstance(value[key], str) or not re.fullmatch(r'[a-f0-9]{16}', value[key]) for key in ('session', 'request')):
        return False
    if any(type(value[key]) is not int or not 0 <= value[key] < 2**63 for key in ('seq', 'elapsed_ms')):
        return False
    if any(type(value[key]) is not str for key in ('event', 'phase', 'reason')):
        return False
    if (value['event'] not in EVENTS or value['phase'] not in set(PHASES.values()) | {'other'}
            or value['reason'] not in REASONS or type(value['expected']) is not bool):
        return False
    if 'component' in value and (type(value['component']) is not str or value['component'] not in COMPONENTS):
        return False
    if 'error' in value and (type(value['error']) is not str or value['error'] not in ERRORS):
        return False
    if 'resources' in value:
        resource = value['resources']
        if (not isinstance(resource, dict) or resource.keys() - RESOURCE_KEYS
                or any(type(v) is not int or not 0 <= v < 2**63 for v in resource.values())):
            return False
    return True


def valid_launcher_event(value):
    if not isinstance(value, dict) or set(value) != {'schema', 'source', 'event', 'component', 'exit_code', 'signal', 'expected'}:
        return False
    if type(value['schema']) is not int or value['schema'] != 1 or value['source'] != 'launcher':
        return False
    if any(type(value[key]) is not str for key in ('event', 'component')):
        return False
    return (value['event'] in {'component_exit', 'cleanup_start', 'signal', 'display_failed'}
            and value['component'] in {'display', 'vnc', 'websocket', 'bot', 'service', 'unknown'}
            and type(value['expected']) is bool
            and all(type(value[key]) is int and 0 <= value[key] <= 255 for key in ('exit_code', 'signal')))


class BrowserDiagnostics:
    def __init__(self, request_id):
        self.session = uuid.uuid4().hex[:16]
        self.request = hashlib.sha256(str(request_id).encode()).hexdigest()[:16]
        self.started = time.monotonic()
        self.seq = 0
        self.phase = 'browser_start'
        self.reason = 'running'
        self.closing = False
        self.failure_seen = False

    def emit(self, event, **fields):
        # A diagnostics/logging failure must never change registration behaviour.
        try:
            self.seq += 1
            value = dict(schema=1, source='browser', session=self.session, request=self.request,
                         seq=self.seq, elapsed_ms=max(0, int((time.monotonic() - self.started) * 1000)),
                         event=event, phase=self.phase, reason=self.reason, expected=self.closing, **fields)
            if valid_event(value):
                LOGGER.info('MULINO_DIAG %s', json.dumps(value, separators=(',', ':')))
        except Exception:
            pass

    def set_phase(self, phase):
        code = PHASES.get(phase, 'other')
        if code != self.phase:
            self.phase = code
            self.emit('phase')

    def failure(self, error, component='browser'):
        self.failure_seen = True
        self.reason = 'cancelled' if error_kind(error) == 'cancelled' else 'error'
        self.emit('operation_error', error=error_kind(error), component=component, resources=resources())

    def begin_cleanup(self, reason):
        self.reason = reason
        self.closing = True
        self.emit('cleanup_start')

    def attach_browser(self, browser):
        browser.on('disconnected', lambda *_: self.emit('browser_disconnected', resources=resources()))
        self.emit('browser_connected')

    def attach_context(self, context):
        context.on('close', lambda *_: self.emit('context_close'))
        self.emit('context_opened')

    def attach_page(self, page):
        page.on('close', lambda *_: self.emit('page_close'))
        page.on('crash', lambda *_: self.emit('page_crash', resources=resources()))
        self.emit('page_opened')
