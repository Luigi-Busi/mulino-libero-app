"""Real old-image/SQLite/ZIP compatibility tests, entirely on synthetic data."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

IMAGE = 'sha256:5c87211974dc0c7c2fb7446e7e4f8410489a146faf72f07462b2dc41d242d532'


def main():
    os.umask(0o077)
    root = Path(tempfile.mkdtemp(prefix='mulino-tester-integration-', dir='/var/tmp'))
    data = root / 'fixture'
    data.mkdir()
    source = Path(__file__).resolve().parents[2]

    def execute(code, new=True):
        args = ['docker', 'run', '--rm', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges', '--tmpfs', '/tmp:rw,nosuid,nodev',
                '--memory', '256m', '--pids-limit', '32', '--cpus', '1',
                '--mount', f'type=bind,src={data},dst=/fixture', '-e', 'PYTHONDONTWRITEBYTECODE=1',
                '--entrypoint', 'python']
        if new:
            args += ['--mount', f'type=bind,src={source},dst=/suite,readonly',
                     '-e', 'PYTHONPATH=/suite', '--workdir', '/suite']
        result = subprocess.run(args + [IMAGE, '-c', code], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError('Synthetic integration failed: ' + result.stderr)

    execute("""from pathlib import Path
from libero_mail_bot import CreatedOutcomes,MessageCleanup,QueueRequest
from telegram_panel import ReusablePanel
o=CreatedOutcomes(Path('/fixture')); MessageCleanup(Path('/fixture'))
o.set_queue_paused(True); ReusablePanel(o.db,99).bind(7,42)
for key,user in [('one',11),('two',11),('other',22)]:
 r=QueueRequest(2,key,'IN_CREAZIONE','s','t',4,3,'',claimed_by=str(user))
 o.save(r,'fixture','fixture@libero.it',sms_proof=(user,o.testers.now()))
o.testers.reset(11,99,o.testers.stats(11)['snapshot'])
r=QueueRequest(2,'new','IN_CREAZIONE','s','t',4,3,'',claimed_by='11')
o.save(r,'fixture','fixture@libero.it',sms_proof=(11,o.testers.now()))
o.close()
""")
    execute("""from pathlib import Path
from libero_mail_bot import CreatedOutcomes
from telegram_panel import ReusablePanel
o=CreatedOutcomes(Path('/fixture'))
assert o.testers.stats(11)['count']==1 and o.testers.stats(11)['total']==3
assert o.testers.stats(22)['count']==1 and o.pending_count()==4
assert o.queue_paused() and ReusablePanel(o.db,99).message_id(7)==42
o.close()
""")
    scenarios = ['counts, reset history, pause and panel survive separate container restart']
    execute("""from pathlib import Path
from libero_mail_bot import CreatedOutcomes,LocalBackups,QueueRequest
o=CreatedOutcomes(Path('/fixture'))
assert o.queue_paused() and o.pending_count()==4
# The real previous worker ignores additional tables and can still save an outcome.
o.save(QueueRequest(2,'rollback','IN_CREAZIONE','s','t',4,3,'',claimed_by='11'),'fixture','fixture@libero.it')
o.close()
b=LocalBackups(Path('/fixture')).create('manual')
assert b['retention_ok']
LocalBackups.verify(Path('/fixture/backups')/b['filename'])
""", new=False)
    scenarios.append('real v1.2.1 image saves outcomes and creates/verifies ZIP with new tables')
    execute("""from pathlib import Path
from zipfile import ZipFile
from libero_mail_bot import CreatedOutcomes,LocalBackups,QueueRequest
from telegram_panel import ReusablePanel
root=Path('/fixture'); archive=next((root/'backups').glob('manual-*.zip'))
LocalBackups.verify(archive)
restored=root/'restored';restored.mkdir()
with ZipFile(archive) as z:
 for name in LocalBackups.filenames:
  (restored/name).write_bytes(z.read(name))
o=CreatedOutcomes(restored)
assert o.testers.stats(11)['count']==1 and o.testers.stats(11)['total']==3
assert o.testers.stats(22)['count']==1 and o.pending_count()==5
assert o.queue_paused() and ReusablePanel(o.db,99).message_id(7)==42
# Old-worker completions and duplicate pre-reset requests cannot get retroactive credit.
for key in ('rollback','one'):
 o.save(QueueRequest(2,key,'IN_CREAZIONE','s','t',4,3,'',claimed_by='11'),'fixture','fixture@libero.it',sms_proof=(11,o.testers.now()))
assert o.testers.stats(11)['count']==1 and o.testers.stats(11)['total']==3
o.close()
""")
    scenarios.append('actual ZIP restore preserves counts/reset and never credits rollback or duplicate history')
    execute("""from pathlib import Path
from libero_mail_bot import CreatedOutcomes,LocalBackups
o=CreatedOutcomes(Path('/fixture'));o.close()
b=LocalBackups(Path('/fixture')).create('manual')
assert b['retention_ok']
""")
    execute("""from pathlib import Path
from libero_mail_bot import LocalBackups
b,invalid=LocalBackups(Path('/fixture')).latest('manual')
assert b and invalid==0
""", new=False)
    scenarios.append('previous backup verifier accepts ZIP created by new worker')
    report = dict(status='passed', scenarios=scenarios, protected_paths='synthetic_only')
    (root / 'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(dict(report=str(root / 'report.json'), **report), indent=2))


if __name__ == '__main__':
    main()
