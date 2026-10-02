import hashlib,json,sqlite3,tarfile,tempfile,unittest
from pathlib import Path
import email_monitor as m
from backup_system import snapshot
from verify_payload import verify

class RecoveryTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.db=m.State(self.root/'live.sqlite3')
  self.account=m.Account('sisal','test@libero.it','Test','book','Sisal Sport',10,10,'id')
  self.db.sync([self.account])
  with self.db.db:
   self.db.advance(self.account.email,'sisal','INBOX',1,3,55)
   self.db.db.execute("INSERT INTO events(event_key,email,operator,subject,received,status,created,updated) VALUES('key','test@libero.it','sisal','Test','date','sent','now','now')")
 def tearDown(self):self.db.db.close();self.temp.cleanup()
 def test_online_wal_snapshot_preserves_cursors_and_notifications(self):
  target=self.root/'snapshot.sqlite3';snapshot(self.root/'live.sqlite3',target);restored=m.State(target)
  try:
   self.assertEqual(restored.cursor('test@libero.it','sisal','INBOX')['uid'],55)
   self.assertEqual(restored.status()['delivery'],{'sent':1});self.assertEqual(restored.status()['integrity'],'ok')
  finally:restored.db.close()
 def test_backup_does_not_change_live_baseline(self):
  snapshot(self.root/'live.sqlite3',self.root/'snapshot.sqlite3')
  self.assertEqual(self.db.cursor('test@libero.it','sisal','INBOX')['uid'],55);self.assertEqual(self.db.generation('test@libero.it','sisal'),1)
 def package(self):
  stage=self.root/'stage';dbpath=stage/'rootfs/opt/mulino-libero/data/email-monitor/monitor.sqlite3';snapshot(self.root/'live.sqlite3',dbpath)
  files={p.relative_to(stage).as_posix():{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'mode':0o600} for p in stage.rglob('*') if p.is_file()}
  (stage/'manifest.json').write_text(json.dumps({'format':'mulino-system-v1','created_utc':'test','current':{'tag':'v1.3.0'},'previous':{'tag':'v1.2.1'},'image_asset':{},'files':files}))
  archive=self.root/'package.tar'
  with tarfile.open(archive,'w') as tar:
   for p in stage.rglob('*'):
    if p.is_file():tar.add(p,arcname=p.relative_to(stage).as_posix())
  return archive,stage
 def test_existing_payload_verifier_accepts_and_restores_monitor_snapshot(self):
  archive,_=self.package();destination=self.root/'restored';result=verify(archive,destination)
  self.assertEqual(result['files_verified'],1)
  restored=m.State(destination/'rootfs/opt/mulino-libero/data/email-monitor/monitor.sqlite3')
  try:self.assertEqual(restored.status()['delivery'],{'sent':1})
  finally:restored.db.close()
 def test_payload_checksum_rejects_tampered_monitor_state(self):
  archive,stage=self.package();dbpath=stage/'rootfs/opt/mulino-libero/data/email-monitor/monitor.sqlite3';dbpath.write_bytes(dbpath.read_bytes()+b'tamper')
  with tarfile.open(archive,'w') as tar:
   for p in stage.rglob('*'):
    if p.is_file():tar.add(p,arcname=p.relative_to(stage).as_posix())
  with self.assertRaises(ValueError):verify(archive,self.root/'restored')

if __name__=='__main__':unittest.main(verbosity=2)
