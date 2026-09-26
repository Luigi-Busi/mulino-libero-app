#!/usr/bin/env python3
"""Restore only onto an empty server. All real services remain stopped."""
import argparse
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
from verify_payload import verify


def run(args, **kwargs):
    result = subprocess.run([str(v) for v in args], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, **kwargs)
    if result.returncode:
        raise RuntimeError('Restore step failed: ' + str(args[0]))
    return result.stdout.decode()


def restore(core, images, confirmed):
    started = time.monotonic()
    os.umask(0o077)
    if os.geteuid() != 0 or not confirmed:
        raise ValueError('Root and --empty-server-confirmed are required')
    for p in ['/opt/mulino-libero', '/var/lib/mulino-deploy', '/usr/local/lib/mulino-deploy']:
        if Path(p).exists():
            raise ValueError('Destination is not empty: ' + p)
    if run(['docker', 'ps', '-aq']).strip():
        raise ValueError('Destination already has containers')
    # Production was upgraded and retains overlay2. Fresh Docker 29 defaults
    # to a different image store, which changes image identity semantics.
    docker_info = json.loads(run(['docker', 'info', '--format', '{{json .}}']))
    if docker_info['Driver'] != 'overlay2':
        raise ValueError('An empty Docker engine using overlay2 is required; see recovery guide')
    stage = Path('/var/lib/mulino-restore/payload')
    if stage.exists():
        raise ValueError('A restore payload already exists; inspect previous attempt')
    result = verify(core, stage)
    manifest = json.loads((stage / 'manifest.json').read_text())
    if manifest.get('docker_storage_driver', 'overlay2') != docker_info['Driver']:
        raise ValueError('Source and destination Docker storage drivers differ')
    for record in [manifest['current'], manifest['previous']]:
        if not re.fullmatch('sha256:[a-f0-9]{64}', record['image']) or not re.fullmatch('[a-f0-9]{40}', record['sha']):
            raise ValueError('Invalid immutable release identity')
    # Validate every payload name before installing files.
    permitted = ['opt/mulino-libero/', 'var/lib/mulino-deploy/',
                 'usr/local/lib/mulino-deploy/', 'usr/local/lib/mulino-recovery/',
                 'usr/local/lib/mulino-monitor/', 'etc/mulino-monitor/',
                 'usr/local/sbin/mulino-', 'etc/systemd/system/mulino-',
                 'etc/systemd/system/bot-risponditore.service',
                 'etc/mulino-recovery/', 'root/.ssh/', 'home/backupmulino/.ssh/']
    for source in (stage / 'rootfs').rglob('*'):
        if source.is_file():
            rel = source.relative_to(stage / 'rootfs').as_posix()
            if not any(rel.startswith(prefix) for prefix in permitted):
                raise ValueError('Unapproved restoration path')
    run(['docker', 'image', 'load', '-i', images], timeout=1200)
    for record in [manifest['current'], manifest['previous']]:
        actual = json.loads(run(['docker', 'image', 'inspect', record['image']]))[0]['Id']
        if actual != record['image']:
            raise ValueError('Wrong restored image')
        run(['docker', 'tag', record['image'], record['image_tag']])
    if subprocess.run(['id', 'backupmulino'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        run(['useradd', '--create-home', '--shell', '/bin/bash', 'backupmulino'])
    # Remote access identity must be reviewed, never replace the rescue SSH keys.
    for source in (stage / 'rootfs').rglob('*'):
        if not source.is_file():
            continue
        rel = source.relative_to(stage / 'rootfs')
        if rel.parts[:2] == ('root', '.ssh') or rel.parts[:3] == ('home', 'backupmulino', '.ssh'):
            continue
        target = Path('/') / rel
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if target.exists():
            raise ValueError('Would overwrite existing target: ' + str(target))
        shutil.copy2(source, target)
    app = Path('/opt/mulino-libero/app')
    # Clone to a temporary empty location, then merge only the ignored env file.
    clone = stage / 'checkout'
    run(['git', 'clone', stage / 'repository.bundle', clone])
    run(['git', '-C', clone, 'checkout', '--detach', manifest['current']['sha']])
    for child in clone.iterdir():
        if (app / child.name).exists():
            raise ValueError('Unexpected conflict with tracked source')
        shutil.move(child, app / child.name)
    run(['git', '-C', app, 'remote', 'set-url', 'origin',
         'git@github-mulino-app:Luigi-Busi/mulino-libero-app.git'])
    env = app.parent / '.env'
    env.chmod(0o600)
    (app / 'bot_risponditore.env').chmod(0o600)
    (app.parent / 'secrets').chmod(0o700)
    for p in (app.parent / 'secrets').iterdir():
        p.chmod(0o600)
    data = app.parent / 'data'
    data.chmod(0o700)
    outcomes = data / 'created-outcomes.sqlite3'
    with sqlite3.connect(outcomes) as db:
        assert db.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
        db.execute("INSERT INTO runtime_settings(key,value) VALUES('queue_paused','1') ON CONFLICT(key) DO UPDATE SET value='1'")
        count = db.execute('SELECT count(*) FROM outcomes').fetchone()[0]
    with sqlite3.connect(data / 'telegram-cleanup.sqlite3') as db:
        assert db.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
    run(['python3', '-m', 'venv', app / '.venv-risponditore'])
    run([app / '.venv-risponditore/bin/python', '-m', 'pip', 'install', '--no-index',
         '--find-links', stage / 'wheels', '-r', stage / 'risponditore-requirements.txt'], timeout=180)
    # Archived secret inode numbers cannot match the new machine. Rebaseline only
    # after all file hashes and strict permissions have been verified above.
    state_path = Path('/var/lib/mulino-deploy/state.json')
    state = json.loads(state_path.read_text())
    if state['pending']:
        raise ValueError('Unexpected pending deploy in stable system archive')
    state['configuration'] = {'env': hashlib.sha256(env.read_bytes()).hexdigest(), 'secrets': {}}
    for p in sorted((app.parent / 'secrets').iterdir()):
        s = p.stat()
        state['configuration']['secrets'][p.name] = [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_mode]
    state_path.write_text(json.dumps(state, indent=2))
    state_path.chmod(0o600)
    image_dir = Path('/var/lib/mulino-deploy/images')
    image_dir.mkdir(mode=0o700)
    # The external image set already contains both immutable releases. Keep one
    # physical copy and hardlink both expected rollback names to it. This avoids
    # docker-save scratch space and duplicate multi-gigabyte layers on recovery.
    shared = image_dir / (state['current']['image'].split(':')[1] + '.tar')
    shutil.copyfile(images, shared)
    shared.chmod(0o600)
    for r in [state['current'], state['previous']]:
        target = image_dir / (r['image'].split(':')[1] + '.tar')
        if target != shared:
            os.link(shared, target)
    # No Telegram polling, startup messages, or cleanup jobs before cutover.
    run(['systemctl', 'daemon-reload'])
    for unit in ['bot-risponditore.service', 'mulino-backup-export.timer', 'mulino-system-backup.timer']:
        run(['systemctl', 'disable', unit])
    if Path('/etc/systemd/system/mulino-monitor.timer').exists():
        run(['systemctl', 'disable', 'mulino-monitor.timer'])
    (Path('/var/lib/mulino-restore') / 'SERVICES-NOT-ACTIVATED').write_text(
        'Start only after the original server is off and the Sheets queue is reconciled.\n')
    result.update(restored_outcomes=count, queue_paused=True, services_started=False,
                  images_verified=2, duration_seconds=round(time.monotonic()-started, 1))
    Path('/var/lib/mulino-restore/report.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--core', type=Path, required=True)
    p.add_argument('--images', type=Path, required=True)
    p.add_argument('--empty-server-confirmed', action='store_true')
    args = p.parse_args()
    restore(args.core, args.images, args.empty_server_confirmed)
