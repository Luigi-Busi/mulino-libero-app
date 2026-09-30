"""Real bind-mount checks with synthetic summaries, no production credentials."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


def run(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL).strip()


def main():
    os.umask(0o077)
    root = Path(tempfile.mkdtemp(prefix='mulino-panel-integration-', dir='/var/tmp'))
    panel = root / 'panel'
    panel.mkdir(mode=0o700)
    source = Path(__file__).resolve().parents[2]
    container = root.name
    report = dict(schema=1, checked_utc=datetime.now(timezone.utc).isoformat(), codes={c: 'OK' for c in (
        'mugnaio', 'browser', 'risponditore', 'disco', 'backup_creazione', 'backup_esportazione', 'backup_pc')})
    path = panel / 'status.json'
    path.write_text(json.dumps(report))
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    results = []
    def check(code):
        return run('docker', 'exec', container, 'python', '-c', code)
    try:
        run('docker', 'run', '-d', '--name', container, '--network', 'none', '--read-only',
            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--pids-limit', '32',
            '--memory', '128m', '--cpus', '0.5', '--mount', f'type=bind,src={source},dst=/suite,readonly',
            '--mount', f'type=bind,src={panel},dst=/run/mulino-panel,readonly',
            '-e', 'PYTHONPATH=/suite', '-e', 'PYTHONDONTWRITEBYTECODE=1', '--entrypoint', 'python',
            'sha256:03d21c7f3bf7773ffa6994489ab6b7ac8eb6c087eabd813f29fa6dc033494d49',
            '-c', 'import time; time.sleep(180)')
        text = check("from telegram_panel import controls_text; text=controls_text(); assert text.count('✅')==7; print('OK')")
        assert text == 'OK'
        results.append('container reads seven synthetic status codes from dedicated bind')
        check("""from pathlib import Path
try:
 Path('/run/mulino-panel/status.json').write_text('SHOULD NOT WRITE')
except OSError as error:
 assert error.errno == 30
else:
 raise AssertionError('bind writable')
""")
        assert hashlib.sha256(path.read_bytes()).hexdigest() == before
        mounts = json.loads(run('docker', 'inspect', container))[0]['Mounts']
        assert {m['Source'] for m in mounts} == {str(source), str(panel)}
        assert all(m['RW'] is False for m in mounts)
        results.append('writes rejected and no production data, secrets or Docker socket mounted')
        report['codes']['backup_pc'] = 'COPIA_PC_OBSOLETA'
        temporary = panel / 'replacement.json'
        temporary.write_text(json.dumps(report))
        os.replace(temporary, path)
        check("from telegram_panel import controls_text; assert '⚠️ Copia sul PC' in controls_text()")
        results.append('atomic host replacement visible without remount or bot restart')
        output = dict(status='passed', scenarios=results, protected_paths='synthetic_only')
        (root / 'report.json').write_text(json.dumps(output, indent=2))
        print(json.dumps(dict(report=str(root / 'report.json'), **output), indent=2))
    finally:
        subprocess.run(['docker', 'rm', '-f', container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
