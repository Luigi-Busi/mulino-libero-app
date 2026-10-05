// Il Banco: private account dashboard. No credentials in logs/cache/callback_data.
const BANCO_MENU_VERSION = '1.1.2';
const BANCO_STATUS_TAB = 'Stato Account Banco';
const BANCO_PAGE_SIZE = 8;
const BANCO_COLORS = ['#ffffff','#ff00ff','#9900ff','#d9d2e9','#b4a7d6','#8e7cc3','#674ea7','#351c75','#20124d'];

// Manual commissioning check: only the configured administrator receives views.
function bancoVerificaMenuPrivato() {
  const chat={id:String(ADMIN_TELEGRAM_ID),type:'private'};
  bancoAnswerCallback_({id:'commissioning-expired-callback'});
  const root=bancoRender_(chat,null,bancoRoot_());
  const items=bancoSheets_(),item=items.find(s=>s.name==='Sisal Sport') || items[0];
  let list=null,descending=true;
  if (item) {
    const view=bancoSheet_(item.bookIndex,item.gid,0);
    const rows=view.buttons.flat().filter(b=>b.callback_data.indexOf('bn:a:')===0).map(b=>Number(b.callback_data.split(':')[4]));
    descending=rows.every((row,i)=>i===0 || row<rows[i-1]);
    if (!descending) throw new Error('Ordine account non valido');
    list=bancoRender_(chat,null,view);
  }
  console.log(JSON.stringify({ok:true,version:BANCO_MENU_VERSION,worksheets:items.length,root_message:root.message_id,list_message:list && list.message_id,descending:descending,expired_callback_does_not_block:true}));
}

function bancoRiceviStati_(rows) {
  const headers=['email','operatore','stato','ultima_variazione','monitorato','ultimo_controllo','consegna','id_evento'];
  if (rows.length<2 || rows.length>10000 || rows[0].join('|')!==headers.join('|') || rows[1][0]!=='__meta__') throw new Error('Stati non validi');
  rows.forEach((r,i)=>{
    if (!Array.isArray(r) || r.length!==8 || r.some(v=>typeof v!=='string' || v.length>320)) throw new Error('Formato stati non valido');
    if (i>1 && (['sisal','pokerstars','snai'].indexOf(r[1])===-1 || ['active','documents','reactivated'].indexOf(r[2])===-1 || !/^[01]$/.test(r[4]) || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(r[0]))) throw new Error('Record stato non valido');
  });
  const lock=LockService.getScriptLock();lock.waitLock(30000);
  try {
    const id=PropertiesService.getScriptProperties().getProperty('SPREADSHEET_ID_LOG_MAIL');
    if (!id) throw new Error('File log non configurato');
    const book=SpreadsheetApp.openById(id);
    let sheet=book.getSheetByName(BANCO_STATUS_TAB);
    if (!sheet) sheet=book.insertSheet(BANCO_STATUS_TAB);
    if (sheet.getLastRow() && sheet.getRange(1,1,1,8).getDisplayValues()[0].join('|')!==headers.join('|')) throw new Error('Scheda stati occupata da altri dati');
    const last=sheet.getLastRow(),total=Math.max(last,rows.length);
    if (sheet.getMaxRows()<total) sheet.insertRowsAfter(sheet.getMaxRows(),total-sheet.getMaxRows());
    const payload=rows.map(r=>r.map(v=>v.startsWith('=')?"'"+v:v));
    while (payload.length<total) payload.push(['','','','','','','','']);
    sheet.getRange(1,1,total,8).setNumberFormat('@').setValues(payload);
    SpreadsheetApp.flush();
    const digest=Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,JSON.stringify(rows),Utilities.Charset.UTF_8).map(v=>('0'+((v+256)%256).toString(16)).slice(-2)).join('');
    return ContentService.createTextOutput(JSON.stringify({ok:true,rows:rows.length,digest:digest,version:BANCO_MENU_VERSION,chat_state:bancoChatRead_()})).setMimeType(ContentService.MimeType.JSON);
  } finally {lock.releaseLock();}
}

function bancoApi_(method, data) {
  const token = PropertiesService.getScriptProperties().getProperty('TELEGRAM_TOKEN');
  if (!token) throw new Error('Banco non configurato');
  let response;
  try {
    response = UrlFetchApp.fetch('https://api.telegram.org/bot' + token + '/' + method, {
      method: 'post', contentType: 'application/json', payload: JSON.stringify(data), muteHttpExceptions: true
    });
  } catch (_) { throw new Error('Connessione Telegram non riuscita'); }
  let value;
  try { value = JSON.parse(response.getContentText()); } catch (_) { throw new Error('Risposta Telegram non valida'); }
  if (!value.ok) {
    if (method === 'editMessageText' && String(value.description || '').indexOf('message is not modified') !== -1) return;
    throw new Error('Operazione Telegram non riuscita');
  }
  return value.result;
}

function bancoAnswerCallback_(callback,options) {
  try {bancoApi_('answerCallbackQuery',Object.assign({callback_query_id:callback.id},options||{}));}
  catch (_) {console.warn('Banco: conferma clic non disponibile; apertura schermata prosegue.');}
}
function bancoMenuFailure_(chat) {
  const text='Non riesco ad aggiornare la schermata. Riprova con /menu. Nessuna modifica è stata effettuata agli account.';
  const result=bancoApi_('sendMessage',{chat_id:String(chat.id),text:text});
  try {bancoLegacySent_(chat.id,result.message_id,text);} catch (_) {}
}

function bancoPrivateAdmin_(actor, chat) {
  return !!actor && !!chat && !actor.is_bot && chat.type === 'private' &&
    String(actor.id) === String(ADMIN_TELEGRAM_ID) && String(chat.id) === String(ADMIN_TELEGRAM_ID);
}

function bancoRender_(chat,message,view) {return bancoPanelRender_(chat,message,view);}

function bancoGestisciUpdate(update) {
  const callback = update.callback_query;
  const message = callback ? callback.message : update.message;
  const text = String(message && message.text || '').trim();
  const command = text.split(/\s/)[0].split('@')[0].toLowerCase();
  let data = callback ? String(callback.data || '') : '';
  bancoForceRefresh_=data.indexOf('bn:r:')===0;
  if (bancoForceRefresh_) data=data.replace('bn:r:','bn:');
  const recognized = callback ? data.indexOf('bn:') === 0 : ['/start','/menu','/account','/stato','/help'].indexOf(command) !== -1;

  const actor = callback ? callback.from : message && message.from;
  const chat = message && message.chat;
  if (!bancoPrivateAdmin_(actor,chat)) {
    if (!recognized) return false;
    if (callback) bancoAnswerCallback_(callback,{text:'Menu riservato alla chat privata dell’amministratore.',show_alert:true});
    else if (chat) bancoApi_('sendMessage',{chat_id:chat.id,text:'Menu riservato alla chat privata dell’amministratore.'});
    return true;
  }
  // A delayed/expired Telegram acknowledgement must never swallow the action.
  if (recognized && callback) bancoAnswerCallback_(callback);
  try {bancoObserve_(message,callback && /^bn:cmd:/.test(data)?'/'+data.split(':')[2]:command,callback);}
  catch (_) {if (recognized) {bancoMenuFailure_(chat);return true;} throw _;}
  if (!recognized) return false;
  // Existing commands continue through the original authorization/correction code.
  if (callback && /^bn:cmd:(correggi|annulla|test|id)$/.test(data)) {
    update.message = {from:actor, chat:chat, message_id:message.message_id,text:'/'+data.split(':')[2]};
    return false;
  }
  try {
    let view;
    if (!callback) view = ['/account','/stato'].indexOf(command)!==-1 ? bancoRoot_() : command==='/help' ? bancoHelp_() : bancoHome_();
    else if (data==='bn:menu') view=bancoHome_();
    else if (data==='bn:help') view=bancoHelp_();
    else if (data==='bn:root') view=bancoRoot_();
    else {
      const pieces=data.split(':');
      if (pieces[1]==='s' && pieces.length===5 && pieces.slice(2).every(x=>/^\d+$/.test(x)))
        view=bancoSheet_(Number(pieces[2]),Number(pieces[3]),Number(pieces[4]));
      else if (pieces[1]==='a' && pieces.length===7 && pieces.slice(2,5).every(x=>/^\d+$/.test(x)) && /^[a-f0-9]{12}$/.test(pieces[5]) && /^\d+$/.test(pieces[6]))
        view=bancoAccount_(Number(pieces[2]),Number(pieces[3]),Number(pieces[4]),pieces[5],Number(pieces[6]));
      else view={text:'Questo pulsante non è più valido. Torna all’elenco aggiornato.',buttons:[[bancoButton_('📊 Stato account','bn:root')]]};
    }
    bancoRender_(chat,callback ? message.message_id : null,view);
  } catch (_) {
    bancoMenuFailure_(chat);
  }
  return true;
}

function bancoButton_(text,data) {return {text:text,callback_data:data};}
function bancoHome_() {
  return {text:'🏦 Il Banco\n\nConsulta gli account e il loro stato, oppure usa i comandi di gestione.\nPer inserire un account, invia il messaggio completo con i dati come fai già.',buttons:[
    [bancoButton_('📊 Stato account','bn:root')],
    [bancoButton_('✏️ Correggi ultimo inserimento','bn:cmd:correggi')],
    [bancoButton_('↩️ Annulla correzione','bn:cmd:annulla'),bancoButton_('🧪 Test','bn:cmd:test')],
    [bancoButton_('❓ Guida','bn:help'),bancoButton_('🆔 Il mio ID','bn:cmd:id')]]};
}
function bancoHelp_() {
  return {text:'🏦 Guida del Banco\n\n/menu — apre il menu\n/account o /stato — fogli e stato account\n/correggi — corregge il tuo ultimo inserimento entro 60 minuti; reinvia poi il messaggio completo\n/annulla — esce dalla correzione\n/test — verifica i collegamenti configurati\n/id — mostra il tuo identificativo Telegram\n\nNella scheda account puoi copiare username, password dell’account ed email. La password è nascosta nel testo.\n\n🟢 Attivo: nessuna richiesta documenti rilevata dal monitor.\n🟠 Richiesta documenti: mail individuata dal monitor.\n✅ Riattivato: successiva mail di riattivazione individuata.\n⚪ Non monitorato: fuori dai controlli attivi.\n\nIl monitor controlla ogni ora dalle 08:00 alle 21:00, ora italiana. Dopo la notifica della richiesta documento, la riattivazione viene cercata dalle 08:00 del giorno successivo, inclusa la posta arrivata nel frattempo.',buttons:[[bancoButton_('📊 Stato account','bn:root'),bancoButton_('🏠 Menu','bn:menu')]]};
}

function bancoBooks_() {
  const props=PropertiesService.getScriptProperties();
  return ['SPREADSHEET_ID'].map((key,index)=>({key:key,index:index,id:props.getProperty(key)})).filter(b=>!!b.id);
}
function bancoSheets_() {
  if (bancoSheetRefs_) return bancoSheetRefs_;
  const result=[];
  bancoBooks_().forEach(b=>{
    const book=SpreadsheetApp.openById(b.id);
    book.getSheets().forEach(sheet=>{
      const cfg=Object.keys(CONFIG_SITI).map(k=>CONFIG_SITI[k]).find(c=>c.spreadsheetProperty===b.key && c.foglio===sheet.getName());
      if (cfg && ['Sisal Sport','PokerStars'].indexOf(sheet.getName())!==-1) result.push({book:b.id,bookIndex:b.index,bookTitle:book.getName(),sheet:sheet,gid:sheet.getSheetId(),name:sheet.getName()});
    });
  });
  bancoSheetRefs_=result;return result;
}
function bancoFindSheet_(bi,gid) {
  const item=bancoSheets_().find(s=>s.bookIndex===bi && s.gid===gid);
  if (!item) throw new Error('Foglio non disponibile');
  return item;
}
function bancoNorm_(v) {return String(v||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[-_]/g,' ').replace(/\s+/g,' ').trim();}
function bancoHeaders_(values) {
  for (let r=0;r<Math.min(30,values.length);r++) {
    const row=values[r].map(bancoNorm_);
    const find=names=>row.findIndex(v=>names.indexOf(v)!==-1);
    const h={row:r,name:find(['nome cognome','nome e cognome','nome cliente']),username:find(['username','user name']),password:find(['password','pass']),email:find(['e mail','email','email usata','e mail usata']),mailPassword:find(['password e mail','password email','pass e mail','pass email']),stable:find(['id mulino'])};
    if (h.name>=0 && h.password>=0 && (h.username>=0 || h.email>=0)) return h;
  }
  throw new Error('Intestazioni account non riconosciute');
}
function bancoFingerprint_(a) {
  const raw=[a.name,a.username,a.email,a.stable].join('\n');
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,raw,Utilities.Charset.UTF_8).map(v=>('0'+((v+256)%256).toString(16)).slice(-2)).join('').slice(0,12);
}
function bancoAccounts_(item,withPassword,rowNumber) {
  const sheet=item.sheet,cache=CacheService.getScriptCache(),key='bn:'+BANCO_MENU_VERSION+':'+item.book+':'+item.name;
  if (!withPassword && !bancoForceRefresh_) {
    try {const hit=cache.get(key);if (hit) return JSON.parse(hit);} catch (_) {}
  }
  const last=sheet.getLastRow();if (!last || last>10000) throw new Error('Dimensioni foglio non riconosciute');
  const width=Math.min(sheet.getLastColumn(),26);
  const headerValues=sheet.getRange(1,1,rowNumber?Math.min(last,30):last,width).getDisplayValues();
  const headers=bancoHeaders_(headerValues);
  if (rowNumber && (rowNumber<=headers.row+1 || rowNumber>last)) return [];
  const start=rowNumber||1;
  const values=rowNumber?sheet.getRange(rowNumber,1,1,width).getDisplayValues():headerValues;
  const colors=sheet.getRange(start,1,values.length,width).getBackgrounds();const result=[];
  for (let i=0;i<values.length;i++) {
    const physical=start+i;if (physical<=headers.row+1) continue;
    const row=values[i],get=n=>n>=0?String(row[n]||'').trim():'';
    const name=get(headers.name),username=get(headers.username),email=get(headers.email);
    if (!name || (!username && !email && !get(headers.password))) continue;
    const a={row:physical,name:name,username:username,email:email,stable:get(headers.stable),emailColor:headers.email>=0?colors[i][headers.email].toLowerCase():'unknown',mailPasswordColor:headers.mailPassword>=0?colors[i][headers.mailPassword].toLowerCase():'unknown',hasMailPassword:!!get(headers.mailPassword)};
    if (withPassword) a.password=get(headers.password);
    a.fingerprint=bancoFingerprint_(a);result.push(a);
  }
  if (!withPassword) {try {const raw=JSON.stringify(result);if (raw.length<80000) cache.put(key,raw,45);} catch (_) {}}
  return result;
}

function bancoMirror_() {
  const id=PropertiesService.getScriptProperties().getProperty('SPREADSHEET_ID_LOG_MAIL');
  const data={states:{},updated:'',available:false};
  if (!id) return data;
  const sheet=SpreadsheetApp.openById(id).getSheetByName(BANCO_STATUS_TAB);
  if (!sheet) return data;
  const rows=sheet.getDataRange().getDisplayValues();
  if (!rows.length || rows[0].join('|')!=='email|operatore|stato|ultima_variazione|monitorato|ultimo_controllo|consegna|id_evento') return data;
  rows.slice(1).forEach(r=>{
    if (r[0]==='__meta__') {data.updated=r[5];data.available=true;}
    else data.states[String(r[0]).trim().toLowerCase()+'\n'+r[1]]={state:r[2],changed:r[3],monitored:r[4]==='1',delivery:r[6]};
  });
  return data;
}
function bancoAllowedColor_(c) {return BANCO_COLORS.indexOf(c)!==-1 || (/^#[0-9a-f]{6}$/.test(c) && c!=='#000000' && c.slice(1,3)===c.slice(3,5) && c.slice(3,5)===c.slice(5,7));}
function bancoState_(item,account,mirror) {
  const operator=item.name==='Sisal Sport'?'sisal':item.name==='PokerStars'?'pokerstars':null;
  const record=mirror.states[account.email.toLowerCase()+'\n'+operator];
  if (!operator) return {code:'unmonitored',label:'⚪ Non monitorato',detail:'Questo operatore non è incluso nel monitor delle email.'};
  if (!account.email || !account.hasMailPassword || account.emailColor!==account.mailPasswordColor || !bancoAllowedColor_(account.emailColor))
    return {code:'unmonitored',label:'⚪ Non monitorato',detail:'Account escluso dagli attuali controlli sulle celle email/password email.'};
  if (!mirror.available || !record) return {code:'unknown',label:'🔵 In attesa di controllo',detail:'Lo stato sarà disponibile dopo il prossimo controllo del monitor.'};
  if (!record.monitored) return {code:'unmonitored',label:'⚪ Non monitorato',detail:'Account escluso dall’ultimo controllo del monitor.'};
  const labels={active:'🟢 Attivo',documents:'🟠 Richiesta documenti',reactivated:'✅ Riattivato'};
  return {code:record.state,label:labels[record.state]||'🔵 In attesa di controllo',changed:record.changed,detail:record.state==='active'?'Nessuna richiesta documenti rilevata dal monitor.':''};
}
function bancoDate_(value) {
  if (!value) return '—';
  const d=new Date(value);return isNaN(d.getTime())?'—':Utilities.formatDate(d,'Europe/Rome','dd/MM/yyyy HH:mm');
}
function bancoCounts_(accounts,item,mirror) {
  const counts={active:0,documents:0,reactivated:0,unmonitored:0,unknown:0};
  accounts.forEach(a=>{const s=bancoState_(item,a,mirror);counts[s.code]=(counts[s.code]||0)+1;});
  return '🟢 '+counts.active+'  🟠 '+counts.documents+'  ✅ '+counts.reactivated+'  ⚪ '+counts.unmonitored+(counts.unknown?'  🔵 '+counts.unknown:'');
}
function bancoRoot_() {
  const cache=CacheService.getScriptCache(),key='bn:root:'+BANCO_MENU_VERSION;
  if (!bancoForceRefresh_) {try {const hit=cache.get(key);if(hit) return JSON.parse(hit);} catch (_) {}}
  const mirror=bancoMirror_(),items=bancoSheets_(),buttons=[];
  let text='📊 Stato account\n\n';let lastBook=null;
  items.forEach(item=>{
    if (lastBook!==item.book) {text+='📁 '+item.bookTitle+'\n';lastBook=item.book;}
    const accounts=bancoAccounts_(item,false);
    text+=item.name+' · '+accounts.length+' account\n'+bancoCounts_(accounts,item,mirror)+'\n\n';
    buttons.push([bancoButton_('Apri '+item.name,'bn:s:'+item.bookIndex+':'+item.gid+':0')]);
  });
  text+='🟢 Attivo · 🟠 Richiesta documenti · ✅ Riattivato\n⚪ Non monitorato · 🔵 In attesa di controllo\n\nUltimo controllo: '+bancoDate_(mirror.updated);
  buttons.push([bancoButton_('🔄 Aggiorna','bn:r:root'),bancoButton_('🏠 Menu','bn:menu')]);
  const view={text:text,buttons:buttons};
  try {cache.put(key,JSON.stringify(view),45);} catch (_) {}
  return view;
}
function bancoSheet_(bi,gid,requestedPage) {
  const item=bancoFindSheet_(bi,gid),mirror=bancoMirror_(),accounts=bancoAccounts_(item,false).slice().reverse();
  const pages=Math.max(1,Math.ceil(accounts.length/BANCO_PAGE_SIZE)),page=Math.min(requestedPage,pages-1);
  const batch=accounts.slice(page*BANCO_PAGE_SIZE,(page+1)*BANCO_PAGE_SIZE);
  let text='📁 '+item.bookTitle+'\n'+item.name+' · '+accounts.length+' account\n'+bancoCounts_(accounts,item,mirror)+'\n\nPagina '+(page+1)+'/'+pages+' · ultimi inseriti per primi\n';
  const buttons=batch.map(a=>[bancoButton_(bancoState_(item,a,mirror).label+' · '+a.name.slice(0,55),'bn:a:'+bi+':'+gid+':'+a.row+':'+a.fingerprint+':'+page)]);
  if (!batch.length) text+='\nNessun account presente.';
  const nav=[];
  if (page>0) nav.push(bancoButton_('◀️ Indietro','bn:s:'+bi+':'+gid+':'+(page-1)));
  if (page+1<pages) nav.push(bancoButton_('Avanti ▶️','bn:s:'+bi+':'+gid+':'+(page+1)));
  if (nav.length) buttons.push(nav);
  buttons.push([bancoButton_('🔄 Aggiorna','bn:r:s:'+bi+':'+gid+':'+page),bancoButton_('📂 Fogli','bn:root')]);
  return {text:text,buttons:buttons};
}
function bancoAccount_(bi,gid,row,fingerprint,page) {
  const item=bancoFindSheet_(bi,gid),account=bancoAccounts_(item,true,row).find(a=>a.row===row);
  const back='bn:s:'+bi+':'+gid+':'+page;
  if (!account || account.fingerprint!==fingerprint) return {text:'La riga dell’account è cambiata. Apri di nuovo l’elenco per consultare i dati aggiornati.',buttons:[[bancoButton_('📋 Torna agli account',back)]]};
  const mirror=bancoMirror_(),state=bancoState_(item,account,mirror);
  let text=account.name+' — '+item.name+'\n'+state.label+'\n\nUsername: '+(account.username||'—')+'\nEmail: '+(account.email||'—')+'\nPassword: '+(account.password?'nascosta · usa il pulsante Copia':'non presente');
  if (state.detail) text+='\n\n'+state.detail;
  if (state.changed) text+='\nUltimo cambio di stato: '+bancoDate_(state.changed);
  text+='\nUltimo controllo: '+bancoDate_(mirror.updated);
  const buttons=[],copy=[];
  [['📋 Copia username',account.username],['🔑 Copia password',account.password],['📧 Copia email',account.email]].forEach(pair=>{
    if (pair[1] && Array.from(pair[1]).length<=256) copy.push({text:pair[0],copy_text:{text:pair[1]}});
  });
  if (copy.length) buttons.push(copy);
  buttons.push([bancoButton_('🔄 Aggiorna','bn:r:a:'+bi+':'+gid+':'+row+':'+fingerprint+':'+page),bancoButton_('↩️ Account',back)]);
  return {text:text,buttons:buttons};
}
