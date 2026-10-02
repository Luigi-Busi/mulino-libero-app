#!/usr/bin/env python3
"""Mulino deployment controller. Production paths are deliberately not CLI options."""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import time
import uuid

from image_store import Store
from dataclasses import dataclass


class Failure(RuntimeError):
    pass


TAG = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+\Z")
REMOTE_BROWSER_URLS = (
    b'http://127.0.0.1:6080/vnc.html',
    b'https://mulino-browser.tail1ce920.ts.net/vnc.html?autoconnect=1&resize=scale',
)
REMOTE_BROWSER_LINE = re.compile(rb'^      REMOTE_BROWSER_URL: ([^\r\n]+)(?=\r?$)', re.MULTILINE)


def browser_url_only_change(before, after):
    """Permit only the reviewed URL transition, with every other byte unchanged."""
    if before == after:
        return True
    old, new = REMOTE_BROWSER_LINE.findall(before), REMOTE_BROWSER_LINE.findall(after)
    if len(old) != 1 or len(new) != 1 or old[0] not in REMOTE_BROWSER_URLS or new[0] not in REMOTE_BROWSER_URLS:
        return False
    return (REMOTE_BROWSER_LINE.sub(b'      REMOTE_BROWSER_URL: REVIEWED', before)
            == REMOTE_BROWSER_LINE.sub(b'      REMOTE_BROWSER_URL: REVIEWED', after))


INTERRUPTS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
PANEL_BIND = (b'      - type: bind\n'
              b'        source: /var/lib/mulino-monitor/panel\n'
              b'        target: /run/mulino-panel\n'
              b'        read_only: true\n'
              b'        bind:\n'
              b'          create_host_path: false\n')


def reviewed_compose_change(before, after):
    def strip_panel(value):
        if value.count(PANEL_BIND) > 1:
            return None
        if PANEL_BIND in value:
            anchor = b'      - ../data:/data\n' + PANEL_BIND
            if value.count(anchor) != 1:
                return None
            value = value.replace(anchor, b'      - ../data:/data\n', 1)
        return value
    old, new = strip_panel(before), strip_panel(after)
    return old is not None and new is not None and browser_url_only_change(old, new)


HEALTH = r'''
from pathlib import Path
import urllib.request
commands = [p.read_bytes().replace(b'\0', b' ') for p in Path('/proc').glob('[0-9]*/cmdline') if p.exists()]
for expected in (b'python /app/libero_mail_bot.py', b'Xvfb :99', b'x11vnc -display', b'websockify'):
    assert any(expected in c and b'python -c' not in c for c in commands), 'process absent'
with urllib.request.urlopen('http://127.0.0.1:6080/vnc.html', timeout=4) as response:
    assert response.status == 200
'''
UNIT_RUNNER = r'''
import os, sys, unittest
suite = unittest.defaultTestLoader.discover(os.environ.get('MULINO_TEST_DIRECTORY', '/suite/tests'))
assert suite.countTestCases() > 0, 'No regression tests found'
result = unittest.TextTestRunner(verbosity=1).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
'''


@dataclass(frozen=True)
class Config:
    app: Path = Path('/opt/mulino-libero/app')
    state: Path = Path('/var/lib/mulino-deploy')
    project: str = 'mulino-libero'
    service: str = 'libero-mail-bot'
    container: str = 'libero-mail-bot'
    image_repo: str = 'mulino-release'
    health_code: str = HEALTH
    health_timeout: int = 120
    settle_seconds: int = 15
    poll_seconds: int = 3
    require_pause: bool = True
    minimum_free: int = 4 * 1024**3
    image_files: tuple = ('libero_mail_bot.py', 'start.sh', 'requirements.txt')
    frozen_files: tuple = ('docker-compose.yml', 'bot_risponditore.py', 'install_risponditore.sh')

    @property
    def env(self):
        return self.app.parent / '.env'

    @property
    def data(self):
        return self.app.parent / 'data'

    @property
    def secrets(self):
        return self.app.parent / 'secrets'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('x', encoding='utf-8') as stream:
        os.chmod(temporary, 0o600)
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


class Manager:
    def __init__(self, config=Config()):
        self.c = config
        self.logfile = None

    def run(self, args, timeout=120, binary=False, log=False):
        # Child tools never inherit Compose/Docker overrides from an operator shell.
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('COMPOSE_', 'DOCKER_', 'GIT_'))}
        env.update(DOCKER_HOST='unix:///var/run/docker.sock', GIT_TERMINAL_PROMPT='0',
                   PYTHONDONTWRITEBYTECODE='1')
        try:
            result = subprocess.run([str(x) for x in args], stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, env=env, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise Failure(f'Tempo scaduto: {args[0]}.') from None
        if self.logfile:
            with self.logfile.open('ab') as stream:
                stream.write(f'{args[0]}: exit {result.returncode}\n'.encode())
                if log:
                    stream.write(result.stdout)
                if log or result.returncode:
                    stream.write(result.stderr)
        if result.returncode:
            raise Failure(f'Comando {args[0]} fallito (codice {result.returncode}); vedere il log locale.')
        return result.stdout if binary else result.stdout.decode().strip()

    def git(self, *args, binary=False):
        return self.run(['git', '-C', self.c.app, '-c', 'core.hooksPath=/dev/null', *args], binary=binary)

    @contextlib.contextmanager
    def locked(self):
        if self.c.state.is_symlink():
            raise Failure('La directory di stato non puo essere un collegamento.')
        self.c.state.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.c.state, 0o700)
        with (self.c.state / 'lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Failure('Un altro deploy/rollback e in corso.') from None
            logs = self.c.state / 'logs'
            logs.mkdir(mode=0o700, exist_ok=True)
            self.logfile = logs / (time.strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8] + '.log')
            self.logfile.touch(mode=0o600)
            yield

    def save(self, state):
        # state.json is authoritative; the human-readable marker is derived.
        atomic(self.c.state / 'state.json', json.dumps(state, indent=2) + '\n')
        target = (state.get('pending') or {}).get('from') or state.get('previous') or state['current']
        atomic(self.c.state / 'last-known-good', target['tag'] + '\n')

    def load(self):
        try:
            result = json.loads((self.c.state / 'state.json').read_text())
        except FileNotFoundError:
            raise Failure('Prima eseguire: mulino-deploy init v1.0.0') from None
        if result.get('schema') != 1:
            raise Failure('Formato dello stato non supportato.')
        return result

    def clean(self):
        if self.c.app.resolve() != self.c.app or self.git('status', '--porcelain', '--untracked-files=all'):
            raise Failure('Repository modificato, file non tracciati o percorso non canonico: operazione bloccata.')

    def resolve(self, tag, fetch=False):
        if not TAG.fullmatch(tag):
            raise Failure('Usare un tag esatto nel formato v1.2.3.')
        if fetch:
            listing = self.git('ls-remote', '--tags', 'origin', f'refs/tags/{tag}', f'refs/tags/{tag}^{{}}')
            refs = dict(line.split()[::-1] for line in listing.splitlines())
            remote = refs.get(f'refs/tags/{tag}^{{}}', refs.get(f'refs/tags/{tag}'))
            if not remote:
                raise Failure('Il tag non e pubblicato su origin.')
            self.git('fetch', '--no-tags', 'origin', 'tag', tag)
        sha = self.git('rev-parse', '--verify', f'refs/tags/{tag}^{{commit}}')
        if fetch and sha != remote:
            raise Failure('Il tag locale non coincide con origin.')
        return sha

    def source(self, sha):
        destination = self.c.state / 'releases' / sha / 'source'
        if any(line.startswith(('160000 ', '120000 ')) for line in self.git('ls-tree', '-r', sha).splitlines()):
            raise Failure('Submodule e collegamenti non sono ammessi nelle release.')
        # Re-use only an archive whose entire content still matches the Git tree.
        archive = self.git('archive', '--format=tar', sha, binary=True)
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            members = bundle.getmembers()
            for member in members:
                parts = Path(member.name).parts
                if (member.name.startswith('/') or '..' in parts or not (member.isfile() or member.isdir())
                    or any(p in {'data', 'secrets', '.git'} or p.startswith('.venv') for p in parts)
                    or any(p == '.env' or (p.startswith('.env.') and p != '.env.example')
                           or p == 'bot_risponditore.env' or '.sqlite' in p or p.endswith('.log') for p in parts)):
                    raise Failure(f'File non ammesso nel tag: {member.name}')
            if destination.exists():
                if any(p.is_symlink() for p in destination.rglob('*')):
                    raise Failure('Collegamento inatteso nell archivio della release.')
                expected = set()
                for member in members:
                    if member.isfile():
                        expected.add(member.name)
                        item = destination / member.name
                        if item.is_symlink() or not item.is_file() or item.read_bytes() != bundle.extractfile(member).read():
                            raise Failure('Archivio della release alterato.')
                actual = {str(p.relative_to(destination)) for p in destination.rglob('*') if p.is_file()}
                if actual != expected:
                    raise Failure('Archivio della release contiene file inattesi.')
            else:
                destination.mkdir(mode=0o700, parents=True)
                bundle.extractall(destination, filter='data')
                # Git archives can give different same-size files identical mtimes.
                # Fresh timestamps prevent incremental build-context transfer from
                # mistaking different archives for the last context it sent.
                for item in destination.rglob('*'):
                    if item.is_file():
                        os.utime(item, None)
        return destination

    def compose(self, *args, override=None, compose_file=None):
        command = ['docker', 'compose', '--project-directory', self.c.app, '--env-file', self.c.env,
                   '-p', self.c.project, '-f', compose_file or self.c.app / 'docker-compose.yml']
        if override:
            command += ['-f', override]
        return self.run(command + list(args), timeout=300)

    def model(self, compose_file=None):
        model = json.loads(self.compose('config', '--format', 'json', '--no-env-resolution', compose_file=compose_file))
        if set(model['services']) != {self.c.service}:
            raise Failure('Questa procedura gestisce soltanto il servizio Docker del Mugnaio.')
        service = model['services'][self.c.service]
        volumes = service.get('volumes', [])
        data = [v for v in volumes if v.get('target') == '/data']
        panel = [v for v in volumes if v.get('target') == '/run/mulino-panel']
        if (len(data) != 1 or data[0].get('type') != 'bind' or data[0].get('source') != str(self.c.data)
                or data[0].get('read_only', False) is not False or len(volumes) != 1 + len(panel)
                or len(panel) > 1):
            raise Failure('Il volume dati non coincide con il percorso previsto.')
        if panel and (panel[0].get('type') != 'bind'
                      or panel[0].get('source') != '/var/lib/mulino-monitor/panel'
                      or panel[0].get('read_only') is not True
                      or panel[0].get('bind', {}).get('create_host_path') is not False):
            raise Failure('Il riepilogo del pannello deve essere il bind previsto in sola lettura.')
        for secret in model.get('secrets', {}).values():
            if Path(secret['file']).parent != self.c.secrets:
                raise Failure('Percorso di un segreto non previsto.')
        return model

    def fingerprint(self):
        # Only metadata for secrets. No passwords or tokens are copied to state.
        info = {'env': digest(self.c.env), 'secrets': {}}
        for path in sorted(self.c.secrets.iterdir()):
            if path.is_symlink() or not path.is_file():
                raise Failure('Struttura secrets non prevista.')
            stat = path.stat()
            info['secrets'][path.name] = [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_mode]
        return info

    def guard(self, state, pending=False):
        self.clean()
        if state.get('pending') and not pending:
            raise Failure('Deploy interrotto: eseguire mulino-rollback --recover.')
        if not pending and self.git('rev-parse', 'HEAD') != state['current']['sha']:
            raise Failure('HEAD non coincide con la versione registrata.')
        if self.fingerprint() != state['configuration']:
            raise Failure('Configurazione o metadati dei segreti cambiati: serve una verifica prima del deploy.')
        self.model()

    def inspect(self):
        return json.loads(self.run(['docker', 'inspect', self.c.container]))[0]

    def runtime_matches(self, record):
        container = self.inspect()
        labels = container['Config'].get('Labels') or {}
        if container['Image'] != record['image'] or labels.get('com.docker.compose.project') != self.c.project or labels.get('com.docker.compose.service') != self.c.service:
            raise Failure('Il container non coincide con la release/progetto registrati.')
        expected = {(str(self.c.data), '/data', True)}
        model = self.model()
        for volume in model['services'][self.c.service].get('volumes', []):
            if volume.get('target') == '/run/mulino-panel':
                expected.add((volume['source'], volume['target'], False))
        for secret in model['services'][self.c.service].get('secrets', []):
            expected.add((model['secrets'][secret['source']]['file'], '/run/secrets/' + secret['target'], False))
        actual = {(v['Source'], v['Destination'], v['RW']) for v in container['Mounts']}
        if actual != expected:
            raise Failure('I mount del container non coincidono con dati e segreti previsti.')
        environment = model['services'][self.c.service].get('environment', {})
        if 'REMOTE_BROWSER_URL' in environment:
            actual_environment = dict(value.split('=', 1) for value in container['Config'].get('Env', []) if '=' in value)
            if actual_environment.get('REMOTE_BROWSER_URL') != environment['REMOTE_BROWSER_URL']:
                raise Failure('Il collegamento del browser nel container non coincide con la release.')
        return container

    def health(self, record):
        start = time.monotonic()
        stable_since = None
        first = None
        while time.monotonic() - start <= self.c.health_timeout:
            try:
                container = self.runtime_matches(record)
                marker = (container['Id'], container['RestartCount'], container['State']['StartedAt'])
                if first is None:
                    first = marker
                if marker != first:
                    raise Failure('Container riavviato durante il controllo.')
                if not container['State']['Running'] or container['State'].get('Health', {}).get('Status', 'healthy') != 'healthy':
                    raise Failure('Container non pronto.')
                self.run(['docker', 'exec', container['Id'], 'python', '-c', self.c.health_code], timeout=12)
                stable_since = stable_since or time.monotonic()
                if time.monotonic() - stable_since >= self.c.settle_seconds:
                    return
            except Failure:
                stable_since = None
            time.sleep(self.c.poll_seconds)
        raise Failure('Controllo di salute/stabilita non superato.')

    def retain_image(self, record):
        self.run(['docker', 'image', 'inspect', record['image']])
        self.run(['docker', 'tag', record['image'], record['image_tag']])
        if (self.c.state / 'releases' / 'shared-images.json').exists():
            try:
                Store(self.c.state, self.run, self.c.minimum_free).retain(record)
            except (RuntimeError, OSError, ValueError) as error:
                raise Failure('Conservazione condivisa non riuscita: ' + str(error)) from error
            return
        images = self.c.state / 'images'
        images.mkdir(mode=0o700, exist_ok=True)
        archive = images / (record['image'].split(':')[1] + '.tar')
        if not archive.exists():
            if shutil.disk_usage(images).free < self.c.minimum_free:
                raise Failure('Spazio insufficiente per conservare l immagine di rollback.')
            temporary = archive.with_suffix('.tmp')
            self.run(['docker', 'image', 'save', '-o', temporary, record['image_tag']], timeout=600)
            with temporary.open('rb') as stream:
                os.fsync(stream.fileno())
            os.replace(temporary, archive)

    def ensure_image(self, record):
        try:
            self.run(['docker', 'image', 'inspect', record['image']])
        except Failure:
            archive = self.c.state / 'images' / (record['image'].split(':')[1] + '.tar')
            if (self.c.state / 'releases' / 'shared-images.json').exists():
                try:
                    archive = Store(self.c.state, self.run, self.c.minimum_free).archive_for(record['image'])
                except (RuntimeError, OSError, ValueError) as error:
                    raise Failure('Archivio condiviso non disponibile: ' + str(error)) from error
            self.run(['docker', 'image', 'load', '-i', archive], timeout=1200)
        self.run(['docker', 'image', 'inspect', record['image']])
        self.run(['docker', 'tag', record['image'], record['image_tag']])

    def unit_tests(self, record, source):
        name = self.c.project + '-tests-' + uuid.uuid4().hex[:12]
        extra = []
        if record.get('tests_override'):
            correction = record['tests_override']
            path = Path(correction['path'])
            if path.is_symlink() or digest(path) != correction['sha256']:
                raise Failure('Suite corretta della baseline alterata.')
            extra = ['--mount', f'type=bind,src={path.parent},dst=/corrected-tests,readonly',
                     '-e', 'MULINO_TEST_DIRECTORY=/corrected-tests',
                     '-e', 'MULINO_TEST_SOURCE=/suite/libero_mail_bot.py']
        try:
            self.run(['docker', 'run', '--rm', '--name', name, '--network', 'none', '--read-only', '--cap-drop', 'ALL',
                  '--security-opt', 'no-new-privileges', '--tmpfs', '/tmp:rw,nosuid,nodev',
                  '--pids-limit', '128', '--memory', '512m', '--cpus', '1',
                  '--mount', f'type=bind,src={source},dst=/suite,readonly', '-e', 'PYTHONDONTWRITEBYTECODE=1',
                  *extra, '--entrypoint', 'python', record['image'], '-c', UNIT_RUNNER], timeout=300, log=True)
        finally:
            with contextlib.suppress(Failure):
                self.run(['docker', 'rm', '-f', name])

    def image_files(self, source):
        optional = tuple(name for name in ('runtime_health.py', 'browser_diagnostics.py', 'telegram_panel.py') if (source / name).is_file())
        if (source / 'telegram_panel.py').is_file():
            optional += ('VERSION',)
        return self.c.image_files + optional

    def verify_image(self, record, source):
        output = self.run(['docker', 'run', '--rm', '--network', 'none', '--read-only',
                           '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                           '--entrypoint', 'sha256sum', record['image'],
                           *('/app/' + name for name in self.image_files(source))])
        actual = dict(line.split(maxsplit=1)[::-1] for line in output.splitlines())
        for name in self.image_files(source):
            if actual.get('/app/' + name) != digest(source / name):
                raise Failure('L immagine costruita non contiene il codice del tag: ' + name)

    def check_integrations(self, record, source):
        original = self.model(compose_file=source / 'docker-compose.yml')
        service = original['services'][self.c.service]
        safe = {key: service[key] for key in ('env_file', 'environment', 'secrets') if key in service}
        safe['environment'] = dict(safe.get('environment', {}), DATA_DIR='/tmp/mulino-check')
        safe.update(image=record['image_tag'], read_only=True, tmpfs=['/tmp:rw,nosuid,nodev'],
                    cap_drop=['ALL'], security_opt=['no-new-privileges:true'],
                    mem_limit='512m', pids_limit=128, cpus=1)
        model = {'services': {self.c.service: safe}, 'secrets': original.get('secrets', {})}
        config = self.c.state / 'preflight.json'
        atomic(config, json.dumps(model))
        # No production volumes, network or ports are attached to this one-off check.
        name = self.c.project + '-check-' + uuid.uuid4().hex[:12]
        try:
            self.run(['docker', 'compose', '-p', self.c.project + '-preflight', '--env-file', self.c.env,
                  '-f', config, 'run', '--rm', '--name', name, '--no-deps', '-T', '--entrypoint', 'python',
                  self.c.service, '/app/libero_mail_bot.py', '--check'], timeout=150, log=True)
        finally:
            with contextlib.suppress(Failure):
                self.run(['docker', 'rm', '-f', name])
            with contextlib.suppress(Failure):
                self.run(['docker', 'network', 'rm', self.c.project + '-preflight_default'])

    def init(self, tag, baseline_tests=None):
        if (self.c.state / 'state.json').exists():
            raise Failure('Stato gia inizializzato: non viene sovrascritto.')
        self.clean()
        configuration = self.fingerprint()
        sha = self.resolve(tag)
        if self.git('rev-parse', 'HEAD') != sha:
            raise Failure('Il tag iniziale non coincide con HEAD.')
        source = self.source(sha)
        container = self.inspect()
        record = {'tag': tag, 'sha': sha, 'image': container['Image'],
                  'image_tag': self.c.image_repo + ':' + sha,
                  'branch': self.git('branch', '--show-current')}
        for name in self.image_files(source):
            actual = self.run(['docker', 'exec', container['Id'], 'sha256sum', '/app/' + name]).split()[0]
            if actual != digest(source / name):
                raise Failure('Il codice in esecuzione non coincide con Git: ' + name)
        self.health(record)
        self.retain_image(record)
        if baseline_tests:
            if tag != 'v1.0.0':
                raise Failure('La correzione storica dei test e ammessa solo per v1.0.0.')
            directory = source.parent / 'tests-correction'
            directory.mkdir(mode=0o700, exist_ok=True)
            corrected = directory / 'test_regressions.py'
            atomic(corrected, Path(baseline_tests).read_text())
            record['tests_override'] = {'path': str(corrected), 'sha256': digest(corrected)}
        self.unit_tests(record, source)
        self.check_integrations(record, source)
        if configuration != self.fingerprint():
            raise Failure('Configurazione cambiata durante la verifica iniziale.')
        state = {'schema': 1, 'current': record, 'previous': None, 'pending': None,
                 'configuration': configuration}
        self.save(state)
        return state

    def prepare(self, tag):
        state = self.load()
        self.guard(state)
        self.runtime_matches(state['current'])
        sha = self.resolve(tag, fetch=True)
        source = self.source(sha)
        baseline = self.source(state['current']['sha'])
        for name in self.c.frozen_files:
            before, after = (baseline / name).read_bytes(), (source / name).read_bytes()
            allowed = (reviewed_compose_change(before, after) if name == 'docker-compose.yml' else before == after)
            if not allowed:
                raise Failure('Modifica da gestire separatamente: ' + name)
        if sha == state['current']['sha']:
            record = state['current']
        elif (source.parent / 'release.json').is_file():
            # Once verified, a commit keeps its exact image even if upstream
            # base-image tags change or a later build overwrites a Docker tag.
            record = json.loads((source.parent / 'release.json').read_text())
            if record['sha'] != sha:
                raise Failure('Record della release non coerente con il commit.')
            self.ensure_image(record)
        else:
            image_tag = self.c.image_repo + ':' + sha
            build = source.parent / 'build.json'
            atomic(build, json.dumps({'services': {self.c.service: {
                'image': image_tag, 'build': {'context': str(source)}}}}))
            if shutil.disk_usage(self.c.state).free < self.c.minimum_free:
                raise Failure('Spazio insufficiente per il build.')
            self.run(['docker', 'compose', '-p', self.c.project + '-build-' + sha[:12], '-f', build,
                      'build', self.c.service], timeout=1200, log=True)
            image = json.loads(self.run(['docker', 'image', 'inspect', image_tag]))[0]['Id']
            record = {'tag': tag, 'sha': sha, 'image': image, 'image_tag': image_tag, 'branch': ''}
        self.verify_image(record, source)
        self.unit_tests(record, source)
        self.check_integrations(record, source)
        self.retain_image(record)
        atomic(source.parent / 'release.json', json.dumps(record))
        return record

    def maintenance(self, record, idle_confirmed):
        if not idle_confirmed:
            raise Failure('Prima /pausa e /stato nel Mugnaio; poi usare --idle-confirmed solo senza registrazioni attive.')
        if self.c.require_pause:
            code = "import sqlite3; db=sqlite3.connect('file:/data/created-outcomes.sqlite3?mode=ro',uri=True); assert db.execute(\"SELECT value FROM runtime_settings WHERE key='queue_paused'\").fetchone() == ('1',), 'Coda non in pausa'"
            self.run(['docker', 'run', '--rm', '--network', 'none', '--read-only',
                      '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                      '--mount', f'type=bind,src={self.c.data},dst=/data,readonly',
                      '--entrypoint', 'python', record['image'], '-c', code])

    def activate(self, record):
        self.ensure_image(record)
        self.source(record['sha'])
        self.git('checkout', '--no-overwrite-ignore', '--detach', record['sha'])
        override = self.c.state / 'runtime-image.json'
        atomic(override, json.dumps({'services': {self.c.service: {'image': record['image_tag']}}}))
        self.compose('up', '-d', '--no-build', '--pull', 'never', '--no-deps',
                     '--wait', '--wait-timeout', str(self.c.health_timeout), self.c.service, override=override)
        self.health(record)
        if record.get('branch'):
            if self.git('rev-parse', 'refs/heads/' + record['branch']) == record['sha']:
                self.git('checkout', '--no-overwrite-ignore', record['branch'])

    def transaction(self, state, target):
        old = state['current']
        previous = state.get('previous')
        state['pending'] = {'from': old, 'to': target, 'phase': 'activating'}
        self.save(state)
        try:
            self.activate(target)
            state.update(current=target, previous=old, pending=None)
            self.save(state)
        except BaseException as error:
            # A second interrupt must not interrupt recovery. SIGKILL remains recoverable via the journal.
            old_handlers = {}
            for sig in INTERRUPTS:
                old_handlers[sig] = signal.signal(sig, signal.SIG_IGN)
            try:
                state.update(current=old, previous=previous, pending={'from': old, 'to': target, 'phase': 'recovering'})
                self.save(state)
                self.activate(old)
                state['pending'] = None
                self.save(state)
            except BaseException:
                state['pending'] = {'from': old, 'to': target, 'phase': 'recovery-required'}
                self.save(state)
                raise Failure('Deploy e ripristino falliti: eseguire mulino-rollback --recover. Stato conservato.') from error
            finally:
                for sig, handler in old_handlers.items():
                    signal.signal(sig, handler)
            raise Failure('Operazione fallita; versione precedente ripristinata e verificata.') from error

    def deploy(self, tag, idle_confirmed=False, data_compatible=False):
        record = self.prepare(tag)
        state = self.load()
        if record['sha'] == state['current']['sha']:
            self.health(record)
            return 'Versione gia attiva e verificata; nessun riavvio.'
        if not data_compatible:
            raise Failure('Serve --data-compatible dopo aver verificato la compatibilita dei dati con la versione precedente.')
        self.guard(state)
        self.runtime_matches(state['current'])
        self.health(state['current'])
        self.ensure_image(state['current'])
        self.maintenance(state['current'], idle_confirmed)
        self.transaction(state, record)
        return 'Deploy confermato: ' + tag

    def rollback(self, idle_confirmed=False, recover=False):
        state = self.load()
        if state.get('pending'):
            if not recover:
                raise Failure('Transazione interrotta: usare --recover.')
            self.guard(state, pending=True)
            target = state['pending']['from']
            self.activate(target)
            state.update(current=target, pending=None)
            self.save(state)
            return 'Recupero confermato: ' + target['tag']
        if recover:
            return 'Nessuna transazione interrotta.'
        self.guard(state)
        target = state.get('previous') or state['current']
        if target['sha'] == state['current']['sha']:
            self.health(target)
            return 'Gia alla versione di ripristino; nessun riavvio.'
        self.ensure_image(target)
        self.maintenance(state['current'], idle_confirmed)
        self.transaction(state, target)
        return 'Rollback confermato: ' + target['tag']

    def status(self):
        state = self.load()
        target = (state.get('pending') or {}).get('from') or state.get('previous') or state['current']
        print('Versione confermata:', state['current']['tag'])
        print('Commit:', state['current']['sha'])
        print('Last-known-good:', target['tag'])
        print('Transazione:', (state.get('pending') or {}).get('phase', 'nessuna'))
        self.guard(state, pending=bool(state.get('pending')))
        self.runtime_matches(state['current'])
        print('Git, immagine, mount e configurazione: coerenti')


def main():
    os.umask(0o077)
    if os.geteuid() != 0:
        raise Failure('Eseguire come root o tramite sudo.')
    args = sys.argv[1:]
    if args and TAG.fullmatch(args[0]):
        args.insert(0, 'deploy')
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('init', 'check', 'deploy'):
        part = sub.add_parser(name)
        part.add_argument('tag')
        if name == 'init':
            part.add_argument('--baseline-tests', type=Path)
        if name == 'deploy':
            part.add_argument('--idle-confirmed', action='store_true')
            part.add_argument('--data-compatible', action='store_true')
    sub.add_parser('status')
    part = sub.add_parser('rollback')
    part.add_argument('--idle-confirmed', action='store_true')
    part.add_argument('--recover', action='store_true')
    options = parser.parse_args(args)
    manager = Manager()
    def interrupted(signum, frame):
        raise Failure('Operazione interrotta da un segnale.')
    for sig in INTERRUPTS:
        signal.signal(sig, interrupted)
    try:
        with manager.locked():
            if options.command == 'init':
                manager.init(options.tag, options.baseline_tests)
                print('Baseline verificata e salvata:', options.tag)
            elif options.command == 'check':
                record = manager.prepare(options.tag)
                print('Release verificata e pronta:', record['tag'], record['sha'])
            elif options.command == 'deploy':
                print(manager.deploy(options.tag, options.idle_confirmed, options.data_compatible))
            elif options.command == 'rollback':
                print(manager.rollback(options.idle_confirmed, options.recover))
            else:
                manager.status()
    except (Failure, OSError, ValueError) as error:
        print('ERRORE:', error, file=sys.stderr)
        if manager.logfile:
            print('Log locale:', manager.logfile, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
