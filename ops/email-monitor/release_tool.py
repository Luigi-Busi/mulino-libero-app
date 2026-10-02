#!/usr/bin/env python3
"""Independent monitor release management. Never deploys/restarts the Mugnaio."""
import argparse,ast,fcntl,hashlib,json,os,re,shutil,subprocess,tempfile,uuid
from pathlib import Path
TAG=re.compile(r'email-monitor-v\d+\.\d+\.\d+\Z')
FILES={
 'test_monitor.py':('ops/email-monitor/test_monitor.py','usr/local/lib/mulino-email-monitor/test_monitor.py',0o600),
 'test_recovery.py':('ops/email-monitor/test_recovery.py','usr/local/lib/mulino-email-monitor/test_recovery.py',0o600),
 'test_releases.py':('ops/email-monitor/test_releases.py','usr/local/lib/mulino-email-monitor/test_releases.py',0o600),
 'email_monitor.py':('ops/email-monitor/email_monitor.py','usr/local/lib/mulino-email-monitor/email_monitor.py',0o600),
 'launcher.py':('ops/email-monitor/launcher.py','usr/local/sbin/mulino-email-monitor',0o700),
 'release_tool.py':('ops/email-monitor/release_tool.py','usr/local/lib/mulino-email-monitor/release_tool.py',0o700),
 'mulino-email-monitor.service':('ops/email-monitor/mulino-email-monitor.service','etc/systemd/system/mulino-email-monitor.service',0o644),
 'mulino-email-monitor.timer':('ops/email-monitor/mulino-email-monitor.timer','etc/systemd/system/mulino-email-monitor.timer',0o644),
 'backup_system.py':('ops/recovery/backup_system.py','usr/local/lib/mulino-recovery/backup_system.py',0o700),
 'restore_system.py':('ops/recovery/restore_system.py','usr/local/lib/mulino-recovery/restore_system.py',0o700),
}
def sha(raw):return hashlib.sha256(raw).hexdigest()
def command(args):
 result=subprocess.run([str(v) for v in args],capture_output=True)
 if result.returncode:raise RuntimeError('Operation failed: '+str(args[0]))
 return result.stdout
def atomic(path,raw,mode=0o600):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 if path.is_symlink():raise ValueError('Symlink target')
 tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.new')
 with tmp.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
 tmp.chmod(mode);os.replace(tmp,path)
def json_write(path,value):atomic(path,(json.dumps(value,indent=2)+'\n').encode())

class Releases:
 def __init__(self,root=Path('/'),runner=command):
  self.root=Path(root).resolve();self.runner=runner
  self.config=self.root/'etc/mulino-email-monitor';self.record=self.config/'release.json'
  self.pending=self.config/'release-pending.json';self.archives=self.root/'usr/local/lib/mulino-email-monitor/releases'
 def run(self,*args):return self.runner(list(args))
 def state(self):return json.loads(self.record.read_text()) if self.record.exists() else {'current':None,'previous':None}
 def verify(self,record):
  if not record or not TAG.fullmatch(record['tag']) or record.get('data_schema')!=1:raise ValueError('Invalid release identity')
  if set(record['files'])!=set(FILES):raise ValueError('Incomplete managed file list')
  for name,(_,rel,_) in FILES.items():
   path=self.root/rel
   if path.is_symlink() or not path.is_file() or sha(path.read_bytes())!=record['files'][name]:raise ValueError('Installed source differs: '+name)
 def archive(self,record,payload):
  directory=self.archives/record['commit']
  directory.mkdir(parents=True,exist_ok=True,mode=0o700)
  for name,raw in payload.items():
   target=directory/name
   if target.exists():
    if sha(target.read_bytes())!=sha(raw):raise ValueError('Archive differs')
   else:atomic(target,raw)
  meta=directory/'release.json'
  if not meta.exists():json_write(meta,record)
 def archived(self,record):
  payload={name:(self.archives/record['commit']/name).read_bytes() for name in FILES}
  if any(sha(payload[name])!=record['files'][name] for name in FILES):raise ValueError('Rollback archive differs')
  return payload
 def timer_active(self):
  return self.run('systemctl','show','mulino-email-monitor.timer','-p','ActiveState','--value').strip()==b'active'
 def install_files(self,payload):
  for name,(_,rel,mode) in FILES.items():atomic(self.root/rel,payload[name],mode)
 def restore_timer(self,enabled):
  self.run('systemctl','daemon-reload')
  if enabled:self.run('systemctl','start','mulino-email-monitor.timer')
 def register(self,record,payload):
  if self.pending.exists() or self.record.exists():raise ValueError('Registration already exists or deploy pending')
  self.verify(record);self.archive(record,payload);json_write(self.record,{'current':record,'previous':None})
 def activate(self,record,payload):
  if self.pending.exists():raise ValueError('Recover pending transaction first')
  old=self.state();self.verify(old['current'])
  if old['current']['commit']==record['commit']:return 'already_current'
  if record.get('data_schema')!=old['current']['data_schema']:raise ValueError('Data schema change requires separate migration')
  self.archive(record,payload);self.archived(old['current'])
  enabled=self.timer_active()
  json_write(self.pending,{'before':old,'target':record,'timer_active':enabled})
  try:
   self.run('systemctl','stop','mulino-email-monitor.timer')
   self.run('systemctl','stop','mulino-email-monitor.service')
   self.install_files(payload)
   self.run('systemd-analyze','verify',self.root/'etc/systemd/system/mulino-email-monitor.service',self.root/'etc/systemd/system/mulino-email-monitor.timer')
   self.verify(record)
   json_write(self.record,{'current':record,'previous':old['current']})
   self.restore_timer(enabled);self.pending.unlink()
   return 'activated'
  except BaseException:
   self.recover();raise
 def recover(self):
  transaction=json.loads(self.pending.read_text())
  self.run('systemctl','stop','mulino-email-monitor.timer')
  self.run('systemctl','stop','mulino-email-monitor.service')
  before=transaction['before'];self.install_files(self.archived(before['current']))
  self.verify(before['current']);json_write(self.record,before)
  self.restore_timer(transaction['timer_active']);self.pending.unlink()
 def rollback(self):
  state=self.state()
  if not state['previous']:raise ValueError('No previous monitor release; disable its timer to revert the first installation')
  return self.activate(state['previous'],self.archived(state['previous']))

def from_git(tag):
 if not TAG.fullmatch(tag):raise ValueError('Expected email-monitor-vX.Y.Z')
 repo=Path('/opt/mulino-libero/app')
 command(['git','-C',repo,'fetch','origin',f'refs/tags/{tag}:refs/tags/{tag}'])
 commit=command(['git','-C',repo,'rev-parse',tag+'^{commit}']).decode().strip()
 def blob(path):return command(['git','-C',repo,'show',commit+':'+path])
 spec=json.loads(blob('ops/email-monitor/release-spec.json'))
 if spec!={'version':tag.removeprefix('email-monitor-v'),'data_schema':1}:raise ValueError('Release specification mismatch')
 payload={name:blob(source) for name,(source,_,_) in FILES.items()}
 for name,raw in payload.items():
  if name.endswith('.py'):ast.parse(raw)
 version=[node.value.value for node in ast.parse(payload['email_monitor.py']).body if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='VERSION' for t in node.targets)]
 if version!=[spec['version']]:raise ValueError('Monitor version differs from tag')
 record={'tag':tag,'commit':commit,'data_schema':1,'version':spec['version'],'files':{name:sha(raw) for name,raw in payload.items()},'managed_files':{('/'+target):{'git_path':source,'sha256':sha(payload[name])} for name,(source,target,_) in FILES.items()}}
 with tempfile.TemporaryDirectory(prefix='email-release-check-') as temp:
  stage=Path(temp)
  for name,raw in payload.items():(stage/name).write_bytes(raw)
  for name,path in {'test_monitor.py':'ops/email-monitor/test_monitor.py','test_recovery.py':'ops/email-monitor/test_recovery.py','test_releases.py':'ops/email-monitor/test_releases.py','verify_payload.py':'ops/recovery/verify_payload.py'}.items():(stage/name).write_bytes(blob(path))
  runtime=json.loads(Path('/etc/mulino-email-monitor/runtime.json').read_text())['image']
  runner="import unittest; s=unittest.defaultTestLoader.discover('/suite'); assert s.countTestCases()>=60; r=unittest.TextTestRunner().run(s); raise SystemExit(0 if r.wasSuccessful() else 1)"
  command(['docker','run','--rm','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges','--memory=256m','--cpus=0.5','--tmpfs','/tmp:rw,nosuid,size=32m','--entrypoint','python','-e','PYTHONDONTWRITEBYTECODE=1','--mount',f'type=bind,src={stage},dst=/suite,readonly','--workdir','/suite',runtime,'-c',runner])
 return record,payload

def main():
 parser=argparse.ArgumentParser();parser.add_argument('action',choices=['check','register','verify','deploy','rollback','recover']);parser.add_argument('tag',nargs='?');args=parser.parse_args()
 manager=Releases()
 with (manager.config/'release.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  # Lock order follows system backup: backup then main deploy. This serializes
  # managed recovery scripts with backups and Mugnaio deployment operations.
  with Path('/var/lib/mulino-recovery/lock').open('a') as backup_lock,Path('/var/lib/mulino-deploy/lock').open('a') as app_lock:
   fcntl.flock(backup_lock,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(app_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
   if args.action in ['check','register','deploy']:
    record,payload=from_git(args.tag or '')
    if args.action=='register':manager.register(record,payload)
    elif args.action=='deploy':manager.activate(record,payload)
    print(json.dumps({'checked':record['tag'],'commit':record['commit'],'action':args.action}));return
   if args.action=='recover':manager.recover()
   elif args.action=='rollback':manager.rollback()
   manager.verify(manager.state()['current']);print(json.dumps(manager.state(),indent=2))
if __name__=='__main__':
 try:main()
 except Exception as exc:
  print(json.dumps({'status':'failed','code':type(exc).__name__}));raise SystemExit(1)
