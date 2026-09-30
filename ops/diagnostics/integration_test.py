"""Faults affect only named synthetic containers: never the production browser."""
import contextlib
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import uuid

import collector as module


IMAGE = 'sha256:4c79d59b34c442631468d4fc35d37dc120200d8c0ce29959ac2bdb4867c3a07f'
APP = Path(__file__).resolve().parents[2]


def docker(*args):
    result = subprocess.run(['docker', *args], text=True, capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError('Synthetic Docker command failed: ' + str(args[0]))
    return result.stdout.strip()


def wait_until(check, timeout=15):
    limit = time.monotonic() + timeout
    while time.monotonic() < limit:
        if check():
            return
        time.sleep(.2)
    raise AssertionError('Synthetic observation timed out')


def main():
    root = Path(tempfile.mkdtemp(prefix='mulino-diagnostics-test-', dir='/var/tmp'))
    prefix = 'mulino-diagnostics-test-' + uuid.uuid4().hex[:12]
    original = module.PROJECT, module.SERVICE, module.CONTAINER
    names = []
    results = []
    def passed(name):
        results.append(name)
        print('PASS:', name, flush=True)
    try:
        # Verify collection from stderr, filtering and Docker kill/die events.
        name = prefix + '-observer'
        names.append(name)
        module.PROJECT = prefix
        module.SERVICE = 'probe'
        module.CONTAINER = name
        code = "import logging,time; from browser_diagnostics import BrowserDiagnostics; logging.basicConfig(level=logging.INFO); print('PRIVATE email@example.test'); d=BrowserDiagnostics('fixture'); d.emit('session_start'); time.sleep(60)"
        docker('create', '--name', name, '--network', 'none', '--read-only', '--cap-drop', 'ALL',
               '--security-opt', 'no-new-privileges', '--tmpfs', '/tmp:rw,nosuid,nodev',
               '--label', 'com.docker.compose.project=' + prefix, '--label', 'com.docker.compose.service=probe',
               '--mount', 'type=bind,src=' + str(APP) + ',dst=/fixture,readonly', '-e', 'PYTHONPATH=/fixture',
               '--entrypoint', 'python', IMAGE, '-u', '-c', code)
        observer = module.Collector(root / 'observer')
        thread = threading.Thread(target=observer.serve)
        thread.start()
        logfile = root / 'observer/events.jsonl'
        def records():
            return [json.loads(line) for line in logfile.read_text().splitlines()]
        try:
            docker('start', name)
            wait_until(lambda: any(r['kind'] == 'browser' for r in records()))
            assert 'PRIVATE' not in logfile.read_text() and 'email@example.test' not in logfile.read_text()
            passed('collector captures diagnostic stderr and discards ordinary private logs')
            docker('kill', '--signal', 'KILL', name)
            wait_until(lambda: any(r['kind'] == 'docker' and r['event'] == 'die' and r.get('exit_code') == 137 for r in records()))
            passed('collector records container kill and exit code without restarting it')
            assert json.loads(docker('inspect', name))[0]['State']['Running'] is False
        finally:
            observer.shutdown()
            thread.join(timeout=15)
            assert not thread.is_alive()
        # Test the real launcher with fake display/VNC/websocket/bot programs.
        fake = root / 'fake-bin'
        fake.mkdir()
        for binary, component in (('Xvfb', 'display'), ('x11vnc', 'vnc'), ('websockify', 'websocket'), ('python', 'bot')):
            script = '#!/bin/bash\n'
            if binary == 'x11vnc':
                script += 'if [[ "$1" == -storepasswd ]]; then printf fixture > "$3"; exit 0; fi\n'
            script += f'if [[ "$MULINO_FIXTURE_COMPONENT" == {component} ]]; then sleep "${{MULINO_FIXTURE_DELAY:-0.5}}"; exit "${{MULINO_FIXTURE_EXIT_CODE:-23}}"; fi\nexec sleep 60\n'
            (fake / binary).write_text(script)
            (fake / binary).chmod(0o755)
        (fake / 'xdpyinfo').write_text('#!/bin/bash\nexit 0\n')
        (fake / 'xdpyinfo').chmod(0o755)
        for component in ('display', 'vnc', 'websocket', 'bot'):
            name = prefix + '-' + component
            names.append(name)
            docker('run', '-d', '--name', name, '--network', 'none', '--read-only', '--cap-drop', 'ALL',
                   '--security-opt', 'no-new-privileges', '--tmpfs', '/tmp:rw,nosuid,nodev', '--tmpfs', '/data:rw,nosuid,nodev',
                   '--mount', 'type=bind,src=' + str(fake) + ',dst=/fixture-bin,readonly',
                   '--mount', 'type=bind,src=' + str(APP / 'start.sh') + ',dst=/fixture-start.sh,readonly',
                   '-e', 'PATH=/fixture-bin:/usr/bin:/bin', '-e', 'VNC_PASSWORD=fixture',
                   '-e', 'MULINO_FIXTURE_COMPONENT=' + component, '--entrypoint', 'bash', IMAGE, '/fixture-start.sh')
            self_exit = docker('wait', name)
            assert self_exit == '23', (component, self_exit)
            logs = docker('logs', name)
            # Launcher uses stdout; docker logs stderr is irrelevant to these records.
            values = [module.decode_line(line) for line in logs.splitlines()]
            event = next(v for v in values if v and v['event'] == 'component_exit')
            assert event['component'] == component and event['exit_code'] == 23 and not event['expected']
            passed('launcher identifies first terminated ' + component + ' and preserves its exit status')
        for label, component, exit_code in (('clean-exit', 'bot', '0'), ('early-exit', 'display', '0'), ('term', 'none', '143')):
            name = prefix + '-' + label
            names.append(name)
            docker('run', '-d', '--name', name, '--network', 'none', '--read-only', '--cap-drop', 'ALL',
                   '--security-opt', 'no-new-privileges', '--tmpfs', '/tmp:rw,nosuid,nodev', '--tmpfs', '/data:rw,nosuid,nodev',
                   '--mount', 'type=bind,src=' + str(fake) + ',dst=/fixture-bin,readonly',
                   '--mount', 'type=bind,src=' + str(APP / 'start.sh') + ',dst=/fixture-start.sh,readonly',
                   '-e', 'PATH=/fixture-bin:/usr/bin:/bin', '-e', 'VNC_PASSWORD=fixture',
                   '-e', 'MULINO_FIXTURE_COMPONENT=' + component, '-e', 'MULINO_FIXTURE_EXIT_CODE=0',
                   '-e', 'MULINO_FIXTURE_DELAY=' + ('0' if label == 'early-exit' else '0.5'),
                   '--entrypoint', 'bash', IMAGE, '/fixture-start.sh')
            if label == 'term':
                time.sleep(1)
                docker('kill', '--signal', 'TERM', name)
            assert docker('wait', name) == exit_code
            values = [module.decode_line(line) for line in docker('logs', name).splitlines()]
            if label == 'term':
                assert any(v and v['event'] == 'signal' and v['expected'] and v['signal'] == 15 for v in values)
                assert not any(v and v['event'] == 'component_exit' for v in values)
                passed('requested service termination is distinguished from component failure')
            else:
                assert any(v and v['event'] == 'component_exit' and v['exit_code'] == 0 for v in values)
                passed('already terminated startup component is detected' if label == 'early-exit' else 'unexpected clean component exit remains visible')
    finally:
        module.PROJECT, module.SERVICE, module.CONTAINER = original
        for name in names:
            with contextlib.suppress(Exception):
                docker('rm', '-f', name)
        report = root / 'report.json'
        report.write_text(json.dumps({'passed': results, 'workspace': str(root)}, indent=2))
        print('REPORT:', report, flush=True)
    assert len(results) == 9


if __name__ == '__main__':
    main()
