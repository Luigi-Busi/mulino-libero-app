import json,tempfile,unittest
from pathlib import Path
from release_tool import Releases,FILES,sha

class ReleaseTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.calls=[];self.fail=False
  def runner(args):
   self.calls.append([str(x) for x in args])
   if args[:2]==['systemctl','show']:return b'active\n'
   if args[0]=='systemd-analyze' and self.fail:self.fail=False;raise RuntimeError('simulated validation failure')
   return b''
  self.manager=Releases(self.root,runner)
  self.old=self.release(1);self.new=self.release(2)
  self.manager.install_files(self.old[1]);self.manager.register(*self.old)
  self.data=self.root/'opt/mulino-libero/data/email-monitor/monitor.sqlite3';self.data.parent.mkdir(parents=True);self.data.write_bytes(b'preserved state')
  self.config=self.root/'etc/mulino-email-monitor/config.json';self.config.write_text('private config preserved')
 def tearDown(self):self.temp.cleanup()
 def release(self,n):
  payload={name:('release '+str(n)+' '+name).encode() for name in FILES}
  return {'tag':f'email-monitor-v1.0.{n-1}','commit':str(n)*40,'version':f'1.0.{n-1}','data_schema':1,'files':{k:sha(v) for k,v in payload.items()}},payload
 def assert_preserved(self):
  self.assertEqual(self.data.read_bytes(),b'preserved state');self.assertEqual(self.config.read_text(),'private config preserved')
  self.assertFalse(any('libero-mail-bot' in ' '.join(c) or 'bot-risponditore' in ' '.join(c) for c in self.calls))
 def test_register_and_verify_exact_files(self):self.manager.verify(self.old[0]);self.assertFalse(self.calls);self.assert_preserved()
 def test_update_and_rollback_preserve_data_config_and_mugnaio(self):
  self.assertEqual(self.manager.activate(*self.new),'activated');self.manager.verify(self.new[0]);self.assert_preserved()
  self.manager.rollback();self.manager.verify(self.old[0]);self.assert_preserved()
 def test_failed_update_restores_previous_files_and_timer(self):
  self.fail=True
  with self.assertRaises(RuntimeError):self.manager.activate(*self.new)
  self.manager.verify(self.old[0]);self.assertFalse(self.manager.pending.exists());self.assert_preserved()
 def test_modified_live_source_blocks_update(self):
  (self.root/FILES['email_monitor.py'][1]).write_bytes(b'modified')
  with self.assertRaises(ValueError):self.manager.activate(*self.new)
  self.assertFalse(self.calls);self.assert_preserved()
 def test_schema_change_requires_separate_migration(self):
  self.new[0]['data_schema']=2
  with self.assertRaises(ValueError):self.manager.activate(*self.new)
  self.manager.verify(self.old[0]);self.assert_preserved()
 def test_pending_recovery_restores_previous_release(self):
  self.manager.archive(*self.new);self.manager.pending.write_text(json.dumps({'before':self.manager.state(),'target':self.new[0],'timer_active':True}))
  self.manager.install_files(self.new[1]);self.manager.recover();self.manager.verify(self.old[0]);self.assert_preserved()

if __name__=='__main__':unittest.main(verbosity=2)
