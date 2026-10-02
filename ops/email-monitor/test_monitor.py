import unittest,tempfile,json,sqlite3
from pathlib import Path
from unittest.mock import Mock
import email_monitor as m

CONFIG={'allowed_colors':['#ffffff','#ff00ff','#9900ff'],'max_messages_per_folder':500,'imap_domains':['libero.it'],'max_rows':10000}
ACCOUNT=m.Account('sisal','test@libero.it','Persona Test','book','Sisal Sport',10,12,'stable')
def raw(sender='info@sisal.it',subject="Inviaci la copia del tuo documento d'identità",mid='<one@test>'):
 from email.message import EmailMessage
 msg=EmailMessage();msg['From']=sender;msg['Subject']=subject
 if mid:msg['Message-ID']=mid
 return msg.as_bytes()

class FakeIMAP:
 def __init__(self,uidnext=6,validity=1,messages=None,folders=None,fail_uid=None):
  self.uidnext=uidnext;self.validity=validity;self.messages=messages or {};self.calls=[];self.fail_uid=fail_uid
  self.folders=folders or [b'(\\HasNoChildren) "/" INBOX',b'(\\Junk) "/" Spam']
 def __enter__(self):return self
 def __exit__(self,*args):pass
 def login(self,email,password):self.calls.append(('LOGIN',email))
 def list(self):return 'OK',self.folders
 def select(self,folder,readonly=False):self.calls.append(('SELECT',folder,readonly));return 'OK',[]
 def response(self,name):return name,[str(self.validity if name=='UIDVALIDITY' else self.uidnext).encode()]
 def uid(self,command,*args):
  self.calls.append((command,*args))
  if command=='SEARCH':
   low,high=map(int,args[-1].split(':'));return 'OK',[' '.join(str(u) for u in self.messages if low<=u<=high).encode()]
  uid=int(args[0])
  if uid==self.fail_uid:return 'NO',[]
  return 'OK',[(f'1 (UID {uid} INTERNALDATE "02-Oct-2026 12:30:00 +0000" BODY[HEADER.FIELDS] {{100}}'.encode(),self.messages[uid]),b')']

class StateTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.state=m.State(Path(self.temp.name)/'state.sqlite3');self.state.sync([ACCOUNT])
 def tearDown(self):self.state.db.close();self.temp.cleanup()
 def scan(self,imap,operators=None):
  return m.Scanner(CONFIG,self.state,lambda:imap).scan(ACCOUNT.email,operators or {'sisal'},'test-password')
 def baseline(self,uid=5):
  with self.state.db:self.state.advance(ACCOUNT.email,'sisal','INBOX',1,1,uid)
 def event(self,operator='sisal',message=None):
  with self.state.db:return self.state.enqueue(ACCOUNT.email,operator,message or raw(),'02-Oct-2026 12:30:00 +0000')
 def test_baseline_reads_no_historical_headers(self):
  conn=FakeIMAP(messages={1:raw(),5:raw()});stats,errors=self.scan(conn)
  self.assertEqual(stats['baselines'],2);self.assertFalse(errors)
  self.assertFalse(any(c[0] in ['FETCH','SEARCH'] for c in conn.calls));self.assertEqual(self.state.status()['delivery'],{})
 def test_select_readonly_every_folder(self):
  conn=FakeIMAP();self.scan(conn);self.assertTrue(all(c[2] for c in conn.calls if c[0]=='SELECT'))
 def test_new_mail_enqueued_once_even_across_folders(self):
  self.scan(FakeIMAP(uidnext=6));stats,_=self.scan(FakeIMAP(uidnext=7,messages={6:raw()}))
  self.assertEqual(stats['candidates'],1);self.assertEqual(self.state.status()['delivery'],{'pending':1})
 def test_body_peek_only(self):
  self.baseline();conn=FakeIMAP(uidnext=7,messages={6:raw()},folders=[b'() "/" INBOX']);self.scan(conn)
  self.assertIn('BODY.PEEK[HEADER.FIELDS',next(c for c in conn.calls if c[0]=='FETCH')[-1])
 def test_no_search_when_uidnext_unchanged(self):
  self.scan(FakeIMAP());conn=FakeIMAP();self.scan(conn);self.assertFalse(any(c[0]=='SEARCH' for c in conn.calls))
 def test_uidvalidity_change_baselines_without_backfill(self):
  self.scan(FakeIMAP());conn=FakeIMAP(uidnext=100,validity=2,messages={90:raw()});stats,_=self.scan(conn)
  self.assertEqual(stats['uidvalidity_resets'],2);self.assertEqual(self.state.status()['delivery'],{})
 def test_reactivation_baselines_without_backfill(self):
  self.scan(FakeIMAP());self.state.sync([]);self.state.sync([ACCOUNT]);conn=FakeIMAP(uidnext=20,messages={19:raw()});self.scan(conn)
  self.assertEqual(self.state.cursor(ACCOUNT.email,'sisal','INBOX')['uid'],19);self.assertEqual(self.state.status()['delivery'],{})
 def test_failed_fetch_does_not_skip_mail(self):
  self.baseline();conn=FakeIMAP(uidnext=8,messages={6:raw(mid='<six>'),7:raw(mid='<seven>')},fail_uid=7,folders=[b'() "/" INBOX'])
  _,errors=self.scan(conn);self.assertTrue(errors);self.assertEqual(self.state.cursor(ACCOUNT.email,'sisal','INBOX')['uid'],6)
  conn.fail_uid=None;stats,errors=self.scan(conn);self.assertFalse(errors);self.assertEqual(stats['candidates'],1);self.assertEqual(self.state.status()['delivery'],{'pending':2})
 def test_new_operator_does_not_receive_old_mail(self):
  self.scan(FakeIMAP());ps=m.Account('pokerstars',ACCOUNT.email,'Test','book','PokerStars',11,10,'id2');self.state.sync([ACCOUNT,ps])
  conn=FakeIMAP(uidnext=10,messages={8:raw(sender='info@clienti.pokerstars.it',subject="Inviaci il tuo documento d'identità")});self.scan(conn,{'sisal','pokerstars'})
  self.assertEqual(self.state.status()['delivery'],{})
 def test_restart_preserves_baseline(self):
  self.scan(FakeIMAP());path=Path(self.temp.name)/'state.sqlite3';self.state.db.close();self.state=m.State(path)
  conn=FakeIMAP(uidnext=7,messages={6:raw()});stats,_=self.scan(conn);self.assertEqual(stats['candidates'],1)
 def test_per_folder_limit_continues_next_cycle(self):
  self.baseline();cfg={**CONFIG,'max_messages_per_folder':1};conn=FakeIMAP(uidnext=8,messages={6:raw(mid='<six>'),7:raw(mid='<seven>')},folders=[b'() "/" INBOX'])
  scanner=m.Scanner(cfg,self.state,lambda:conn);stats,_=scanner.scan(ACCOUNT.email,{'sisal'},'pw')
  self.assertEqual(stats['backlog_folders'],1);self.assertEqual(self.state.cursor(ACCOUNT.email,'sisal','INBOX')['uid'],6)
  scanner.scan(ACCOUNT.email,{'sisal'},'pw');self.assertEqual(self.state.status()['delivery'],{'pending':2})
 def test_exact_sender(self):
  for sender in ['info@sisal.it.evil.example','evil@info.sisal.it','info@clienti.pokerstars.it','info@sisal.it, attacker@example.it']:
   self.assertFalse(self.event(message=raw(sender=sender)))
 def test_display_name_sender_allowed(self):self.assertTrue(self.event(message=raw(sender='Sisal <info@sisal.it>')))
 def test_sisal_distinct_subject(self):self.assertFalse(self.event(message=raw(subject="Inviaci il tuo documento d'identità")))
 def test_curly_apostrophe_and_spaces_and_case(self):self.assertTrue(self.event(message=raw(subject='URGENTE: INVIACI   LA COPIA DEL TUO DOCUMENTO D’IDENTITÀ')))
 def test_pokerstars_rule(self):self.assertTrue(self.event('pokerstars',raw(sender='info@clienti.pokerstars.it',subject="Inviaci il tuo documento d'identità")))
 def test_snai_rule(self):self.assertTrue(self.event('snai',raw(sender='infoclienti@snai.it',subject="Inviaci il tuo documento d'identità")))
 def test_dedup_same_message_id(self):self.assertTrue(self.event());self.assertFalse(self.event())
 def test_new_distinct_message_id(self):self.assertTrue(self.event());self.assertTrue(self.event(message=raw(mid='<two>')))
 def test_missing_message_id_fallback(self):self.assertTrue(self.event(message=raw(mid=None)));self.assertFalse(self.event(message=raw(mid=None)))
 def test_send_success_and_no_repeat(self):
  self.event();sender=Mock();sender.send.return_value=('sent',42,0,None)
  self.assertEqual(m.deliver(self.state,[ACCOUNT],sender),{'sent':1});m.deliver(self.state,[ACCOUNT],sender);sender.send.assert_called_once()
 def test_removed_red_account_cancels_pending(self):
  self.event();sender=Mock();m.deliver(self.state,[],sender);sender.send.assert_not_called();self.assertEqual(self.state.status()['delivery'],{'cancelled':1})
 def test_rate_limit_keeps_pending(self):
  self.event();sender=Mock();sender.send.return_value=('pending',None,100,'RATE_LIMIT');m.deliver(self.state,[ACCOUNT],sender);m.deliver(self.state,[ACCOUNT],sender);sender.send.assert_called_once();self.assertEqual(self.state.status()['delivery'],{'pending':1})
 def test_uncertain_delivery_not_repeated(self):
  self.event();sender=Mock();sender.send.return_value=('uncertain',None,0,'NETWORK_UNCERTAIN');m.deliver(self.state,[ACCOUNT],sender);m.deliver(self.state,[ACCOUNT],sender);sender.send.assert_called_once()
 def test_send_crash_claim_not_pending(self):
  self.event();sender=Mock();sender.send.side_effect=RuntimeError('simulated crash')
  with self.assertRaises(RuntimeError):m.deliver(self.state,[ACCOUNT],sender)
  self.assertEqual(self.state.status()['delivery'],{'sending':1})
 def test_message_date_italian_timezone(self):self.assertEqual(m.display_date('02-Oct-2026 12:30:00 +0000'),'02/10/2026, 14:30')
 def test_message_has_link_without_password(self):
  self.event();event=self.state.db.execute('SELECT * FROM events').fetchone();text=m.notification(event,[ACCOUNT]);self.assertIn('range=G12:H12',text);self.assertNotIn('test-password',text)
 def test_disabled_folder_not_scanned(self):
  conn=FakeIMAP(folders=[b'() "/" INBOX',b'(\\Sent) "/" outbox',b'(\\Trash) "/" trash',b'(\\Junk) "/" Spam']);self.scan(conn)
  self.assertEqual([c[1] for c in conn.calls if c[0]=='SELECT'],['"INBOX"','"Spam"'])
 def test_failed_sheets_load_never_sends(self):
  self.event();sender=Mock();source=Mock();source.load.side_effect=ValueError('secret-value')
  cfg={**CONFIG,'status_file':str(Path(self.temp.name)/'status.json'),'password_file':str(Path(self.temp.name)/'pw')}
  result=m.run_cycle(cfg,self.state,source=source,sender=sender);sender.send.assert_not_called();self.assertEqual(result['status'],'failed');self.assertNotIn('secret-value',json.dumps(result))
 def test_expunged_fetch_is_safe(self):
  self.baseline();conn=FakeIMAP(uidnext=7,messages={6:raw()},folders=[b'() "/" INBOX']);conn.uid=lambda command,*args:('OK',[b'6']) if command=='SEARCH' else ('OK',[None])
  stats,errors=self.scan(conn);self.assertFalse(errors);self.assertEqual(stats['expunged_during_scan'],1)
 def test_health_unchanged_silent(self):
  sender=Mock();sender.send.return_value=('sent',1,0,None);summary={'status':'degraded','errors':[{'code':'IMAP_ERROR','mailbox_hash':'test'}]}
  m.notify_health(CONFIG,self.state,summary,sender);m.notify_health(CONFIG,self.state,summary,sender);sender.send.assert_called_once()
 def test_healthy_start_silent(self):
  sender=Mock();m.notify_health(CONFIG,self.state,{'status':'ok','errors':[]},sender);sender.send.assert_not_called()
 def test_interrupted_send_recovered_without_resending(self):
  self.event()
  with self.state.db:self.state.db.execute("UPDATE events SET status='sending'")
  self.state.db.close();self.state=m.State(Path(self.temp.name)/'state.sqlite3')
  sender=Mock();m.deliver(self.state,[ACCOUNT],sender);sender.send.assert_not_called();self.assertEqual(self.state.status()['delivery'],{'uncertain':1})

class ColorAndFoldersTest(unittest.TestCase):
 def test_white_missing_effective_format(self):self.assertEqual(m.background({}),'#ffffff')
 def test_pure_red(self):self.assertFalse(m.allowed_color(m.background({'effectiveFormat':{'backgroundColor':{'red':1}}}),CONFIG))
 def test_dark_red(self):self.assertFalse(m.allowed_color('#980000',CONFIG))
 def test_fuchsia(self):self.assertTrue(m.allowed_color('#ff00ff',CONFIG))
 def test_grey_shades(self):
  for color in ['#434343','#999999','#cccccc','#ffffff']:self.assertTrue(m.allowed_color(color,CONFIG))
  self.assertFalse(m.allowed_color('#000000',CONFIG))
 def test_cyan_requires_explicit_config(self):self.assertFalse(m.allowed_color('#00ffff',CONFIG));self.assertTrue(m.allowed_color('#00ffff',{**CONFIG,'allowed_colors':CONFIG['allowed_colors']+['#00ffff']}))
 def test_unknown_theme_excluded(self):self.assertFalse(m.allowed_color(m.background({'effectiveFormat':{'backgroundColorStyle':{'themeColor':'ACCENT1'}}}),CONFIG))
 def test_theme_resolution(self):self.assertEqual(m.background({'effectiveFormat':{'backgroundColorStyle':{'themeColor':'ACCENT1'}}},{'ACCENT1':{'red':1,'blue':1}}),'#ff00ff')
 def test_inbox_required(self):
  with self.assertRaises(ValueError):m.parse_folders([b'(\\Junk) "/" Spam'])
 def test_quoted_folder(self):self.assertEqual(m.parse_folders([b'() "/" "INBOX"',b'(\\Junk) "/" "Posta indesiderata"']),['INBOX','Posta indesiderata'])
 def test_error_messages_never_exposed(self):self.assertEqual(m.error_code(ValueError('SECRET_TOKEN')),'ValueError')

class OperatingHoursTest(unittest.TestCase):
 def allowed(self,time):return m.within_hours({'operating_hours':[8,22]},m.datetime.fromisoformat(time))
 def test_before_eight_skipped(self):self.assertFalse(self.allowed('2026-10-02T07:59:00+02:00'))
 def test_eight_included(self):self.assertTrue(self.allowed('2026-10-02T08:00:00+02:00'))
 def test_before_twenty_two_included(self):self.assertTrue(self.allowed('2026-10-02T21:59:00+02:00'))
 def test_twenty_two_skipped(self):self.assertFalse(self.allowed('2026-10-02T22:00:00+02:00'))
 def test_utc_converted_to_italian_time(self):self.assertTrue(self.allowed('2026-10-02T06:00:00+00:00'))
 def test_winter_utc_converted_to_italian_time(self):self.assertTrue(self.allowed('2026-11-02T07:00:00+00:00'))

class SheetsSelectionTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.pw=Path(self.temp.name)/'password';self.pw.write_text('shared-test-password')
  self.source=object.__new__(m.SheetsSource);self.source.config={**CONFIG,'password_file':str(self.pw),'sources':[{'book':'book','sheet':'Sisal Sport','gid':10,'operator':'sisal'}]}
  self.source.client=Mock();self.book=Mock();self.source.client.open_by_key.return_value=self.book
 def tearDown(self):self.temp.cleanup()
 def load(self,email_color=None,password_color=None,password='shared-test-password',gid=10):
  headers=['Data Apertura','Chiusura','Diffida','Nome Cognome','Username','Password','E-mail','Password E-mail','ID_MULINO']
  header={'values':[{'formattedValue':v} for v in headers]}
  vals=['','','','Persona Test','testuser','game-password','test@libero.it',password,'stable-id'];cells=[{'formattedValue':v} for v in vals]
  if email_color is not None:cells[6]['effectiveFormat']={'backgroundColor':email_color}
  if password_color is not None:cells[7]['effectiveFormat']={'backgroundColor':password_color}
  self.book.fetch_sheet_metadata.side_effect=[{'sheets':[{'properties':{'title':'Sisal Sport','sheetId':gid,'gridProperties':{'rowCount':1000,'columnCount':26}}}]},{'sheets':[{'properties':{'sheetId':10},'data':[{'startRow':7,'rowData':[header,{'values':cells}]}]}]}]
  return self.source.load()
 def test_white_allowed_with_exact_password_and_columns(self):
  accounts,report=self.load();self.assertEqual(len(accounts),1);self.assertEqual(accounts[0].row,9);self.assertEqual(accounts[0].stable_id,'stable-id')
 def test_red_in_both_cells_excluded(self):
  accounts,report=self.load({'red':1},{'red':1});self.assertEqual(accounts,[]);self.assertEqual(report['Sisal Sport']['excluded_color'],1)
 def test_color_disagreement_excluded_and_reported(self):
  accounts,report=self.load({'red':1,'blue':1},{'red':1,'green':1,'blue':1});self.assertFalse(accounts);self.assertEqual(report['Sisal Sport']['color_discordance'],1)
 def test_password_mismatch_excluded_without_leak(self):
  accounts,report=self.load(password='secret-incorrect');self.assertFalse(accounts);self.assertEqual(report['Sisal Sport']['password_mismatch'],1);self.assertNotIn('secret-incorrect',json.dumps(report))
 def test_missing_password_reported(self):
  accounts,report=self.load(password='');self.assertFalse(accounts);self.assertEqual(report['Sisal Sport']['missing_password'],1)
 def test_changed_sheet_id_fails_closed(self):
  with self.assertRaises(ValueError):self.load(gid=99)

if __name__=='__main__':unittest.main(verbosity=2)
