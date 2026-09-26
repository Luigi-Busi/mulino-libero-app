#!/usr/bin/env python3
"""Public-key encrypted, online snapshots. Never writes live data or secrets."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timezone

ROOT = Path('/var/lib/mulino-recovery')
OUT = Path('/srv/mulino-backups-export/system')
APP = Path('/opt/mulino-libero/app')
DEPLOY = Path('/var/lib/mulino-deploy')
CONFIG = Path('/etc/mulino-recovery')


def run(args, **kwargs):
    result = subprocess.run([str(x) for x in args], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, **kwargs)
    if result.returncode:
        # Subprocess output can contain credentials; keep it out of journals.
        raise RuntimeError('Operation failed: ' + str(args[0]))
    return result.stdout


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(value, indent=2) + '\n')
    path.chmod(0o600)


def publish(path):
    import grp
    path.chmod(0o640)
    os.chown(path, 0, grp.getgrnam('backupmulino').gr_gid)


def encrypt(command, destination):
    recipient = (CONFIG / 'recipient.txt').read_text().strip()
    if not re.fullmatch('[A-F0-9]{40}', recipient):
        raise ValueError('Invalid recipient fingerprint')
    temporary = destination.with_suffix(destination.suffix + '.partial')
    try:
        with temporary.open('xb') as output, tempfile.TemporaryFile() as errors:
            producer = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors)
            consumer = subprocess.Popen(['gpg', '--homedir', str(CONFIG / 'gnupg'),
                '--batch', '--trust-model', 'always', '--cipher-algo', 'AES256',
                '--compress-algo', 'zlib', '--compress-level', '3',
                '--recipient', recipient, '--encrypt'],
                stdin=producer.stdout, stdout=output, stderr=errors)
            producer.stdout.close()
            code = consumer.wait()
            producer_code = producer.wait()
            if code or producer_code:
                raise RuntimeError('Encryption or source stream failed')
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
        publish(destination)
    finally:
        temporary.unlink(missing_ok=True)


def copy_file(source, stage):
    source = Path(source)
    if source.is_symlink() or not source.is_file():
        raise ValueError('Required file absent or not regular: ' + str(source))
    target = stage / 'rootfs' / source.relative_to('/')
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    shutil.copy2(source, target)


def copy_tree(source, stage):
    source = Path(source)
    for p in sorted(source.rglob('*')):
        if p.is_symlink():
            raise ValueError('Unexpected symlink: ' + str(p))
        if p.is_file():
            copy_file(p, stage)


def snapshot(source, target):
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=30) as src:
        with sqlite3.connect(target) as dst:
            src.backup(dst, pages=128, sleep=0.1)
            if dst.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise ValueError('SQLite integrity check failed')
    target.chmod(0o600)


def backup():
    os.umask(0o077)
    ROOT.mkdir(mode=0o700, exist_ok=True)
    OUT.mkdir(mode=0o750, exist_ok=True)
    if shutil.disk_usage(ROOT).free < 5 * 1024**3:
        raise RuntimeError('Less than 5 GiB free; backup not started')
    # Lock order is fixed: backup, then deploy. No active app operation is stopped.
    with (ROOT / 'lock').open('a') as lock, (DEPLOY / 'lock').open('a') as deploy_lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(deploy_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads((DEPLOY / 'state.json').read_text())
        if state.get('pending'):
            raise RuntimeError('Deploy pending; resolve before full backup')
        head = run(['git', '-C', APP, 'rev-parse', 'HEAD']).decode().strip()
        if head != state['current']['sha'] or run(['git', '-C', APP, 'status', '--porcelain']).strip():
            raise RuntimeError('Application checkout does not match stable release')
        records = [state['current']]
        if state.get('previous'):
            records.append(state['previous'])
        image_ids = sorted(set(r['image'] for r in records))
        image_key = hashlib.sha256('\n'.join(image_ids).encode()).hexdigest()
        asset = OUT / ('images-' + image_key + '.tar.gpg')
        metadata = asset.with_suffix(asset.suffix + '.json')
        if asset.exists():
            meta = json.loads(metadata.read_text())
            if meta['sha256'] != digest(asset) or meta['images'] != image_ids:
                raise ValueError('Existing image asset damaged')
        else:
            encrypt(['docker', 'image', 'save', *image_ids], asset)
            meta = {'file': asset.name, 'sha256': digest(asset), 'bytes': asset.stat().st_size,
                    'images': image_ids}
            write_json(metadata, meta)
            publish(metadata)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        with tempfile.TemporaryDirectory(prefix='stage-', dir=ROOT) as temp:
            stage = Path(temp)
            for source in ['/opt/mulino-libero/.env', APP / 'bot_risponditore.env',
                '/usr/local/sbin/mulino-deploy', '/usr/local/sbin/mulino-rollback',
                '/usr/local/sbin/mulino-export-backups',
                '/etc/systemd/system/bot-risponditore.service',
                '/etc/systemd/system/mulino-backup-export.service',
                '/etc/systemd/system/mulino-backup-export.timer',
                '/etc/systemd/system/mulino-system-backup.service',
                '/etc/systemd/system/mulino-system-backup.timer',
                DEPLOY / 'state.json', DEPLOY / 'last-known-good', DEPLOY / 'runtime-image.json']:
                copy_file(source, stage)
            for tree in ['/opt/mulino-libero/secrets', '/usr/local/lib/mulino-deploy',
                         '/usr/local/lib/mulino-recovery', DEPLOY / 'releases']:
                copy_tree(tree, stage)
            for tree in ['/usr/local/lib/mulino-monitor', '/etc/mulino-monitor',
                         '/etc/systemd/system/bot-risponditore.service.d']:
                if Path(tree).exists():
                    copy_tree(tree, stage)
            for unit in ['mulino-monitor.service', 'mulino-monitor.timer']:
                path = Path('/etc/systemd/system') / unit
                if path.exists():
                    copy_file(path, stage)
            for name in ['config', 'known_hosts', 'authorized_keys', 'mulino_github_app', 'mulino_github_app.pub']:
                copy_file(Path('/root/.ssh') / name, stage)
            copy_file('/home/backupmulino/.ssh/authorized_keys', stage)
            copy_file(CONFIG / 'public-key.asc', stage)
            copy_file(CONFIG / 'recipient.txt', stage)
            # Preserve host settings as reference, never automatically replay
            # firewall/SSH settings on a server with potentially different IPs.
            host_files = [Path('/etc/ssh/sshd_config')]
            for directory in ['/etc/ssh/sshd_config.d', '/etc/docker', '/etc/ufw']:
                if Path(directory).exists():
                    host_files.extend(p for p in Path(directory).rglob('*') if p.is_file())
            for p in host_files:
                if p.is_symlink():
                    raise ValueError('Unexpected host-configuration symlink')
                target = stage / 'host-reference' / p.relative_to('/')
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                shutil.copy2(p, target)
            run(['git', '-C', APP, 'bundle', 'create', stage / 'repository.bundle', '--all', 'HEAD'])
            run(['git', '-C', APP, 'bundle', 'verify', stage / 'repository.bundle'])
            for name in ['created-outcomes.sqlite3', 'telegram-cleanup.sqlite3']:
                snapshot(APP.parent / 'data' / name, stage / 'rootfs/opt/mulino-libero/data' / name)
            # Package exact Risponditore dependencies for reinstall without PyPI.
            python = APP / '.venv-risponditore/bin/python'
            pinned = run([python, '-m', 'pip', 'freeze', '--all']).decode()
            (stage / 'risponditore-requirements.txt').write_text(pinned)
            cache = ROOT / 'wheels' / hashlib.sha256(pinned.encode()).hexdigest()
            if not (cache / 'complete').exists():
                cache.mkdir(parents=True, exist_ok=True, mode=0o700)
                req = cache / 'requirements.txt'
                req.write_text(pinned)
                run([python, '-m', 'pip', 'download', '--only-binary=:all:', '--dest', cache, '-r', req], timeout=300)
                (cache / 'complete').write_text('ok\n')
            wheels = stage / 'wheels'
            wheels.mkdir()
            for p in cache.glob('*.whl'):
                shutil.copy2(p, wheels / p.name)
            google = stage / 'google'
            google.mkdir()
            run(['docker', 'run', '--rm', '--read-only', '--cap-drop=ALL',
                 '--security-opt=no-new-privileges', '--entrypoint', 'python',
                 '--mount', 'type=bind,src=/opt/mulino-libero/secrets/google-service-account.json,dst=/credentials.json,readonly',
                 '--mount', 'type=bind,src=/usr/local/lib/mulino-recovery/export_google.py,dst=/export.py,readonly',
                 '--mount', 'type=bind,src=' + str(google) + ',dst=/output',
                 state['current']['image'], '/export.py'], timeout=300)
            system = run(['dpkg-query', '-W', '-f=${Package}=${Version}\n']).decode()
            (stage / 'ubuntu-packages.txt').write_text(system)
            docker_info = json.loads(run(['docker', 'info', '--format', '{{json .}}']))
            if docker_info['Driver'] != 'overlay2':
                raise ValueError('Docker image store changed; revalidate recovery before backup')
            manifest = {'format': 'mulino-system-v1', 'created_utc': stamp,
                'docker_storage_driver': docker_info['Driver'],
                'docker_engine_version': docker_info['ServerVersion'],
                'current': state['current'], 'previous': state.get('previous'),
                'image_asset': meta, 'files': {},
                'limits': ['SQLite snapshots and Google reads are sequential, not one global transaction.',
                           'Apps Script live source, properties and triggers require a separate verified export.',
                           'No mailbox messages, browser session or in-progress registration state.']}
            total_bytes = 0
            for p in sorted(stage.rglob('*')):
                if p.is_file():
                    total_bytes += p.stat().st_size
                    if p.stat().st_size > 512 * 1024**2 or total_bytes > 1024**3:
                        raise ValueError('Payload exceeds verified recovery size limits')
                    manifest['files'][p.relative_to(stage).as_posix()] = {
                        'sha256': digest(p), 'bytes': p.stat().st_size, 'mode': p.stat().st_mode & 0o777}
            write_json(stage / 'manifest.json', manifest)
            archive = OUT / ('system-' + stamp + '.tar.gpg')
            encrypt(['tar', '-C', str(stage), '-cf', '-', '.'], archive)
            summary = {'format': 'mulino-system-index-v1', 'created_utc': stamp,
                       'file': archive.name, 'sha256': digest(archive), 'bytes': archive.stat().st_size,
                       'image_asset': meta, 'recipient': (CONFIG / 'recipient.txt').read_text().strip(),
                       'current': state['current']['tag'], 'previous': state.get('previous', {}).get('tag')}
            index = OUT / ('system-' + stamp + '.json')
            write_json(index, summary)
            publish(index)
            write_json(ROOT / 'last-success.json', summary)
            print(json.dumps(summary))


if __name__ == '__main__':
    try:
        backup()
    except Exception as exc:
        # No tracebacks containing live environment or Google data.
        print('Backup failed: ' + type(exc).__name__ + ': ' + str(exc))
        raise SystemExit(1)
