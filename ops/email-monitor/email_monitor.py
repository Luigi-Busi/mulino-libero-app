#!/usr/bin/env python3
"""Read-only document-request monitor. No email bodies or secrets in state/logs."""
from __future__ import annotations
import argparse
import collections
import contextlib
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from email import policy
from email.parser import BytesHeaderParser
from email.utils import getaddresses, parsedate_to_datetime
import fcntl
import hashlib
import imaplib
import json
import os
from pathlib import Path
import random
import re
import sqlite3
import ssl
import sys
import time
import unicodedata
from zoneinfo import ZoneInfo

VERSION = '1.2.0'
RULES = {
 'sisal': ('info@sisal.it', "inviaci la copia del tuo documento d'identità"),
 'pokerstars': ('info@clienti.pokerstars.it', "inviaci il tuo documento d'identità"),
 'snai': ('infoclienti@snai.it', "inviaci il tuo documento d'identità"),
}
LABELS = {'sisal':'Sisal', 'pokerstars':'PokerStars', 'snai':'Snai'}
EMAIL_RE = re.compile(r'^[a-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[a-z0-9.-]+\.[a-z]{2,}$', re.I)

def now(): return datetime.now(timezone.utc).isoformat()

def within_hours(config, instant=None):
 if 'operating_hours' not in config:return True
 hour=(instant or datetime.now(timezone.utc)).astimezone(ZoneInfo('Europe/Rome')).hour
 start,end=config['operating_hours']
 return start<=hour<end

def normalized(value):
 value = unicodedata.normalize('NFC', str(value)).casefold()
 return ' '.join(value.translate(str.maketrans({'’':"'",'‘':"'",'ʼ':"'",'`':"'"})).split())

def received_time(value):
 return datetime.strptime(value,'%d-%b-%Y %H:%M:%S %z').astimezone(timezone.utc)

def next_morning(stamp):
 local=datetime.fromisoformat(stamp).astimezone(ZoneInfo('Europe/Rome'))
 return (local+timedelta(days=1)).replace(hour=8,minute=0,second=0,microsecond=0).astimezone(timezone.utc).isoformat()

def is_reactivation(subject):
 text=re.sub(r"\be\s*'",'è',normalized(subject))
 return 'il tuo account è stato riattivato' in text

def error_code(exc):
 # Never serialize exception messages: libraries may embed token URLs/passwords.
 if isinstance(exc, imaplib.IMAP4.error): return 'IMAP_ERROR'
 if isinstance(exc, (TimeoutError, OSError)): return 'CONNECTION_ERROR'
 return type(exc).__name__ if re.fullmatch(r'[A-Za-z0-9_]+', type(exc).__name__) else 'ERROR'

def background(cell, theme=None):
 fmt = cell.get('effectiveFormat', {})
 style = fmt.get('backgroundColorStyle', {})
 rgb = style.get('rgbColor', fmt.get('backgroundColor'))
 if 'themeColor' in style:
  rgb = (theme or {}).get(style['themeColor'])
  if rgb is None: return 'unknown'
 if rgb is None: return '#ffffff'
 if not isinstance(rgb,dict): return 'unknown'
 try:
  return '#' + ''.join(f'{max(0,min(255,round(float(rgb.get(c,0))*255))):02x}' for c in ['red','green','blue'])
 except (TypeError,ValueError): return 'unknown'

def allowed_color(color, config):
 if color in config['allowed_colors']: return True
 # All neutral grey shades are allowed; colored greys are not guessed.
 return bool(re.fullmatch(r'#[0-9a-f]{6}',color) and color!='#000000' and color[1:3]==color[3:5]==color[5:7])

@dataclass(frozen=True)
class Account:
 operator: str
 email: str
 name: str
 book: str
 sheet: str
 gid: int
 row: int
 stable_id: str

 @property
 def url(self):
  return f'https://docs.google.com/spreadsheets/d/{self.book}/edit#gid={self.gid}&range=G{self.row}:H{self.row}'

class SheetsSource:
 def __init__(self, config):
  import gspread
  self.config=config
  self.client=gspread.service_account(filename=config['google_credentials'],scopes=['https://www.googleapis.com/auth/spreadsheets.readonly'])
  self.client.set_timeout(45)

 def load(self):
  accounts=[]; report={}; common=Path(self.config['password_file']).read_text().strip()
  if not common: raise ValueError('Empty password file')
  for source in self.config['sources']:
   book=self.client.open_by_key(source['book'])
   meta=book.fetch_sheet_metadata(params={'fields':'properties(spreadsheetTheme),sheets(properties)'})
   sheets=[s['properties'] for s in meta['sheets'] if s['properties']['title']==source['sheet']]
   if len(sheets)!=1 or sheets[0]['sheetId']!=source['gid']: raise ValueError('Configured sheet changed')
   prop=sheets[0]; count=prop['gridProperties']['rowCount'];cols=prop['gridProperties']['columnCount']
   if count>self.config.get('max_rows',10000) or cols<8: raise ValueError('Unexpected grid dimensions')
   raw=book.fetch_sheet_metadata(params={
    'ranges':f"'{source['sheet'].replace(chr(39),chr(39)*2)}'!A1:Z{count}",
    'fields':'sheets(properties(sheetId),data(startRow,rowData(values(formattedValue,effectiveFormat(backgroundColor,backgroundColorStyle)))))'})
   theme={p['colorType']:p['color'].get('rgbColor') for p in meta.get('properties',{}).get('spreadsheetTheme',{}).get('themeColors',[])}
   rows=[]
   for sheet in raw.get('sheets',[]):
    if sheet['properties']['sheetId']!=source['gid']:continue
    for data in sheet.get('data',[]):
     rows.extend((data.get('startRow',0)+i+1,r.get('values',[])) for i,r in enumerate(data.get('rowData',[])))
   header=None
   for rownum,cells in rows[:30]:
    vals=[normalized(c.get('formattedValue','')) for c in cells]
    emails=[i for i,v in enumerate(vals) if v in ['e-mail','email','mail']]
    passwords=[i for i,v in enumerate(vals) if v in ['password e-mail','pass e-mail','password email','pass email']]
    names=[i for i,v in enumerate(vals) if v in ['nome cognome','nome e cognome']]
    if len(emails)==len(passwords)==len(names)==1:
     if header is not None: raise ValueError('Ambiguous headers')
     header=(rownum,emails[0],passwords[0],names[0],vals.index('id_mulino') if 'id_mulino' in vals else None)
   if header is None: raise ValueError('Headers absent')
   hr,ec,pc,nc,ic=header
   if ec!=6 or pc!=7: raise ValueError('Email columns moved; verify configuration')
   stat=collections.Counter();colors=collections.Counter()
   for rownum,cells in rows:
    if rownum<=hr:continue
    cell=lambda i:cells[i] if i is not None and i<len(cells) else {}
    email=cell(ec).get('formattedValue','').strip().lower()
    if not email:continue
    stat['populated']+=1
    ce,cp=background(cell(ec),theme),background(cell(pc),theme);colors[ce+'/'+cp]+=1
    if ce!=cp: stat['color_discordance']+=1;continue
    if not (allowed_color(ce,self.config) and allowed_color(cp,self.config)):
     stat['excluded_color']+=1;continue
    if not EMAIL_RE.fullmatch(email) or email.rsplit('@',1)[-1] not in self.config['imap_domains']:
     stat['invalid_or_unsupported_email']+=1;continue
    password=cell(pc).get('formattedValue','').strip()
    if not password:stat['missing_password']+=1;continue
    if password!=common:stat['password_mismatch']+=1;continue
    name=cell(nc).get('formattedValue','').strip()
    if not name:stat['missing_name']+=1;continue
    accounts.append(Account(source['operator'],email,name,source['book'],source['sheet'],source['gid'],rownum,cell(ic).get('formattedValue','').strip()))
    stat['eligible']+=1
   report[source['sheet']]={**dict(stat),'colors':dict(colors)}
  return accounts, report

class State:
 def __init__(self, path):
  Path(path).parent.mkdir(parents=True,exist_ok=True)
  self.db=sqlite3.connect(path,timeout=30)
  self.db.row_factory=sqlite3.Row
  self.db.execute('PRAGMA journal_mode=WAL')
  self.db.execute('PRAGMA synchronous=FULL')
  self.db.executescript('''
   CREATE TABLE IF NOT EXISTS subscriptions(email TEXT,operator TEXT,active INTEGER NOT NULL,activation INTEGER NOT NULL,PRIMARY KEY(email,operator));
   CREATE TABLE IF NOT EXISTS cursors(email TEXT,operator TEXT,folder TEXT,activation INTEGER NOT NULL,validity INTEGER NOT NULL,uid INTEGER NOT NULL,updated TEXT NOT NULL,PRIMARY KEY(email,operator,folder));
   CREATE TABLE IF NOT EXISTS events(event_key TEXT PRIMARY KEY,email TEXT NOT NULL,operator TEXT NOT NULL,subject TEXT NOT NULL,received TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,next_try REAL NOT NULL DEFAULT 0,telegram_message_id INTEGER,error TEXT,created TEXT NOT NULL,updated TEXT NOT NULL);
   CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY,started TEXT NOT NULL,finished TEXT,summary TEXT);
   CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
   CREATE TABLE IF NOT EXISTS followups(request_key TEXT PRIMARY KEY,email TEXT NOT NULL,operator TEXT NOT NULL,request_received TEXT NOT NULL,not_before TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'waiting');
   CREATE TABLE IF NOT EXISTS followup_cursors(request_key TEXT,folder TEXT,validity INTEGER NOT NULL,uid INTEGER NOT NULL,PRIMARY KEY(request_key,folder));
   CREATE TABLE IF NOT EXISTS followup_events(event_key TEXT PRIMARY KEY,request_key TEXT NOT NULL,email TEXT NOT NULL,operator TEXT NOT NULL,subject TEXT NOT NULL,received TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,next_try REAL NOT NULL DEFAULT 0,telegram_message_id INTEGER,error TEXT,created TEXT NOT NULL,updated TEXT NOT NULL);
  ''')
  with self.db:
   self.db.execute("UPDATE events SET status='uncertain',error='PROCESS_INTERRUPTED',updated=? WHERE status='sending'",(now(),))
   self.db.execute("UPDATE followup_events SET status='uncertain',error='PROCESS_INTERRUPTED',updated=? WHERE status='sending'",(now(),))
  os.chmod(path,0o600)

 def sync(self,accounts):
  desired={(a.email,a.operator) for a in accounts}; old={(r['email'],r['operator']):r for r in self.db.execute('SELECT * FROM subscriptions')}
  with self.db:
   for key in set(old)|desired:
    active=int(key in desired);before=old.get(key); generation=(before['activation'] if before else 0)
    if active and (not before or not before['active']):generation+=1
    self.db.execute('INSERT OR REPLACE INTO subscriptions VALUES(?,?,?,?)',(*key,active,generation))
    if not active:
     self.db.execute("UPDATE followups SET status='cancelled' WHERE email=? AND operator=? AND status IN ('waiting','queued')",key)
     self.db.execute("UPDATE followup_events SET status='cancelled',updated=? WHERE email=? AND operator=? AND status='pending'",(now(),*key))

 def generation(self,email,operator):
  return self.db.execute('SELECT activation FROM subscriptions WHERE email=? AND operator=? AND active=1',(email,operator)).fetchone()[0]

 def cursor(self,email,operator,folder):
  return self.db.execute('SELECT * FROM cursors WHERE email=? AND operator=? AND folder=?',(email,operator,folder)).fetchone()

 def advance(self,email,operator,folder,generation,validity,uid):
  self.db.execute('INSERT OR REPLACE INTO cursors VALUES(?,?,?,?,?,?,?)',(email,operator,folder,generation,validity,uid,now()))

 def enqueue(self,email,operator,raw,received):
  message=BytesHeaderParser(policy=policy.default).parsebytes(raw)
  subject=str(message.get('Subject',''))
  addresses=getaddresses([str(h) for h in message.get_all('From',[])])
  if len(addresses)!=1:return False
  sender,phrase=RULES[operator]
  if addresses[0][1].strip().casefold()!=sender or normalized(phrase) not in normalized(subject):return False
  mid=str(message.get('Message-ID','')).strip()
  fingerprint=mid if mid else hashlib.sha256(raw+received.encode()).hexdigest()
  key=hashlib.sha256((email+'\n'+operator+'\n'+fingerprint).encode()).hexdigest()
  stamp=now()
  # Payload excludes bodies, credentials and account passwords.
  cur=self.db.execute('INSERT OR IGNORE INTO events(event_key,email,operator,subject,received,created,updated) VALUES(?,?,?,?,?,?,?)',(key,email,operator,subject[:1000],received,stamp,stamp))
  return cur.rowcount==1

 def status(self):
  return {'subscriptions':self.db.execute('SELECT COUNT(*) FROM subscriptions WHERE active=1').fetchone()[0],
   'initialized_folders':self.db.execute('SELECT COUNT(*) FROM cursors').fetchone()[0],
   'delivery':dict(self.db.execute('SELECT status,COUNT(*) FROM events GROUP BY status').fetchall()),
   'reactivation_waits':dict(self.db.execute('SELECT status,COUNT(*) FROM followups GROUP BY status').fetchall()),
   'reactivation_delivery':dict(self.db.execute('SELECT status,COUNT(*) FROM followup_events GROUP BY status').fetchall()),
   'last_run':dict(self.db.execute('SELECT * FROM runs ORDER BY id DESC LIMIT 1').fetchone() or {}),
   'integrity':self.db.execute('PRAGMA quick_check').fetchone()[0]}

 def start_followup(self,event,stamp):
  # Repeated document requests during the same open wait keep its first boundary.
  if self.db.execute("SELECT 1 FROM followups WHERE email=? AND operator=? AND status IN ('waiting','queued')",(event['email'],event['operator'])).fetchone():return
  self.db.execute('INSERT OR IGNORE INTO followups(request_key,email,operator,request_received,not_before) VALUES(?,?,?,?,?)',
   (event['event_key'],event['email'],event['operator'],received_time(event['received']).isoformat(),next_morning(stamp)))

 def due_followups(self,email,operators):
  return [r for r in self.db.execute("SELECT f.* FROM followups f JOIN subscriptions s ON f.email=s.email AND f.operator=s.operator WHERE f.email=? AND f.status='waiting' AND s.active=1 AND f.not_before<=? ORDER BY f.not_before",(email,now())) if r['operator'] in operators]

 def enqueue_followup(self,watch,raw,received):
  message=BytesHeaderParser(policy=policy.default).parsebytes(raw)
  addresses=getaddresses([str(h) for h in message.get_all('From',[])])
  if len(addresses)!=1 or addresses[0][1].strip().casefold()!=RULES[watch['operator']][0]:return False
  subject=str(message.get('Subject',''))
  if not is_reactivation(subject) or received_time(received)<datetime.fromisoformat(watch['request_received']):return False
  mid=str(message.get('Message-ID','')).strip()
  fingerprint=mid if mid else hashlib.sha256(raw+received.encode()).hexdigest()
  key=hashlib.sha256((watch['email']+'\n'+watch['operator']+'\n'+fingerprint).encode()).hexdigest()
  stamp=now()
  cur=self.db.execute('INSERT OR IGNORE INTO followup_events(event_key,request_key,email,operator,subject,received,created,updated) VALUES(?,?,?,?,?,?,?,?)',
   (key,watch['request_key'],watch['email'],watch['operator'],subject[:1000],received,stamp,stamp))
  if cur.rowcount:
   self.db.execute("UPDATE followups SET status='queued' WHERE request_key=?",(watch['request_key'],))
   return True
  return False

def parse_folders(lines):
 result=[]
 for line in lines:
  if not isinstance(line,bytes):continue
  match=re.fullmatch(rb'\(([^)]*)\) (?:"(?:[^"\\]|\\.)*"|NIL) (.+)',line)
  if not match:raise ValueError('Unsupported IMAP LIST response')
  flags=match[1].lower().split(); name=match[2]
  if name.startswith(b'"') and name.endswith(b'"'):name=re.sub(rb'\\(.)',rb'\1',name[1:-1])
  if b'\\noselect' in flags:continue
  decoded=name.decode('ascii')
  if decoded.upper()=='INBOX' or b'\\junk' in flags or decoded.casefold() in ['spam','junk','posta indesiderata']:
   result.append(decoded)
 if not any(x.upper()=='INBOX' for x in result): raise ValueError('INBOX absent')
 return sorted(set(result),key=lambda x:(x.upper()!='INBOX',x))

class Scanner:
 def __init__(self, config, state, factory=None):
  self.config=config;self.state=state
  self.factory=factory or (lambda:imaplib.IMAP4_SSL(config['imap_host'],993,ssl_context=ssl.create_default_context(),timeout=30))

 def scan(self,email,operators,password):
  stats=collections.Counter();errors=[]
  with self.factory() as conn:
   conn.login(email,password)
   typ,lines=conn.list()
   if typ!='OK':raise RuntimeError('LIST failed')
   folders=parse_folders(lines)
   for folder in folders:
    try:self.scan_folder(conn,email,operators,folder,stats)
    except Exception as exc:errors.append({'folder':folder,'code':error_code(exc)})
   for watch in self.state.due_followups(email,operators):
    for folder in folders:
     if self.state.db.execute('SELECT status FROM followups WHERE request_key=?',(watch['request_key'],)).fetchone()[0]!='waiting':break
     try:self.scan_followup(conn,watch,folder,stats)
     except Exception as exc:errors.append({'folder':folder,'code':error_code(exc),'phase':'reactivation'})
  if errors:return dict(stats),errors
  return dict(stats),[]

 def scan_folder(self,conn,email,operators,folder,stats):
  mailbox='"'+folder.replace('\\','\\\\').replace('"','\\"')+'"'
  typ,_=conn.select(mailbox,readonly=True)
  if typ!='OK':raise RuntimeError('SELECT failed')
  def response_int(name):
   _,data=conn.response(name)
   if not data or not isinstance(data[0],bytes) or not data[0].isdigit():raise ValueError('Missing IMAP UID metadata')
   return int(data[0])
  validity=response_int('UIDVALIDITY');upper=response_int('UIDNEXT')-1
  if validity<=0 or upper<0:raise ValueError('Invalid UID metadata')
  tracked={}
  with self.state.db:
   for operator in operators:
    generation=self.state.generation(email,operator);cursor=self.state.cursor(email,operator,folder)
    if cursor is None or cursor['validity']!=validity or cursor['activation']!=generation:
     self.state.advance(email,operator,folder,generation,validity,upper);stats['baselines']+=1
     if cursor is not None and cursor['validity']!=validity:stats['uidvalidity_resets']+=1
    else: tracked[operator]=(generation,cursor['uid'])
  if not tracked:return
  low=min(uid for _,uid in tracked.values())+1
  if low>upper:stats['folders_unchanged']+=1;return
  typ,data=conn.uid('SEARCH',None,'UID',f'{low}:{upper}')
  if typ!='OK' or not data or not isinstance(data[0],bytes):raise RuntimeError('SEARCH failed')
  all_uids=sorted(set(int(x) for x in data[0].split() if x.isdigit()))
  uids=[u for u in all_uids if low<=u<=upper]
  cap=self.config.get('max_messages_per_folder',500)
  batch=uids[:cap];target=batch[-1] if len(uids)>cap else upper
  for uid in batch:
   typ,data=conn.uid('FETCH',str(uid),'(UID INTERNALDATE BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])')
   if typ!='OK':raise RuntimeError('FETCH failed')
   literals=[item for item in data if isinstance(item,tuple) and isinstance(item[1],bytes)]
   if not literals:stats['expunged_during_scan']+=1;continue
   if len(literals)!=1:raise ValueError('Unexpected FETCH response')
   metadata,raw=literals[0]
   actual=re.search(rb'\bUID (\d+)\b',metadata)
   if not actual or int(actual[1])!=uid:raise ValueError('UID mismatch')
   match=re.search(rb'INTERNALDATE "([^"\r\n]+)"',metadata)
   if not match:raise ValueError('INTERNALDATE absent')
   received=match[1].decode('ascii')
   with self.state.db:
    for operator,(generation,cursor_uid) in tracked.items():
     if uid>cursor_uid:
      if self.state.enqueue(email,operator,raw,received):stats['candidates']+=1
      self.state.advance(email,operator,folder,generation,validity,uid)
   stats['headers']+=1
  with self.state.db:
   for operator,(generation,old_uid) in tracked.items():
    self.state.advance(email,operator,folder,generation,validity,max(old_uid,target))
  if len(uids)>cap:stats['backlog_folders']+=1
  stats['folders_checked']+=1

 def scan_followup(self,conn,watch,folder,stats):
  mailbox='"'+folder.replace('\\','\\\\').replace('"','\\"')+'"'
  typ,_=conn.select(mailbox,readonly=True)
  if typ!='OK':raise RuntimeError('SELECT failed')
  def integer(name):
   _,data=conn.response(name)
   if not data or not isinstance(data[0],bytes) or not data[0].isdigit():raise ValueError('Missing UID metadata')
   return int(data[0])
  validity=integer('UIDVALIDITY');upper=integer('UIDNEXT')-1
  if validity<=0 or upper<0:raise ValueError('Invalid UID metadata')
  cursor=self.state.db.execute('SELECT * FROM followup_cursors WHERE request_key=? AND folder=?',(watch['request_key'],folder)).fetchone()
  low=cursor['uid']+1 if cursor and cursor['validity']==validity else 1
  if low>upper:return
  # SINCE is day based. A one-day margin handles server INTERNALDATE offsets;
  # the exact timestamp below rejects everything before the document request.
  start=datetime.fromisoformat(watch['request_received'])-timedelta(days=1)
  months=('Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec')
  since=f'{start.day:02d}-{months[start.month-1]}-{start.year}'
  typ,data=conn.uid('SEARCH',None,'SINCE',since,'UID',f'{low}:{upper}')
  if typ!='OK' or not data or not isinstance(data[0],bytes):raise RuntimeError('SEARCH failed')
  uids=sorted({int(x) for x in data[0].split() if x.isdigit() and low<=int(x)<=upper})
  cap=self.config.get('max_messages_per_folder',500);batch=uids[:cap]
  for uid in batch:
   typ,data=conn.uid('FETCH',str(uid),'(UID INTERNALDATE BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])')
   if typ!='OK':raise RuntimeError('FETCH failed')
   literals=[item for item in data if isinstance(item,tuple) and isinstance(item[1],bytes)]
   if not literals:continue
   if len(literals)!=1:raise ValueError('Unexpected FETCH response')
   metadata,raw=literals[0];actual=re.search(rb'\bUID (\d+)\b',metadata);date=re.search(rb'INTERNALDATE "([^"\r\n]+)"',metadata)
   if not actual or int(actual[1])!=uid or not date:raise ValueError('Invalid FETCH metadata')
   with self.state.db:
    found=self.state.enqueue_followup(watch,raw,date[1].decode('ascii'))
    self.state.db.execute('INSERT OR REPLACE INTO followup_cursors VALUES(?,?,?,?)',(watch['request_key'],folder,validity,uid))
   stats['reactivation_headers']+=1
   if found:stats['reactivation_candidates']+=1;return
  target=batch[-1] if len(uids)>cap else upper
  with self.state.db:self.state.db.execute('INSERT OR REPLACE INTO followup_cursors VALUES(?,?,?,?)',(watch['request_key'],folder,validity,target))
  if len(uids)>cap:stats['reactivation_backlog_folders']+=1

def display_date(received):
 try:
  dt=datetime.strptime(received,'%d-%b-%Y %H:%M:%S %z')
  return dt.astimezone(ZoneInfo('Europe/Rome')).strftime('%d/%m/%Y, %H:%M')
 except ValueError:return received

def notification(event,accounts,reactivation=False):
 title='✅ Account riattivato' if reactivation else '🚨 Richiesta documento'
 text=f"{title} — {LABELS[event['operator']]}\n"
 text+=f"Account: {accounts[0].name[:160]}\nEmail: {event['email']}\nOggetto: {event['subject'][:500]}\nRicevuta: {display_date(event['received'])}\n"
 text+='\n'.join(f'Apri {a.sheet}: {a.url}' for a in accounts[:4])
 return text[:3800]

class Telegram:
 def __init__(self,config):
  import requests
  self.session=requests.Session();self.token=Path(config['telegram_token_file']).read_text().strip();self.chat=config['telegram_chat_id'];self.dashboard_button=bool(config.get('dashboard_status'))
 def send(self,text):
  # No requests logging / raise_for_status: URLs contain the secret token.
  try:
   payload={'chat_id':self.chat,'text':text,'link_preview_options':{'is_disabled':True}}
   if getattr(self,'dashboard_button',False):payload['reply_markup']={'inline_keyboard':[[{'text':'📊 Stato account','callback_data':'bn:root'}]]}
   response=self.session.post(f'https://api.telegram.org/bot{self.token}/sendMessage',json=payload,timeout=(10,30))
  except Exception:return ('uncertain',None,0,'NETWORK_UNCERTAIN')
  try:body=response.json()
  except ValueError:return ('uncertain',None,0,'RESPONSE_UNCERTAIN')
  if response.status_code==200 and body.get('ok') and isinstance(body.get('result',{}).get('message_id'),int):return ('sent',body['result']['message_id'],0,None)
  if response.status_code==429 and body.get('error_code')==429:return ('pending',None,int(body.get('parameters',{}).get('retry_after',60))+5,'RATE_LIMIT')
  if response.status_code in [400,401,403]:return ('failed',None,0,'TELEGRAM_REJECTED')
  return ('uncertain',None,0,'RESPONSE_UNCERTAIN')

def deliver(state,accounts,sender,reactivation=False):
 table='followup_events' if reactivation else 'events'
 index=collections.defaultdict(list)
 for account in accounts:index[(account.email,account.operator)].append(account)
 stats=collections.Counter()
 for event in state.db.execute(f"SELECT * FROM {table} WHERE status='pending' AND next_try<=? ORDER BY created LIMIT 100",(time.time(),)).fetchall():
  if reactivation:
   watch=state.db.execute('SELECT * FROM followups WHERE request_key=?',(event['request_key'],)).fetchone()
   if watch['not_before']>now():continue
  targets=index.get((event['email'],event['operator']))
  if not targets:
   with state.db:
    state.db.execute(f"UPDATE {table} SET status='cancelled',updated=? WHERE event_key=?",(now(),event['event_key']))
    if reactivation:state.db.execute("UPDATE followups SET status='cancelled' WHERE request_key=?",(event['request_key'],))
   stats['cancelled']+=1;continue
  # Claim before the network call. A process crash leaves an explicit uncertain
  # delivery, rather than silently repeating a Telegram notification.
  with state.db:state.db.execute(f"UPDATE {table} SET status='sending',attempts=attempts+1,updated=? WHERE event_key=?",(now(),event['event_key']))
  result,mid,delay,error=sender.send(notification(event,targets,reactivation))
  stamp=now()
  with state.db:
   state.db.execute(f'UPDATE {table} SET status=?,telegram_message_id=?,next_try=?,error=?,updated=? WHERE event_key=?',(result,mid,time.time()+delay,error,stamp,event['event_key']))
   if result=='sent':
    if reactivation:state.db.execute("UPDATE followups SET status='sent' WHERE request_key=?",(event['request_key'],))
    else:state.start_followup(event,stamp)
  stats[result]+=1
  if result=='pending':break
 return dict(stats)

def atomic_json(path,value):
 path=Path(path);temp=path.with_suffix('.tmp')
 with temp.open('w',encoding='utf-8') as f:
  json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
 os.chmod(temp,0o600);os.replace(temp,path)

MIRROR_HEADERS=['email','operatore','stato','ultima_variazione','monitorato','ultimo_controllo','consegna','id_evento']

def mirror_rows(state,stamp):
 rows=[MIRROR_HEADERS,['__meta__','1','','','',stamp,'','']]
 for sub in state.db.execute('SELECT * FROM subscriptions ORDER BY operator,email'):
  candidates=[]
  for table,kind in [('events','documents'),('followup_events','reactivated')]:
   for event in state.db.execute(f"SELECT * FROM {table} WHERE email=? AND operator=? AND status!='cancelled'",(sub['email'],sub['operator'])):
    try:received=received_time(event['received'])
    except ValueError:continue
    candidates.append((received,kind,event['status'],event['event_key']))
  latest=max(candidates,key=lambda x:(x[0],x[1]=='reactivated'),default=None)
  rows.append([sub['email'],sub['operator'],latest[1] if latest else 'active',latest[0].isoformat() if latest else '',str(sub['active']),stamp,latest[2] if latest else '',latest[3] if latest else ''])
 return rows

def publish_dashboard(config,state,client=None):
 target=config.get('dashboard_status')
 if not target:return
 checked=state.db.execute('SELECT finished FROM runs WHERE finished IS NOT NULL ORDER BY id DESC LIMIT 1').fetchone()
 rows=mirror_rows(state,checked[0] if checked else '')
 if target.get('webhook_file'):
  import requests
  bridge=json.loads(Path(target['webhook_file']).read_text())
  # Use the Banco's existing authenticated web app; no extra Google grants.
  response=requests.post(bridge['url'],json={'banco_status_sync':rows},timeout=(10,45))
  answer=response.json()
  digest=hashlib.sha256(json.dumps(rows,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
  if response.status_code!=200 or answer.get('ok') is not True or answer.get('digest')!=digest:raise RuntimeError('Dashboard sync not confirmed')
  return
 if client is None:
  import gspread
  client=gspread.service_account(filename=config['google_credentials'],scopes=['https://www.googleapis.com/auth/spreadsheets'])
  client.set_timeout(45)
 book=client.open_by_key(target['book'])
 # A unique named tab is created once; every other tab is left intact.
 matches=[sheet for sheet in book.worksheets() if sheet.title==target['sheet']]
 if len(matches)>1:raise ValueError('Ambiguous dashboard tab')
 sheet=matches[0] if matches else book.add_worksheet(title=target['sheet'],rows=1000,cols=8)
 previous=sheet.get_all_values()
 if previous and previous[0]!=MIRROR_HEADERS:raise ValueError('Dashboard tab contains other data')
 if len(rows)>sheet.row_count:sheet.resize(rows=len(rows)+100)
 # One atomic range update includes empty old rows, avoiding transient empty state.
 count=max(len(rows),len(previous));payload=rows+[['']*8 for _ in range(count-len(rows))]
 sheet.update(range_name=f'A1:H{count}',values=payload,value_input_option='RAW')

def run_cycle(config,state,source=None,scanner=None,sender=None,sleep=time.sleep):
 if not within_hours(config):return {'status':'outside_operating_hours','errors':[],'started':now(),'finished':now()}
 started=now();rid=state.db.execute('INSERT INTO runs(started) VALUES(?)',(started,)).lastrowid;state.db.commit()
 summary={'version':VERSION,'started':started,'status':'running','errors':[]}
 source=source or SheetsSource(config)
 try:
  accounts,sheets=source.load();state.sync(accounts);summary['sheets']=sheets
  groups=collections.defaultdict(set)
  for a in accounts:groups[a.email].add(a.operator)
  summary['eligible_rows']=len(accounts);summary['unique_mailboxes']=len(groups)
  password=Path(config['password_file']).read_text().strip();scanner=scanner or Scanner(config,state)
  aggregate=collections.Counter();failed=[];successful=set()
  items=list(groups.items());random.shuffle(items)
  for number,(email,operators) in enumerate(items):
   try:
    stats,errors=scanner.scan(email,operators,password);aggregate.update(stats)
    if errors:failed.append((email,operators));summary['errors'].extend({'mailbox_hash':hashlib.sha256(email.encode()).hexdigest()[:12],**e} for e in errors)
    else:successful.add(email)
   except Exception as exc:
    failed.append((email,operators));summary['errors'].append({'mailbox_hash':hashlib.sha256(email.encode()).hexdigest()[:12],'code':error_code(exc)})
   if number+1<len(items):sleep(random.uniform(config.get('delay_min',2),config.get('delay_max',4)))
   if (number+1)%20==0 and number+1<len(items):sleep(30)
  if failed and config.get('retry_seconds',120):
   sleep(config['retry_seconds']);retry_errors=[]
   for number,(email,operators) in enumerate(failed):
    try:
     stats,errors=scanner.scan(email,operators,password);aggregate.update(stats)
     if errors:retry_errors.extend({'mailbox_hash':hashlib.sha256(email.encode()).hexdigest()[:12],**e} for e in errors)
     else:successful.add(email)
    except Exception as exc:retry_errors.append({'mailbox_hash':hashlib.sha256(email.encode()).hexdigest()[:12],'code':error_code(exc)})
    if number+1<len(failed):sleep(random.uniform(2,4))
   summary['first_attempt_errors']=len(summary['errors']);summary['errors']=retry_errors
  summary['checked_mailboxes']=len(successful);summary['scan']=dict(aggregate)
  # Re-read current account eligibility before delivering queued alerts.
  if state.db.execute("SELECT 1 FROM events WHERE status='pending' UNION ALL SELECT 1 FROM followup_events WHERE status='pending' LIMIT 1").fetchone():
   latest,_=source.load();state.sync(latest)
   summary['delivery']=deliver(state,latest,sender or Telegram(config))
   summary['reactivation_delivery']=deliver(state,latest,sender or Telegram(config),True)
  with state.db:
   for table in ['events','followup_events']:state.db.execute(f"UPDATE {table} SET status='uncertain',error='PROCESS_INTERRUPTED',updated=? WHERE status='sending'",(now(),))
  pending_problem=sum(state.db.execute(f"SELECT COUNT(*) FROM {table} WHERE status IN ('uncertain','failed')").fetchone()[0] for table in ['events','followup_events'])
  summary['reactivation_waits']=dict(state.db.execute('SELECT status,COUNT(*) FROM followups GROUP BY status').fetchall())
  issues=sum(sum(v.get(key,0) for key in ['color_discordance','invalid_or_unsupported_email','missing_password','password_mismatch','missing_name']) for v in sheets.values())
  summary['configuration_issues']=issues;summary['delivery_issues']=pending_problem
  summary['status']='degraded' if summary['errors'] or issues or pending_problem else 'ok'
 except Exception as exc:
  summary['status']='failed';summary['errors'].append({'code':error_code(exc)})
 summary['finished']=now()
 with state.db:state.db.execute('UPDATE runs SET finished=?,summary=? WHERE id=?',(summary['finished'],json.dumps(summary),rid))
 try:publish_dashboard(config,state)
 except Exception as exc:
  summary['errors'].append({'code':error_code(exc),'phase':'dashboard_sync'})
  if summary['status']=='ok':summary['status']='degraded'
  with state.db:state.db.execute('UPDATE runs SET summary=? WHERE id=?',(json.dumps(summary),rid))
 atomic_json(config['status_file'],summary)
 # Keep compact aggregate history; event ledger and cursors are retained.
 with state.db:state.db.execute('DELETE FROM runs WHERE id < ?',(max(0,rid-720),))
 return summary

def health_text(summary):
 lines=['⚠️ Monitor mail documenti: controllo incompleto',f"Caselle controllate: {summary.get('checked_mailboxes',0)}/{summary.get('unique_mailboxes',0)}",f"Errori di accesso/servizio: {len(summary['errors'])}",f"Problemi di configurazione: {summary.get('configuration_issues',0)}",f"Invii da verificare: {summary.get('delivery_issues',0)}"]
 if summary.get('errors'):lines.append('Codici: '+', '.join(sorted({e['code'] for e in summary['errors']})))
 lines.append('Il monitor riproverà al prossimo ciclo. Le credenziali non sono incluse nel messaggio.')
 return '\n'.join(lines)

def notify_health(config,state,summary,sender=None):
 meaningful={'status':summary['status'],'errors':sorted(summary['errors'],key=lambda e:json.dumps(e,sort_keys=True)),'issues':summary.get('configuration_issues',0),'delivery_issues':summary.get('delivery_issues',0)}
 fingerprint=hashlib.sha256(json.dumps(meaningful,sort_keys=True).encode()).hexdigest()
 row=state.db.execute("SELECT value FROM settings WHERE key='health'").fetchone();previous=json.loads(row[0]) if row else {}
 if fingerprint==previous.get('fingerprint'):return
 if summary['status']=='ok' and previous.get('status') not in ['degraded','failed']:
  with state.db:state.db.execute("INSERT OR REPLACE INTO settings VALUES('health',?)",(json.dumps({'fingerprint':fingerprint,'status':'ok'}),))
  return
 text=health_text(summary) if summary['status']!='ok' else '✅ Monitor mail documenti: controlli tornati regolari.'
 result,_,_,_= (sender or Telegram(config)).send(text)
 if result=='sent':
  with state.db:state.db.execute("INSERT OR REPLACE INTO settings VALUES('health',?)",(json.dumps({'fingerprint':fingerprint,'status':summary['status']}),))

def main():
 os.umask(0o077)
 parser=argparse.ArgumentParser();parser.add_argument('--config',default='/config/config.json');parser.add_argument('command',choices=['once','inventory','status','test-telegram'])
 args=parser.parse_args();config=json.loads(Path(args.config).read_text())
 if args.command=='once' and not within_hours(config):
  print(json.dumps({'status':'outside_operating_hours','timezone':'Europe/Rome','operating_hours':config['operating_hours']}));return 0
 if args.command=='test-telegram':
  result,mid,_,_=Telegram(config).send('✅ Prova monitor mail documenti riuscita. Questo messaggio verifica soltanto Telegram; nessuna vecchia email è stata notificata.')
  print(json.dumps({'result':result,'message_id':mid}));return 0 if result=='sent' else 1
 if args.command=='inventory':
  accounts,report=SheetsSource(config).load();print(json.dumps({'sheets':report,'unique_mailboxes':len({a.email for a in accounts}),'eligible_rows':len(accounts)},ensure_ascii=False));return 0
 if args.command=='status':
  state=object.__new__(State)
  state.db=sqlite3.connect('file:'+str(Path(config['db_file']).resolve())+'?mode=ro',uri=True,timeout=30)
  state.db.row_factory=sqlite3.Row
  try:print(json.dumps(state.status(),ensure_ascii=False,indent=2))
  finally:state.db.close()
  return 0
 with Path(config['db_file']).with_suffix('.lock').open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError: print('Another cycle is active');return 0
  state=State(config['db_file'])
  result=run_cycle(config,state);notify_health(config,state,result)
  print(json.dumps(result,ensure_ascii=False));return 0 if result['status']!='failed' else 1

if __name__=='__main__':
 try:sys.exit(main())
 except Exception as exc:
  print(json.dumps({'status':'failed','code':error_code(exc)}));sys.exit(1)
