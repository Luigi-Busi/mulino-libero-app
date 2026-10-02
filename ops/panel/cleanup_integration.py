"""Restart, restored-pointer safety and old-image ZIP compatibility, synthetic only."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

IMAGE = 'sha256:ac98ba8cbc18e857af0340ab492bcb755b28efa804ef2dfab1b88cfcf91d5b4e'


def main():
    os.umask(0o077)
    root = Path(tempfile.mkdtemp(prefix='mulino-menu-integration-', dir='/var/tmp'))
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
            args += ['--mount', f'type=bind,src={source},dst=/suite,readonly', '-e', 'PYTHONPATH=/suite', '--workdir', '/suite']
        result = subprocess.run(args + [IMAGE, '-c', code], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError('Synthetic integration failed: ' + result.stderr)

    execute("""import asyncio,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from telegram.error import TimedOut
from libero_mail_bot import CreatedOutcomes,MessageCleanup,QueueRequest
from telegram_panel import ReusablePanel
o=CreatedOutcomes(Path('/fixture'));MessageCleanup(Path('/fixture'));o.set_queue_paused(True)
r=QueueRequest(2,'fixture','IN_CREAZIONE','s','t',4,3,'',claimed_by='11')
o.save(r,'fixture','fixture@libero.it',sms_proof=(11,o.testers.now()))
p=ReusablePanel(o.db,99);p.bind(7,42);p.bind(7,44,retired_message=42)
p.cleanup.enqueue(7,50,'command')
t=int(time.time());Path('/fixture/clock.txt').write_text(str(t))
p.cleanup.track_response(7,80,t);p.cleanup.track_response(7,81,t)
bot=SimpleNamespace(id=7,delete_message=AsyncMock(side_effect=TimedOut()))
asyncio.run(p.cleanup.drain(bot,p.message_id(7)))
assert o.db.execute('SELECT COUNT(*) FROM admin_chat_cleanup').fetchone()[0]==2
o.close()
""")
    execute("""import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from libero_mail_bot import CreatedOutcomes
from telegram_panel import ReusablePanel
o=CreatedOutcomes(Path('/fixture'));p=ReusablePanel(o.db,99)
assert p.message_id(7)==44 and o.queue_paused() and o.testers.stats(11)['count']==1
bot=SimpleNamespace(id=7,delete_message=AsyncMock(return_value=True))
t=int(Path('/fixture/clock.txt').read_text())
with patch('telegram_panel.time.time',return_value=t+86400):
 asyncio.run(p.cleanup.drain(bot,p.message_id(7)))
assert [c.kwargs['message_id'] for c in bot.delete_message.call_args_list]==[42,50,80]
assert o.db.execute('SELECT message FROM admin_response_history').fetchall()==[(81,)]
p.cleanup.track_response(7,44,t);p.cleanup.track_response(7,79,t)
assert o.db.execute('SELECT COUNT(*) FROM admin_chat_cleanup').fetchone()[0]==0
p.cleanup.enqueue(7,44,'panel');o.close()
""")
    scenarios = ['restart preserves response ages; scheduled day-old replies, retired panel and command removed; latest response preserved']
    execute("""from pathlib import Path
from libero_mail_bot import CreatedOutcomes,LocalBackups
from telegram_panel import ReusablePanel
o=CreatedOutcomes(Path('/fixture'))
assert o.queue_paused() and o.testers.stats(11)['count']==1
assert ReusablePanel(o.db,99).message_id(7)==44
assert o.db.execute('SELECT COUNT(*) FROM admin_chat_cleanup').fetchone()[0]==1
assert o.db.execute('SELECT COUNT(*) FROM admin_response_history').fetchone()[0]==3
o.close()
b=LocalBackups(Path('/fixture')).create('manual')
assert b['retention_ok']
LocalBackups.verify(Path('/fixture/backups')/b['filename'])
""", new=False)
    scenarios.append('real v1.3.1 image preserves response history, pending jobs, tester counts and creates/verifies ZIP')
    execute("""import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from zipfile import ZipFile
from libero_mail_bot import CreatedOutcomes,LocalBackups
from telegram_panel import ReusablePanel
root=Path('/fixture');archive=next((root/'backups').glob('manual-*.zip'));LocalBackups.verify(archive)
restored=root/'restored';restored.mkdir()
with ZipFile(archive) as z:
 for name in LocalBackups.filenames:
  (restored/name).write_bytes(z.read(name))
o=CreatedOutcomes(restored);p=ReusablePanel(o.db,99)
bot=SimpleNamespace(id=7,delete_message=AsyncMock(return_value=True))
t=int((root/'clock.txt').read_text())
with patch('telegram_panel.time.time',return_value=t+86400):
 asyncio.run(p.cleanup.drain(bot,p.message_id(7)))
assert [c.kwargs['message_id'] for c in bot.delete_message.call_args_list]==[79]
assert o.db.execute('SELECT message FROM admin_response_history').fetchall()==[(81,)]
assert p.message_id(7)==44 and o.queue_paused() and o.testers.stats(11)['count']==1
assert o.db.execute('SELECT COUNT(*) FROM admin_chat_cleanup').fetchone()[0]==0
o.close()
""")
    scenarios.append('actual ZIP restore resumes aged-response cleanup while protecting latest response/current panel and preserving pause/tester counts')
    execute("""from pathlib import Path
from libero_mail_bot import LocalBackups
b=LocalBackups(Path('/fixture')).create('manual');assert b['retention_ok']
""")
    execute("""from pathlib import Path
from libero_mail_bot import LocalBackups
b,invalid=LocalBackups(Path('/fixture')).latest('manual');assert b and invalid==0
""", new=False)
    scenarios.append('previous backup verifier accepts ZIP created by new worker')
    report = dict(status='passed', scenarios=scenarios, protected_paths='synthetic_only', telegram='mock_only_no_real_calls')
    (root / 'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(dict(report=str(root / 'report.json'), **report), indent=2))


if __name__ == '__main__':
    main()
