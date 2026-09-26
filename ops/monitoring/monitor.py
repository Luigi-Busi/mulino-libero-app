"""Independent read-only probes and a single external dead-man check."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request

ROOT = Path('/var/lib/mulino-monitor')
EXPORT = Path('/srv/mulino-backups-export/system')
CONFIG = Path('/etc/mulino-monitor/config.json')
INDEX = re.compile(r'system-[0-9]{8}T[0-9]{6}Z\.json')
PING = re.compile(r'https://hc-ping\.com/[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}')
PROBE = r'''
import json, socket, urllib.request
from pathlib import Path
result={}
try:
 result['runtime']=json.loads(Path('/tmp/mulino-health/status.json').read_text())
 result['alive']=Path('/proc/'+str(int(result['runtime']['pid']))).exists()
except Exception:
 result['runtime']=None
 result['alive']=False
try:
 with socket.create_connection(('127.0.0.1',5900),timeout=3) as s:
  result['vnc']=s.recv(12).startswith(b'RFB ')
except Exception: result['vnc']=False
try:
 with urllib.request.urlopen('http://127.0.0.1:6080/vnc.html',timeout=3) as r:
  result['novnc']=r.status==200 and b'<html' in r.read(4096).lower()
except Exception: result['novnc']=False
print(json.dumps(result))
'''


def run(args, timeout=15):
    return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          timeout=timeout, check=True, text=True).stdout


def read_json(path, limit=65536):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Symlink rejected')
    with path.open('rb') as source:
        raw = source.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('JSON too large')
    return json.loads(raw)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(prefix='.monitor-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as target:
            json.dump(value, target)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def age_good(stamp, now, maximum):
    return (type(stamp) in (float, int) and math.isfinite(stamp)
            and 0 <= now - stamp <= maximum)


def runtime_problem(data, service, running, now):
    if not running:
        return 'PROCESSO_FERMO'
    if not isinstance(data, dict) or data.get('schema') != 1 or data.get('service') != service:
        return 'SEGNALE_ASSENTE'
    if not age_good(data.get('updated'), now, 90):
        return 'CICLO_BLOCCATO'
    # Short bounded startup grace, never reset by a failed probe.
    warming = age_good(data.get('started'), now, 90)
    if not age_good(data.get('poll'), now, 180) and not warming:
        return 'TELEGRAM_NON_RAGGIUNTO'
    if service == 'mugnaio' and data.get('queue_ok') is not True and not warming:
        return 'CODA_NON_AGGIORNATA'
    return 'OK'


def source_time(index):
    return datetime.strptime(index['created_utc'], '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc).timestamp()


def checked_index(name, expected=None):
    if not isinstance(name, str) or not INDEX.fullmatch(name):
        raise ValueError('Invalid index name')
    index = read_json(EXPORT / name)
    if index.get('format') != 'mulino-system-index-v1':
        raise ValueError('Invalid index format')
    if index.get('file') != name[:-5] + '.tar.gpg':
        raise ValueError('Invalid archive name')
    if not re.fullmatch('[a-f0-9]{64}', index.get('sha256', '')):
        raise ValueError('Invalid hash')
    if expected and expected != index['sha256']:
        raise ValueError('Receipt mismatch')
    return index


def file_matches(path, expected, cache):
    if path.is_symlink() or not path.is_file():
        return False
    stat = path.stat()
    signature = [stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, expected]
    # A cached digest is reused only for the exact unchanged inode metadata.
    cached = cache.get(path.name, {})
    if (stat.st_size > 64 * 1024**2 and isinstance(cached, dict)
            and cached.get('signature') == signature
            and age_good(cached.get('checked'), time.time(), 3600)):
        return True
    with path.open('rb') as archive:
        digest = hashlib.file_digest(archive, 'sha256').hexdigest()
    if digest != expected:
        return False
    cache[path.name] = {'signature': signature, 'checked': time.time()}
    return True


def service_state(name):
    raw = run(['systemctl', 'show', name, '-p', 'ActiveState', '-p', 'SubState', '-p', 'Result', '-p', 'MainPID'])
    return dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)


def collect(cache):
    now = time.monotonic()
    wall = time.time()
    codes = {}
    states = {}
    try:
        container = json.loads(run(['docker', 'inspect', '--format', '{{json .State}}', 'libero-mail-bot']))
        with ThreadPoolExecutor(max_workers=2) as pool:
            docker_future = pool.submit(run, ['docker', 'exec', 'libero-mail-bot', 'python', '-c', PROBE], 20)
            responder_future = pool.submit(service_state, 'bot-risponditore.service')
            try:
                probe = json.loads(docker_future.result())
            except Exception:
                probe = {}
            responder = responder_future.result()
        runtime = probe.get('runtime')
        codes['mugnaio'] = runtime_problem(runtime, 'mugnaio',
            container.get('Running') is True and probe.get('alive') is True, time.monotonic())
        if isinstance(runtime, dict):
            states = {k: runtime.get(k) is True for k in ('paused', 'busy', 'human_wait')}
        codes['browser'] = 'OK' if probe.get('novnc') and probe.get('vnc') else 'ACCESSO_NON_DISPONIBILE'
        if isinstance(runtime, dict) and runtime.get('browser_expected') is True and runtime.get('browser_ok') is not True:
            codes['browser'] = 'SESSIONE_NON_RISPONDE'
    except Exception:
        codes.update(mugnaio='CONTROLLO_NON_RIUSCITO', browser='CONTROLLO_NON_RIUSCITO')
        responder = {}
    try:
        if not responder:
            responder = service_state('bot-risponditore.service')
        runtime = read_json('/run/mulino-monitor/risponditore.json')
        running = (responder.get('ActiveState') == 'active'
                   and str(runtime.get('pid')) == responder.get('MainPID'))
        codes['risponditore'] = runtime_problem(runtime, 'risponditore', running, time.monotonic())
    except Exception:
        codes['risponditore'] = 'SEGNALE_ASSENTE'
    usage = shutil.disk_usage('/opt/mulino-libero')
    fs = os.statvfs('/opt/mulino-libero')
    codes['disco'] = ('OK' if usage.free >= 5 * 1024**3 and usage.free / usage.total >= 0.15
                     and (not fs.f_files or fs.f_favail / fs.f_files >= 0.10) else 'SPAZIO_INSUFFICIENTE')
    try:
        latest = read_json('/var/lib/mulino-recovery/last-success.json')
        backup_service = service_state('mulino-system-backup.service')
        timer = service_state('mulino-system-backup.timer')
        good = (age_good(source_time(latest), wall, 30 * 3600)
                and timer.get('ActiveState') == 'active' and backup_service.get('Result') == 'success')
        codes['backup_creazione'] = 'OK' if good else 'COPIA_ASSENTE_O_FALLITA'
        index = checked_index(latest['file'].replace('.tar.gpg', '.json'), latest['sha256'])
        image = index['image_asset']
        if not re.fullmatch(r'images-[a-f0-9]{64}\.tar\.gpg', image['file']):
            raise ValueError('Invalid image name')
        if not re.fullmatch('[a-f0-9]{64}', image.get('sha256', '')):
            raise ValueError('Invalid image hash')
        good = (file_matches(EXPORT / index['file'], index['sha256'], cache)
                and file_matches(EXPORT / image['file'], image['sha256'], cache))
        codes['backup_esportazione'] = 'OK' if good else 'ARCHIVIO_NON_INTEGRO'
    except Exception:
        codes.setdefault('backup_creazione', 'CONTROLLO_NON_RIUSCITO')
        codes['backup_esportazione'] = 'ARCHIVIO_NON_VERIFICABILE'
    try:
        receipt = read_json('/home/backupmulino/mulino-monitor-receipt.json', 4096)
        index = checked_index(receipt['index'], receipt['sha256'])
        # Freshness comes from the backup itself, never from receipt file mtime.
        good = receipt.get('verified') is True and age_good(source_time(index), wall, 30 * 3600)
        codes['backup_pc'] = 'OK' if good else 'COPIA_PC_OBSOLETA'
    except Exception:
        codes['backup_pc'] = 'RICEVUTA_PC_ASSENTE'
    return {'codes': codes, 'states': states}


def stabilize(codes, old, now):
    previous = old.get('components', {}) if age_good(old.get('tick'), now, 300) else {}
    result = {}
    for name, code in codes.items():
        prior = previous.get(name, {})
        bad = code != 'OK'
        count = min(2, prior.get('count', 0) + 1) if prior.get('bad') is bad else 1
        alarm = bad if count >= 2 else prior.get('alarm', False)
        result[name] = {'bad': bad, 'count': count, 'alarm': alarm,
                        'code': 'RIENTRO_IN_VERIFICA' if alarm and not bad else code}
    return {'tick': now, 'components': result}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def ping(url, failed, body):
    if not isinstance(url, str) or not PING.fullmatch(url):
        raise ValueError('Invalid Healthchecks endpoint')
    request = urllib.request.Request(url + ('/fail' if failed else ''),
        data=body.encode('ascii'), headers={'Content-Type': 'text/plain'}, method='POST')
    with urllib.request.build_opener(NoRedirect).open(request, timeout=10) as result:
        if result.status != 200:
            raise ValueError('Signal not accepted')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check-only', action='store_true')
    options = parser.parse_args()
    try:
        old = read_json(ROOT / 'state.json')
    except (OSError, ValueError):
        old = {}
    cache = old.get('hash_cache', {})
    report = collect(cache)
    state = stabilize(report['codes'], old, time.monotonic())
    failed = [name + '=' + item['code'] for name, item in state['components'].items() if item['alarm']]
    if not options.check_only:
        config = read_json(CONFIG)
        body = '\n'.join(failed) if failed else 'TUTTI_I_CONTROLLI_OK'
        ping(config['ping_url'], bool(failed), body)
        state['hash_cache'] = cache
        write_json(ROOT / 'state.json', state)
        write_json(ROOT / 'latest.json', dict(checked_utc=datetime.now(timezone.utc).isoformat(), **report))
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Never include exception messages: transport errors can contain ping URLs.
        print('Monitor non completato: ' + type(error).__name__)
        raise SystemExit(1)
