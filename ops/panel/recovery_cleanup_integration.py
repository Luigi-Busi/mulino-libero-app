"""Recovery flags and cleanup survive restart, ZIP restore and old app reads."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

IMAGE = 'sha256:4ccb18804ed83bf8eb3a871853e9cb50fe59af273ca19b0b86332858425855c7'


def main():
    os.umask(0o077)
    root = Path(tempfile.mkdtemp(prefix='mulino-recovery-cleanup-', dir='/var/tmp'))
    data = root / 'fixture'
    data.mkdir()
    source = Path(__file__).resolve().parents[2]

    def execute(code, new=True):
        args = ['docker','run','--rm','--network','none','--read-only','--cap-drop','ALL',
            '--security-opt','no-new-privileges','--tmpfs','/tmp:rw,nosuid,nodev',
            '--memory','256m','--pids-limit','32','--cpus','1',
            '--mount',f'type=bind,src={data},dst=/fixture',
            '-e','PYTHONDONTWRITEBYTECODE=1','--entrypoint','python']
        if new:
            args += ['--mount',f'type=bind,src={source},dst=/suite,readonly',
                     '-e','PYTHONPATH=/suite','--workdir','/suite']
        result = subprocess.run(args+[IMAGE,'-c',code], capture_output=True,text=True)
        if result.returncode:
            raise RuntimeError('Synthetic recovery integration failed: '+result.stderr)

    execute('''from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from libero_mail_bot import Coordinator,QueueRequest,recovery_signature,hashlib,json
c=Coordinator(SimpleNamespace(admin_id=99,group_chat_id=-100,data_dir=Path('/fixture')),SimpleNamespace())
c.outcomes.set_queue_paused(True)
r=QueueRequest(2,'fixture','ANNULLATA','sheet','tab',4,3,'Fixture')
signature=hashlib.sha256(json.dumps(recovery_signature(r)).encode()).hexdigest()
c.outcomes.db.execute('INSERT INTO recovery_ignored VALUES (?,?)',('fixture',signature))
c.panel.bind(7,50)
with patch('telegram_panel.time.time',return_value=1800000000):
 c.panel.cleanup.track_response(7,40,1800000000)
 c.panel.cleanup.track_response(7,41,1800000000)
 c.panel.cleanup.track_recovery(7,42,'a'*16,'usage')
 c.panel.cleanup.track_recovery(7,43,'b'*16,'list')
c.outcomes.db.execute('UPDATE admin_recovery_messages SET sent_at=1800000000,delete_at=1800001800 WHERE message=42')
c.outcomes.db.execute('UPDATE admin_recovery_messages SET sent_at=1800000000 WHERE message=43')
c.messages.close();c.outcomes.close()
''')
    execute('''from pathlib import Path
from libero_mail_bot import CreatedOutcomes,LocalBackups
from telegram_panel import ReusablePanel
o=CreatedOutcomes(Path('/fixture'))
assert o.queue_paused() and ReusablePanel(o.db,99).message_id(7)==50
assert o.db.execute('SELECT COUNT(*) FROM recovery_ignored').fetchone()[0]==1
assert o.db.execute('SELECT COUNT(*) FROM admin_recovery_messages').fetchone()[0]==2
o.close()
b=LocalBackups(Path('/fixture')).create('manual')
LocalBackups.verify(Path('/fixture/backups')/b['filename'])
''',new=False)
    execute('''import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from zipfile import ZipFile
from libero_mail_bot import Coordinator,LocalBackups,QueueRequest,recovery_ignored
root=Path('/fixture');archive=next((root/'backups').glob('manual-*.zip'))
LocalBackups.verify(archive)
restored=root/'restored';restored.mkdir()
with ZipFile(archive) as z:
 for name in LocalBackups.filenames: (restored/name).write_bytes(z.read(name))
c=Coordinator(SimpleNamespace(admin_id=99,group_chat_id=-100,data_dir=restored),SimpleNamespace())
r=QueueRequest(2,'fixture','ANNULLATA','sheet','tab',4,3,'Fixture')
assert recovery_ignored(c,r) and c.outcomes.queue_paused()
bot=SimpleNamespace(id=7,delete_message=AsyncMock(return_value=True))
with patch('telegram_panel.time.time',return_value=1800001800):
 asyncio.run(c.panel.cleanup.drain(bot,lambda:c.panel.message_id(7)))
assert [x.kwargs['message_id'] for x in bot.delete_message.call_args_list]==[42]
with patch('telegram_panel.time.time',return_value=1800043200):
 asyncio.run(c.panel.cleanup.drain(bot,lambda:c.panel.message_id(7)))
assert [x.kwargs['message_id'] for x in bot.delete_message.call_args_list]==[42,40]
assert c.outcomes.db.execute('SELECT message FROM admin_response_history').fetchall()==[(41,)]
assert c.outcomes.db.execute('SELECT message FROM admin_recovery_messages').fetchall()==[(43,)]
assert c.panel.message_id(7)==50 and recovery_ignored(c,r)
c.messages.close();c.outcomes.close()
LocalBackups(Path('/fixture')).create('manual')
''')
    execute('''from pathlib import Path
from libero_mail_bot import LocalBackups
b,invalid=LocalBackups(Path('/fixture')).latest('manual')
assert b and invalid==0
''',new=False)
    report={'status':'passed','scenarios':[
        'v1.3.3 reads new database and preserves ignored flags, message deadlines and saved pause',
        'v1.3.3 creates verified ZIP containing all additional metadata',
        'ZIP restore resumes 30-minute usage and 12-hour reply cleanup, preserving latest reply, current panel and recovery list',
        'v1.3.3 verifies ZIP written by the new worker'],
        'production_data':'not_mounted','telegram':'mock_only','network':'none'}
    (root/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'report':str(root/'report.json'),**report},indent=2))


if __name__ == '__main__':
    main()
