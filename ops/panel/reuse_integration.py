"""Verify persisted pointer and old-version/backup compatibility with fake databases."""
import json
import os
from pathlib import Path
import subprocess
import tempfile


IMAGE='sha256:1c7d4858738a377661c8601ce7e336185fee2b6897e385e55c9aa07239255550'


def main():
    os.umask(0o077)
    root=Path(tempfile.mkdtemp(prefix='mulino-panel-reuse-',dir='/var/tmp'))
    data=root/'fixture'
    data.mkdir()
    source=Path(__file__).resolve().parents[2]
    def execute(code,new=True):
        args=['docker','run','--rm','--network','none','--read-only','--cap-drop','ALL',
              '--security-opt','no-new-privileges','--tmpfs','/tmp:rw,nosuid,nodev',
              '--memory','256m','--pids-limit','32','--cpus','1',
              '--mount',f'type=bind,src={data},dst=/fixture',
              '-e','PYTHONDONTWRITEBYTECODE=1','--entrypoint','python']
        if new:
            args+=['--mount',f'type=bind,src={source},dst=/suite,readonly','-e','PYTHONPATH=/suite','--workdir','/suite']
        args += [IMAGE,'-c',code]
        subprocess.run(args,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    results=[]
    execute("""from pathlib import Path
from libero_mail_bot import CreatedOutcomes,MessageCleanup
from telegram_panel import ReusablePanel
root=Path('/fixture')
outcomes=CreatedOutcomes(root)
MessageCleanup(root)
outcomes.set_queue_paused(True)
ReusablePanel(outcomes.db,99).bind(7,42)
outcomes.close()
""")
    execute("""from pathlib import Path
from libero_mail_bot import CreatedOutcomes
from telegram_panel import ReusablePanel
o=CreatedOutcomes(Path('/fixture'))
assert ReusablePanel(o.db,99).message_id(7)==42
assert o.queue_paused() is True and o.pending_count()==0
o.close()
""")
    results.append('pointer survives independent container restart; pause and outcomes preserved')
    execute("""from pathlib import Path
from libero_mail_bot import CreatedOutcomes,LocalBackups
o=CreatedOutcomes(Path('/fixture'))
assert o.queue_paused() is True and o.pending_count()==0
assert o.db.execute("SELECT value FROM runtime_settings WHERE key='admin_panel'").fetchone()
o.close()
backup=LocalBackups(Path('/fixture')).create('manual')
assert backup['retention_ok']
LocalBackups.verify(Path('/fixture/backups')/backup['filename'])
""",new=False)
    results.append('v1.2.0 worker and backup verifier accept new preference without schema migration')
    execute("""from pathlib import Path
from zipfile import ZipFile
from libero_mail_bot import CreatedOutcomes,LocalBackups
from telegram_panel import ReusablePanel
root=Path('/fixture')
archive=next((root/'backups').glob('manual-*.zip'))
LocalBackups.verify(archive)
restored=root/'restored'
restored.mkdir()
with ZipFile(archive) as zipped:
 for name in LocalBackups.filenames:
  (restored/name).write_bytes(zipped.read(name))
o=CreatedOutcomes(restored)
assert ReusablePanel(o.db,99).message_id(7)==42
assert o.queue_paused() is True and o.pending_count()==0
o.close()
""")
    results.append('verified synthetic ZIP restores pointer, pause and outcomes on separate copy')
    report=dict(status='passed',scenarios=results,protected_paths='synthetic_only')
    (root/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(dict(report=str(root/'report.json'),**report),indent=2))


if __name__=='__main__':
    main()
