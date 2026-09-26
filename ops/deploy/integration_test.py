"""Real Docker/Git tests in an isolated project, never using production mounts."""
import contextlib
import dataclasses
import json
import os
from pathlib import Path
import subprocess
import tempfile

from controller import Config, Failure, Manager, digest


def command(*args, cwd=None):
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr[-3000:])
    return result.stdout.strip()


class RecordedManager(Manager):
    offline_recovery = False

    def run(self, args, **kwargs):
        if self.offline_recovery:
            assert not any(str(a) in {'build', 'pull', 'fetch', 'ls-remote'} for a in args), args
        return super().run(args, **kwargs)


def main():
    os.umask(0o077)
    root = Path(tempfile.mkdtemp(prefix='mulino-deploy-integration-', dir='/var/tmp'))
    project = root.name
    app = root / 'app'
    app.mkdir()
    (root / 'data').mkdir()
    (root / 'secrets').mkdir()
    (root / 'data' / 'marker').write_text('DATA MUST NOT CHANGE\n')
    (root / 'secrets' / 'probe').write_text('SYNTHETIC TEST SECRET\n')
    (root / '.env').write_text('FIXTURE=1\n')
    protected = [root / 'data' / 'marker', root / 'secrets' / 'probe']
    before = [(str(p), digest(p), p.stat().st_mtime_ns, p.stat().st_mode) for p in protected]
    model = {'name': project, 'services': {'probe': {
        'build': '.', 'image': project + ':initial', 'container_name': project,
        'restart': 'unless-stopped', 'init': True, 'stop_grace_period': '2s',
        'env_file': ['../.env'], 'volumes': ['../data:/data'],
        'secrets': [{'source': 'probe', 'target': 'probe'}],
        'healthcheck': {'test': ['CMD', 'python', '-c',
            "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080',timeout=1)"],
            'interval': '1s', 'timeout': '2s', 'retries': 2, 'start_period': '1s'}
    }}, 'secrets': {'probe': {'file': '../secrets/probe'}}}
    (app / 'docker-compose.yml').write_text(json.dumps(model))
    (app / 'Dockerfile').write_text('FROM python:3.12-slim\nWORKDIR /app\nCOPY libero_mail_bot.py start.sh requirements.txt /app/\nCMD ["python", "/app/libero_mail_bot.py"]\n')
    (app / 'requirements.txt').write_text('# no extra packages\n')
    (app / 'start.sh').write_text('#!/bin/sh\nexec python /app/libero_mail_bot.py\n')
    (app / 'bot_risponditore.py').write_text('# separate service placeholder\n')
    (app / 'install_risponditore.sh').write_text('# never executed\n')
    (app / 'VERSION').write_text('1.0.0\n')
    (app / 'tests').mkdir()
    test_code = 'import unittest\nclass Probe(unittest.TestCase):\n def test_release(self):\n  self.assertTrue(True)\n'
    (app / 'tests' / 'test_probe.py').write_text(test_code)
    def worker(version, broken=False):
        (app / 'libero_mail_bot.py').write_text(f'''import sys
from pathlib import Path
if '--check' in sys.argv:
    assert not Path('/data/marker').exists(), 'production volume leaked into preflight'
    assert Path('/run/secrets/probe').read_text() == 'SYNTHETIC TEST SECRET\\n'
    print('fixture preflight OK')
    sys.exit(0)
VERSION = {version!r}
FIXTURE_ID = {project!r}
if {broken!r}: sys.exit(1)
from http.server import HTTPServer, SimpleHTTPRequestHandler
HTTPServer(('0.0.0.0',8080), SimpleHTTPRequestHandler).serve_forever()
''')
    def git(*args):
        return command('git', '-C', str(app), *args)
    def commit(tag):
        git('add', '.')
        git('commit', '-m', tag)
        git('tag', '-a', tag, '-m', tag)
    worker('1.0.0')
    git('init', '-b', 'main')
    git('config', 'user.name', 'Mulino integration test')
    git('config', 'user.email', 'test@localhost')
    commit('v1.0.0')
    git('checkout', '-b', 'candidates')
    worker('1.0.1')
    commit('v1.0.1')
    worker('1.0.2', broken=True)
    commit('v1.0.2')
    worker('1.0.3')
    (app / 'tests' / 'test_probe.py').write_text(test_code.replace('assertTrue(True)', 'assertTrue(False)'))
    commit('v1.0.3')
    (app / 'tests' / 'test_probe.py').write_text(test_code)
    model['services']['probe']['restart'] = 'always'
    (app / 'docker-compose.yml').write_text(json.dumps(model))
    commit('v1.0.4')
    git('checkout', 'main')
    command('git', 'clone', '--bare', str(app), str(root / 'origin.git'))
    git('remote', 'add', 'origin', str(root / 'origin.git'))
    config = Config(app=app, state=root / 'state', project=project, service='probe', container=project,
                    image_repo=project, require_pause=False, minimum_free=0, health_timeout=20,
                    settle_seconds=1, poll_seconds=1,
                    health_code="import urllib.request; assert urllib.request.urlopen('http://127.0.0.1:8080',timeout=2).status==200")
    manager = RecordedManager(config)
    results = []
    def passed(name):
        results.append(name)
        print('PASS:', name, flush=True)
    try:
        command('docker', 'compose', '-p', project, '-f', str(app / 'docker-compose.yml'),
                'up', '-d', '--build', '--wait', '--wait-timeout', '60')
        with manager.locked():
            manager.init('v1.0.0')
            passed('baseline adoption and isolated preflight')
            initial_id = manager.inspect()['Id']
            manager.deploy('v1.0.0')
            assert manager.inspect()['Id'] == initial_id
            passed('same-version deployment does not restart')
            manager.deploy('v1.0.1', True, True)
            assert manager.load()['previous']['tag'] == 'v1.0.0'
            assert manager.load()['current']['tag'] == 'v1.0.1'
            passed('successful deployment with real Compose')
            manager.offline_recovery = True
            manager.rollback(True)
            manager.offline_recovery = False
            assert manager.load()['current']['tag'] == 'v1.0.0'
            passed('manual rollback without build or network fetch')
            try:
                manager.deploy('v1.0.2', True, True)
                raise AssertionError('bad runtime was accepted')
            except Failure as error:
                assert 'ripristinata' in str(error), str(error)
            assert manager.load()['current']['tag'] == 'v1.0.0'
            assert manager.inspect()['State']['Running']
            passed('failed startup automatically restores healthy previous image')
            stable_id = manager.inspect()['Id']
            try:
                manager.deploy('v1.0.3', True, True)
                raise AssertionError('failed tests were accepted')
            except Failure:
                pass
            assert manager.inspect()['Id'] == stable_id
            assert manager.load()['pending'] is None
            passed('failed regression tests leave running container untouched')
            try:
                manager.prepare('v1.0.4')
                raise AssertionError('changed infrastructure was accepted')
            except Failure as error:
                assert 'separatamente' in str(error)
            passed('infrastructure changes are rejected')
            version = (app / 'VERSION').read_text()
            (app / 'VERSION').write_text('dirty\n')
            try:
                manager.prepare('v1.0.1')
                raise AssertionError('dirty source was accepted')
            except Failure:
                pass
            (app / 'VERSION').write_text(version)
            passed('uncommitted edits are preserved and block deployment')
            next_record = manager.prepare('v1.0.1')
            state = manager.load()
            state['pending'] = {'from': state['current'], 'to': next_record, 'phase': 'activating'}
            manager.save(state)
            manager.activate(next_record)
            manager.offline_recovery = True
            manager.rollback(recover=True)
            manager.offline_recovery = False
            assert manager.load()['current']['tag'] == 'v1.0.0'
            assert manager.load()['pending'] is None
            passed('interrupted transaction recovers from durable journal')
            # Remove only an inactive image built by this unique test project.
            assert next_record['image'] != manager.inspect()['Image']
            command('docker', 'image', 'rm', next_record['image_tag'])
            missing = subprocess.run(['docker', 'image', 'inspect', next_record['image']], capture_output=True)
            assert missing.returncode != 0, 'image must really be absent before archive recovery'
            manager.offline_recovery = True
            manager.rollback(True)
            manager.offline_recovery = False
            assert manager.load()['current']['tag'] == 'v1.0.1'
            passed('rollback reloads missing image from local archive')
            after = [(str(p), digest(p), p.stat().st_mtime_ns, p.stat().st_mode) for p in protected]
            assert before == after
            passed('data and secrets content, timestamps and permissions unchanged')
    finally:
        # Only the named synthetic project is removed; no volumes are deleted.
        command('docker', 'compose', '-p', project, '-f', str(app / 'docker-compose.yml'), 'down')
        report = root / 'report.json'
        report.write_text(json.dumps({'passed': results, 'workspace': str(root)}, indent=2))
        print('REPORT:', report, flush=True)
    assert len(results) == 11


if __name__ == '__main__':
    main()
