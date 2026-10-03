import unittest,tempfile,json,sqlite3
from pathlib import Path
from unittest.mock import Mock,patch
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

class FollowupTest(unittest.TestCase):
 setUp=StateTest.setUp
 tearDown=StateTest.tearDown
 scan=StateTest.scan
 event=StateTest.event
 def sender(self,result='sent'):
  sender=Mock();sender.send.return_value=(result,77,100 if result=='pending' else 0,None);return sender
 def watch(self):
  self.event()
  with patch.object(m,'now',return_value='2026-10-02T19:00:00+00:00'):
   m.deliver(self.state,[ACCOUNT],self.sender())
  return self.state.db.execute('SELECT * FROM followups').fetchone()
 def recovery(self,sender='info@sisal.it',subject="Il tuo account e' stato riattivato",mid='<reactivated>'):
  return raw(sender=sender,subject=subject,mid=mid)
 def enqueue(self,watch=None,received='02-Oct-2026 20:30:00 +0000',message=None):
  with self.state.db:return self.state.enqueue_followup(watch or self.watch(),message or self.recovery(),received)
 def test_wait_starts_only_after_confirmed_document_notification(self):
  self.event();m.deliver(self.state,[ACCOUNT],self.sender('uncertain'))
  self.assertEqual(self.state.db.execute('SELECT COUNT(*) FROM followups').fetchone()[0],0)
 def test_rate_limited_document_has_no_wait_yet(self):
  self.event();m.deliver(self.state,[ACCOUNT],self.sender('pending'))
  self.assertEqual(self.state.db.execute('SELECT COUNT(*) FROM followups').fetchone()[0],0)
 def test_start_is_next_morning_italian_time(self):
  self.assertEqual(self.watch()['not_before'],'2026-10-03T06:00:00+00:00')
 def test_daylight_saving_start(self):
  self.assertEqual(m.next_morning('2026-03-28T20:00:00+00:00'),'2026-03-29T06:00:00+00:00')
 def test_daylight_saving_end(self):
  self.assertEqual(m.next_morning('2026-10-24T19:00:00+00:00'),'2026-10-25T07:00:00+00:00')
 def test_notification_day_controls_start_even_if_request_older(self):
  self.event()
  with patch.object(m,'now',return_value='2026-10-05T07:00:00+00:00'):m.deliver(self.state,[ACCOUNT],self.sender())
  self.assertEqual(self.state.db.execute('SELECT not_before FROM followups').fetchone()[0],'2026-10-06T06:00:00+00:00')
 def test_no_extra_search_before_next_morning(self):
  self.watch();conn=FakeIMAP(messages={5:self.recovery()})
  with patch.object(m,'now',return_value='2026-10-03T05:59:59+00:00'):self.scan(conn)
  self.assertFalse(any(c[0]=='SEARCH' for c in conn.calls))
 def test_night_mail_found_at_eight_even_normal_cursor_already_passed(self):
  self.watch();conn=FakeIMAP(messages={5:self.recovery()})
  with patch.object(m,'now',return_value='2026-10-03T06:00:00+00:00'):
   stats,errors=self.scan(conn);sender=self.sender();m.deliver(self.state,[ACCOUNT],sender,True)
  self.assertFalse(errors);self.assertEqual(stats['reactivation_candidates'],1)
  self.assertIn('Account riattivato',sender.send.call_args[0][0])
  self.assertEqual(self.state.status()['reactivation_waits'],{'sent':1})
  self.assertTrue(all(c[2] for c in conn.calls if c[0]=='SELECT'))
  self.assertTrue(all('BODY.PEEK' in c[-1] for c in conn.calls if c[0]=='FETCH'))
 def test_old_reactivation_rejected(self):
  watch=self.watch();self.assertFalse(self.enqueue(watch,'02-Oct-2026 12:29:59 +0000'))
 def test_wrong_sender_rejected(self):
  watch=self.watch()
  for sender in ['info@clienti.pokerstars.it','info@sisal.it.evil.example','info@sisal.it, evil@example.it']:
   self.assertFalse(self.enqueue(watch,message=self.recovery(sender=sender)))
 def test_subject_variants(self):
  for subject in ["Il tuo account e' stato riattivato",'IL TUO ACCOUNT È STATO RIATTIVATO','Il tuo account e’ stato riattivato','Il tuo   account è stato riattivato']:
   self.assertTrue(m.is_reactivation(subject))
  self.assertFalse(m.is_reactivation('Il tuo account è stato sospeso'))
 def test_pokerstars_uses_own_sender(self):
  ps=m.Account('pokerstars',ACCOUNT.email,'Test','book','PokerStars',11,10,'id2');self.state.sync([ps])
  self.event('pokerstars',raw(sender='info@clienti.pokerstars.it',subject="Inviaci il tuo documento d'identità"))
  with patch.object(m,'now',return_value='2026-10-02T19:00:00+00:00'):m.deliver(self.state,[ps],self.sender())
  watch=self.state.db.execute('SELECT * FROM followups').fetchone()
  self.assertFalse(self.enqueue(watch))
  self.assertTrue(self.enqueue(watch,message=self.recovery(sender='info@clienti.pokerstars.it')))
 def test_pending_reactivation_never_delivered_early(self):
  self.enqueue();sender=self.sender()
  with patch.object(m,'now',return_value='2026-10-03T05:59:00+00:00'):m.deliver(self.state,[ACCOUNT],sender,True)
  sender.send.assert_not_called()
 def test_reactivation_dedup_across_folders_and_restart(self):
  watch=self.watch();self.assertTrue(self.enqueue(watch));self.assertFalse(self.enqueue(watch))
  self.state.db.close();self.state=m.State(Path(self.temp.name)/'state.sqlite3')
  with patch.object(m,'now',return_value='2026-10-03T06:00:00+00:00'):
   sender=self.sender();m.deliver(self.state,[ACCOUNT],sender,True);m.deliver(self.state,[ACCOUNT],sender,True)
  sender.send.assert_called_once()
 def test_reactivation_without_document_never_queued(self):
  self.scan(FakeIMAP());conn=FakeIMAP(uidnext=7,messages={6:self.recovery()});self.scan(conn)
  self.assertEqual(self.state.status()['reactivation_delivery'],{})
 def test_failed_followup_fetch_retried_without_skip(self):
  self.watch();conn=FakeIMAP(messages={5:self.recovery()},fail_uid=5,folders=[b'() "/" INBOX'])
  with patch.object(m,'now',return_value='2026-10-03T06:00:00+00:00'):
   _,errors=self.scan(conn);self.assertTrue(errors);conn.fail_uid=None
   stats,errors=self.scan(conn);self.assertFalse(errors);self.assertEqual(stats['reactivation_candidates'],1)
 def test_cancel_wait_if_account_excluded(self):
  self.watch();self.state.sync([])
  self.assertEqual(self.state.status()['reactivation_waits'],{'cancelled':1})
  self.state.sync([ACCOUNT]);self.assertEqual(self.state.due_followups(ACCOUNT.email,{'sisal'}),[])
 def test_eligibility_rechecked_before_followup_delivery(self):
  self.enqueue();sender=self.sender()
  with patch.object(m,'now',return_value='2026-10-03T06:00:00+00:00'):m.deliver(self.state,[],sender,True)
  sender.send.assert_not_called();self.assertEqual(self.state.status()['reactivation_delivery'],{'cancelled':1})
 def test_uncertain_followup_does_not_repeat(self):
  self.enqueue();sender=self.sender('uncertain')
  with patch.object(m,'now',return_value='2026-10-03T06:00:00+00:00'):
   m.deliver(self.state,[ACCOUNT],sender,True);m.deliver(self.state,[ACCOUNT],sender,True)
  sender.send.assert_called_once();self.assertEqual(self.state.status()['reactivation_waits'],{'queued':1})
 def test_interrupted_followup_delivery_recovers_as_uncertain(self):
  self.enqueue()
  with self.state.db:self.state.db.execute("UPDATE followup_events SET status='sending'")
  self.state.db.close();self.state=m.State(Path(self.temp.name)/'state.sqlite3')
  self.assertEqual(self.state.status()['reactivation_delivery'],{'uncertain':1})
 def test_repeated_document_keeps_original_open_wait(self):
  watch=self.watch();self.event(message=raw(mid='<second-doc>'))
  with patch.object(m,'now',return_value='2026-10-04T12:00:00+00:00'):m.deliver(self.state,[ACCOUNT],self.sender())
  self.assertEqual(self.state.db.execute('SELECT COUNT(*) FROM followups').fetchone()[0],1)
  self.assertEqual(self.state.db.execute('SELECT not_before FROM followups').fetchone()[0],watch['not_before'])
 def test_new_document_after_completion_opens_new_wait(self):
  self.enqueue()
  with patch.object(m,'now',return_value='2026-10-03T06:00:00+00:00'):m.deliver(self.state,[ACCOUNT],self.sender(),True)
  self.event(message=raw(mid='<second-doc>'))
  with patch.object(m,'now',return_value='2026-10-04T12:00:00+00:00'):m.deliver(self.state,[ACCOUNT],self.sender())
  self.assertEqual(self.state.status()['reactivation_waits'],{'sent':1,'waiting':1})
 def test_snapshot_preserves_wait_and_followup_outbox(self):
  from backup_system import snapshot
  self.enqueue();snapshot(Path(self.temp.name)/'state.sqlite3',Path(self.temp.name)/'copy.sqlite3')
  restored=m.State(Path(self.temp.name)/'copy.sqlite3')
  try:
   self.assertEqual(restored.status()['reactivation_waits'],{'queued':1})
   self.assertEqual(restored.status()['reactivation_delivery'],{'pending':1})
  finally:restored.db.close()
 def test_old_schema_preserved_and_old_notifications_not_backfilled(self):
  path=Path(self.temp.name)/'old.sqlite3';db=sqlite3.connect(path)
  db.execute("CREATE TABLE events(event_key TEXT PRIMARY KEY,email TEXT NOT NULL,operator TEXT NOT NULL,subject TEXT NOT NULL,received TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,next_try REAL NOT NULL DEFAULT 0,telegram_message_id INTEGER,error TEXT,created TEXT NOT NULL,updated TEXT NOT NULL)")
  db.execute("INSERT INTO events(event_key,email,operator,subject,received,status,created,updated) VALUES('old','test@libero.it','sisal','doc','date','sent','now','now')");db.commit();db.close()
  upgraded=m.State(path)
  try:
   self.assertEqual(upgraded.status()['delivery'],{'sent':1})
   self.assertEqual(upgraded.status()['reactivation_waits'],{})
  finally:upgraded.db.close()
 def test_followup_incremental_cursor_avoids_rescan(self):
  self.watch();conn=FakeIMAP(messages={5:raw(subject='Altra mail')})
  with patch.object(m,'now',return_value='2026-10-03T06:00:00+00:00'):
   self.scan(conn);conn.calls.clear();self.scan(conn)
  self.assertFalse(any(c[0] in ['FETCH','SEARCH'] for c in conn.calls))
 def test_followup_uidvalidity_change_recovers_only_since_request(self):
  self.watch();conn=FakeIMAP(messages={5:raw(subject='Altra mail')})
  with patch.object(m,'now',return_value='2026-10-03T06:00:00+00:00'):
   self.scan(conn);conn.validity=2;conn.messages={5:self.recovery()};stats,errors=self.scan(conn)
  self.assertFalse(errors);self.assertEqual(stats['reactivation_candidates'],1)
 def test_followup_batch_limit_keeps_pending_search_progress(self):
  self.watch();conn=FakeIMAP(uidnext=8,messages={5:raw(subject='Other'),6:raw(subject='Other'),7:self.recovery()},folders=[b'() "/" INBOX'])
  scanner=m.Scanner({**CONFIG,'max_messages_per_folder':1},self.state,lambda:conn)
  with patch.object(m,'now',return_value='2026-10-03T06:00:00+00:00'):
   first,_=scanner.scan(ACCOUNT.email,{'sisal'},'pw');self.assertEqual(first['reactivation_backlog_folders'],1)
   scanner.scan(ACCOUNT.email,{'sisal'},'pw');last,errors=scanner.scan(ACCOUNT.email,{'sisal'},'pw')
  self.assertFalse(errors);self.assertEqual(last['reactivation_candidates'],1)
 def test_full_cycle_rechecks_sheets_and_delivers_reactivation(self):
  self.watch();pw=Path(self.temp.name)/'pw';pw.write_text('test-password')
  cfg={**CONFIG,'password_file':str(pw),'status_file':str(Path(self.temp.name)/'status.json')}
  source=Mock();source.load.return_value=([ACCOUNT],{'Sisal Sport':{'eligible':1}})
  conn=FakeIMAP(messages={5:self.recovery()});scanner=m.Scanner(cfg,self.state,lambda:conn);sender=self.sender()
  with patch.object(m,'now',return_value='2026-10-03T06:00:00+00:00'):
   summary=m.run_cycle(cfg,self.state,source=source,scanner=scanner,sender=sender,sleep=lambda _:None)
  self.assertEqual(summary['status'],'ok');self.assertEqual(summary['reactivation_delivery'],{'sent':1})
  self.assertEqual(source.load.call_count,2);sender.send.assert_called_once()

class DashboardMirrorTest(unittest.TestCase):
 setUp=StateTest.setUp
 tearDown=StateTest.tearDown
 event=StateTest.event
 def test_mirror_active_subscription_has_no_credentials(self):
  rows=m.mirror_rows(self.state,'2026-10-03T06:00:00+00:00')
  self.assertEqual(rows[2][2],'active');self.assertEqual(rows[2][4],'1')
  self.assertNotIn('password',json.dumps(rows).lower())
 def test_mirror_uses_latest_request_or_reactivation_received_time(self):
  self.event();sender=Mock();sender.send.return_value=('sent',1,0,None);m.deliver(self.state,[ACCOUNT],sender)
  watch=self.state.db.execute('SELECT * FROM followups').fetchone()
  with self.state.db:self.state.enqueue_followup(watch,raw(subject="Il tuo account e' stato riattivato",mid='<react>'),'03-Oct-2026 07:00:00 +0000')
  self.assertEqual(m.mirror_rows(self.state,'stamp')[2][2],'reactivated')
  with self.state.db:self.state.enqueue(ACCOUNT.email,'sisal',raw(mid='<new-doc>'),'04-Oct-2026 09:00:00 +0000')
  self.assertEqual(m.mirror_rows(self.state,'stamp')[2][2],'documents')
 def test_inactive_subscription_never_reported_as_monitored(self):
  self.event();self.state.sync([])
  self.assertEqual(m.mirror_rows(self.state,'stamp')[2][4],'0')
 def test_dashboard_write_is_raw_and_clears_only_old_range_tail(self):
  book=Mock();sheet=Mock();sheet.title='Banco';sheet.row_count=1000
  sheet.get_all_values.return_value=[m.MIRROR_HEADERS]+[['old']*8]*5
  book.worksheets.return_value=[sheet];client=Mock();client.open_by_key.return_value=book
  m.publish_dashboard({'dashboard_status':{'book':'log','sheet':'Banco'}},self.state,client)
  args=sheet.update.call_args.kwargs
  self.assertEqual(args['value_input_option'],'RAW');self.assertEqual(args['range_name'],'A1:H6')
  self.assertEqual(args['values'][-1],['']*8);sheet.clear.assert_not_called();book.add_worksheet.assert_not_called()
 def test_existing_tab_with_other_data_never_overwritten(self):
  sheet=Mock();sheet.title='Banco';sheet.get_all_values.return_value=[['Existing','data']]
  book=Mock();book.worksheets.return_value=[sheet];client=Mock();client.open_by_key.return_value=book
  with self.assertRaises(ValueError):m.publish_dashboard({'dashboard_status':{'book':'log','sheet':'Banco'}},self.state,client)
  sheet.update.assert_not_called()
 def test_disabled_dashboard_performs_no_google_writes(self):
  client=Mock();m.publish_dashboard({},self.state,client);client.open_by_key.assert_not_called()
 def test_sync_uses_actual_last_check_not_manual_publish_time(self):
  with self.state.db:self.state.db.execute("INSERT INTO runs(started,finished) VALUES('start','2026-10-02T19:00:00+00:00')")
  sheet=Mock();sheet.title='Banco';sheet.row_count=1000;sheet.get_all_values.return_value=[]
  book=Mock();book.worksheets.return_value=[sheet];client=Mock();client.open_by_key.return_value=book
  m.publish_dashboard({'dashboard_status':{'book':'log','sheet':'Banco'}},self.state,client)
  self.assertEqual(sheet.update.call_args.kwargs['values'][1][5],'2026-10-02T19:00:00+00:00')
 def bridge(self):
  path=Path(self.temp.name)/'bridge.json';path.write_text(json.dumps({'url':'https://script.google.com/test?key=TEST_SECRET'}))
  return {'dashboard_status':{'webhook_file':str(path)}}
 def test_webhook_sync_requires_matching_confirmation_digest(self):
  cfg=self.bridge();expected=m.mirror_rows(self.state,'')
  digest=m.hashlib.sha256(json.dumps(expected,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
  response=Mock();response.status_code=200;response.json.return_value={'ok':True,'digest':digest}
  with patch('requests.post',return_value=response) as post:m.publish_dashboard(cfg,self.state)
  self.assertEqual(post.call_args.kwargs['json'],{'banco_status_sync':expected})
 def test_mismatched_or_missing_webhook_confirmation_fails(self):
  cfg=self.bridge();response=Mock();response.status_code=200;response.json.return_value={'ok':True,'digest':'wrong'}
  with patch('requests.post',return_value=response):
   with self.assertRaises(RuntimeError):m.publish_dashboard(cfg,self.state)
 def test_sync_errors_do_not_expose_secret_url_in_cycle_summary(self):
  cfg={**CONFIG,**self.bridge(),'status_file':str(Path(self.temp.name)/'status.json'),'password_file':str(Path(self.temp.name)/'pw')}
  Path(cfg['password_file']).write_text('test-password');source=Mock();source.load.return_value=([ACCOUNT],{'Sisal Sport':{'eligible':1}})
  scanner=Mock();scanner.scan.return_value=({},[])
  with patch('requests.post',side_effect=OSError('TEST_SECRET')):
   result=m.run_cycle(cfg,self.state,source=source,scanner=scanner,sleep=lambda _:None)
  self.assertEqual(result['status'],'degraded');self.assertNotIn('TEST_SECRET',json.dumps(result))

class BancoUpgradeTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.state=m.State(Path(self.temp.name)/'state.sqlite3');self.state.sync([ACCOUNT])
 def tearDown(self):self.state.db.close();self.temp.cleanup()
 def test_both_sisal_senders_accepted_for_requests(self):
  for i,sender in enumerate(['info@sisal.it','infoclienti@sisal.it']):self.assertTrue(self.state.enqueue(ACCOUNT.email,'sisal',raw(sender=sender,mid=f'<doc{i}>'),'27-Sep-2026 18:48:40 +0200'))
 def test_new_sender_accepted_for_reactivation(self):
  self.state.enqueue(ACCOUNT.email,'sisal',raw(),'27-Sep-2026 18:48:40 +0200');event=self.state.db.execute('SELECT * FROM events').fetchone();self.state.start_followup(event,'2026-10-03T03:00:00+00:00');watch=self.state.db.execute('SELECT * FROM followups').fetchone()
  self.assertTrue(self.state.enqueue_followup(watch,raw(sender='infoclienti@sisal.it',subject="Il tuo account e' stato riattivato",mid='<react>'),'04-Oct-2026 08:30:00 +0200'))
 def test_similar_or_other_operator_senders_rejected(self):
  self.assertFalse(m.allowed_sender('sisal','infoclienti@sisal.it.example.org'));self.assertFalse(m.allowed_sender('pokerstars','infoclienti@sisal.it'))
 def record(self):return {'email':ACCOUNT.email,'operator':'sisal','subject':"Inviaci la copia del tuo documento d'identità",'received':'27-Sep-2026 18:48:40 +0200','sender':'infoclienti@sisal.it'}
 def test_one_time_import_is_idempotent_and_preserves_cursors(self):
  with self.state.db:self.state.advance(ACCOUNT.email,'sisal','INBOX',1,1,42)
  before=list(self.state.db.execute('SELECT * FROM cursors'))
  first=m.import_confirmed_requests(self.state,[self.record()],'2026-10-03T03:00:00+00:00');second=m.import_confirmed_requests(self.state,[self.record()],'2026-10-03T03:01:00+00:00')
  self.assertEqual(first,second);self.assertEqual(self.state.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],1);self.assertEqual(list(self.state.db.execute('SELECT * FROM cursors')),before)
 def test_import_delivery_opens_next_morning_watch(self):
  m.import_confirmed_requests(self.state,[self.record()],'2026-10-03T03:00:00+00:00');sender=Mock();sender.send.return_value=('sent',55,0,None)
  with patch.object(m,'now',return_value='2026-10-03T03:00:00+00:00'):m.deliver(self.state,[ACCOUNT],sender)
  self.assertEqual(self.state.db.execute('SELECT not_before FROM followups').fetchone()[0],'2026-10-04T06:00:00+00:00');m.deliver(self.state,[ACCOUNT],sender);sender.send.assert_called_once()
 def test_import_rejects_mismatched_sender_or_inactive_account(self):
  bad={**self.record(),'sender':'other@example.org'}
  with self.assertRaises(ValueError):m.import_confirmed_requests(self.state,[bad],m.now())
  self.state.sync([])
  with self.assertRaises(ValueError):m.import_confirmed_requests(self.state,[self.record()],m.now())
 def test_menu_bridge_failure_never_marks_delivery_uncertain(self):
  sender=object.__new__(m.Telegram);sender.token='TEST';sender.chat=1;sender.session=Mock();sender.dashboard_target={'webhook_file':'missing'}
  response=sender.session.post.return_value;response.status_code=200;response.json.return_value={'ok':True,'result':{'message_id':55}}
  self.assertEqual(sender.send('test'),('sent',55,0,None))
 def test_menu_bridge_only_receives_message_id(self):
  bridge=Path(self.temp.name)/'bridge.json';bridge.write_text(json.dumps({'url':'https://test.invalid'}));sender=object.__new__(m.Telegram);sender.dashboard_target={'webhook_file':str(bridge)}
  response=Mock();response.status_code=200;response.json.return_value={'ok':True}
  with patch('requests.post',return_value=response) as post:sender.restore_panel(55)
  self.assertEqual(post.call_args.kwargs['json'],{'banco_notice_message':55})
 def test_chat_snapshot_is_saved_without_credentials(self):
  cfg=MirrorTest.bridge(self) if False else None
  path=Path(self.temp.name)/'bridge.json';path.write_text(json.dumps({'url':'https://test.invalid'}));rows=m.mirror_rows(self.state,'');digest=m.hashlib.sha256(json.dumps(rows,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
  response=Mock();response.status_code=200;response.json.return_value={'ok':True,'digest':digest,'chat_state':{'panel':55,'routines':[],'retired':[],'last':55}}
  with patch('requests.post',return_value=response):m.publish_dashboard({'dashboard_status':{'webhook_file':str(path)}},self.state)
  snap=self.state.db.execute("SELECT value FROM settings WHERE key='banco_chat_snapshot'").fetchone()[0];self.assertIn('55',snap);self.assertNotIn('password',snap)

if __name__=='__main__':unittest.main(verbosity=2)
