#!/usr/bin/python3
"""Run only the monitor using the pinned, existing Mulino runtime image."""
import json,subprocess,sys
from pathlib import Path
allowed={'once','inventory','status','test-telegram','cleanup'}
if len(sys.argv)!=2 or sys.argv[1] not in allowed:raise SystemExit('Use once, inventory, status or test-telegram')
if sys.argv[1]=='cleanup':
 subprocess.run(['docker','stop','--time','10','mulino-email-monitor-once'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 raise SystemExit(0)
image=json.loads(Path('/etc/mulino-email-monitor/runtime.json').read_text())['image']
args=['docker','run','--rm','--name','mulino-email-monitor-'+sys.argv[1],
 '--read-only','--cap-drop=ALL','--security-opt=no-new-privileges','--init',
 '--memory=256m','--cpus=0.25','--pids-limit=80','--user=0:0','--tmpfs','/tmp:rw,noexec,nosuid,size=16m',
 '--entrypoint','python','-e','PYTHONUNBUFFERED=1','-e','PYTHONDONTWRITEBYTECODE=1',
 '--mount','type=bind,src=/usr/local/lib/mulino-email-monitor,dst=/monitor,readonly',
 '--mount','type=bind,src=/etc/mulino-email-monitor,dst=/config,readonly',
 '--mount','type=bind,src=/opt/mulino-libero/secrets/google-service-account.json,dst=/credentials.json,readonly',
 '--mount','type=bind,src=/opt/mulino-libero/secrets/telegram-bot-token,dst=/telegram-token,readonly',
 '--mount','type=bind,src=/opt/mulino-libero/secrets/libero-password,dst=/libero-password,readonly',
 '--mount','type=bind,src=/opt/mulino-libero/data/email-monitor,dst=/state',
 image,'/monitor/email_monitor.py',sys.argv[1]]
raise SystemExit(subprocess.call(args))
