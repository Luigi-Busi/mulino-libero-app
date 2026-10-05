// Only message IDs, timestamps and explicitly allowed routine categories persist.
const BANCO_CHAT_KEY = 'BANCO_CHAT_V1';
let bancoContext_ = null;
let bancoSheetRefs_ = null;
let bancoForceRefresh_ = false;

function bancoChatRead_() {
  let s;
  try {s=JSON.parse(PropertiesService.getScriptProperties().getProperty(BANCO_CHAT_KEY)||'{}');} catch (_) {s={};}
  return {panel:Number(s.panel)||0,last:Number(s.last)||0,routines:Array.isArray(s.routines)?s.routines:[],retired:Array.isArray(s.retired)?s.retired:[]};
}
function bancoChatWrite_(s) {
  s.routines=s.routines.slice(-180);s.retired=s.retired.slice(-40);
  PropertiesService.getScriptProperties().setProperty(BANCO_CHAT_KEY,JSON.stringify(s));
}
function bancoChatLock_(fn) {
  const lock=LockService.getScriptLock();lock.waitLock(15000);
  try {return fn();} finally {lock.releaseLock();}
}
function bancoRoutine_(s,id,kind,at) {
  if (!Number.isSafeInteger(id)||id<=0||s.routines.some(r=>r[0]===id)) return;
  s.routines.push([id,at||Date.now(),kind]);
}
function bancoObserve_(message,command,callback) {
  bancoContext_={message:Number(message.message_id)||0,command:command,callback:!!callback};
  bancoChatLock_(()=>{
    const s=bancoChatRead_();s.last=Math.max(s.last,bancoContext_.message);
    if (!callback && ['/start','/menu','/account','/stato','/help','/test','/id','/correggi','/annulla'].indexOf(command)!==-1)
      bancoRoutine_(s,bancoContext_.message,'c',message.date?message.date*1000:Date.now());
    bancoChatWrite_(s);
  });
}
function bancoDeleteKnown_(id) {
  try {bancoApi_('deleteMessage',{chat_id:String(ADMIN_TELEGRAM_ID),message_id:id});return true;}
  catch (_) {return false;}
}
function bancoPanelRender_(chat,requested,view) {
  return bancoChatLock_(()=>{
    const s=bancoChatRead_();let result;
    const data={chat_id:String(chat.id),text:view.text.slice(0,3900),reply_markup:{inline_keyboard:view.buttons},link_preview_options:{is_disabled:true}};
    // Only a panel we own may be edited or retired. Notification buttons never own it.
    if (requested && requested===s.panel && s.last<=s.panel) {
      data.message_id=s.panel;
      try {result=bancoApi_('editMessageText',data);return result;} catch (_) {delete data.message_id;}
    }
    result=bancoApi_('sendMessage',data);
    const previous=s.panel;s.panel=result.message_id;s.last=Math.max(s.last,s.panel);
    if (previous && previous!==s.panel && !s.retired.includes(previous)) s.retired.push(previous);
    bancoChatWrite_(s);
    // Retired panels are removed immediately; ordinary replies have the 24h rule.
    s.retired=s.retired.filter(id=>id===s.panel?false:!bancoDeleteKnown_(id));bancoChatWrite_(s);
    return result;
  });
}
function bancoFinalize_() {
  if (!bancoContext_) return;
  const s=bancoChatRead_();
  if (s.panel && s.last>s.panel) bancoPanelRender_({id:ADMIN_TELEGRAM_ID},null,bancoHome_());
}
function bancoLegacySent_(chat,id,text) {
  if (String(chat)!==String(ADMIN_TELEGRAM_ID)) return;
  bancoChatLock_(()=>{
    const s=bancoChatRead_();s.last=Math.max(s.last,Number(id)||0);
    const ordinary=bancoContext_ && ['/test','/id','/correggi','/annulla'].indexOf(bancoContext_.command)!==-1;
    const problem=/errore|error|non riesco|fallit|problem|non trovato|mancant|⚠|❌/i.test(String(text));
    if (ordinary && !problem) bancoRoutine_(s,Number(id),'r');
    bancoChatWrite_(s);
  });
  bancoInvalidate_();
}
function bancoSkipLegacyDelete_(chat,id) {
  return String(chat)===String(ADMIN_TELEGRAM_ID) && bancoContext_ && Number(id)===bancoContext_.message;
}
function bancoExternalNotice_(id) {
  if (!Number.isSafeInteger(id)||id<=0) throw new Error('Identificativo messaggio non valido');
  bancoChatLock_(()=>{const s=bancoChatRead_();s.last=Math.max(s.last,id);bancoChatWrite_(s);});
  const s=bancoChatRead_();if (s.panel && s.last>s.panel) bancoPanelRender_({id:ADMIN_TELEGRAM_ID},null,bancoHome_());
  return ContentService.createTextOutput(JSON.stringify({ok:true})).setMimeType(ContentService.MimeType.JSON);
}
function bancoManutenzioneChat() {
  bancoChatLock_(()=>{
    const s=bancoChatRead_(),now=Date.now();
    const latest=Math.max(0,...s.routines.filter(r=>r[2]==='r').map(r=>r[0]));
    s.retired=s.retired.filter(id=>id===s.panel?false:!bancoDeleteKnown_(id));
    let count=0;
    s.routines=s.routines.filter(r=>{
      const id=r[0],age=now-r[1];
      if (id===s.panel || (r[2]==='r' && id===latest)) return true;
      if (age<86400000 || count>=12) return true;
      if (age>=172800000) return false; // Telegram can no longer delete it.
      count++;return !bancoDeleteKnown_(id);
    });
    bancoChatWrite_(s);
  });
}
function bancoConfiguraManutenzione() {
  const triggers=ScriptApp.getProjectTriggers().filter(t=>t.getHandlerFunction()==='bancoManutenzioneChat');
  if (!triggers.length) ScriptApp.newTrigger('bancoManutenzioneChat').timeBased().everyMinutes(15).create();
  console.log(JSON.stringify({ok:true,maintenance:'every_15_minutes',retention_hours:24,latest_reply_preserved:true}));
}
function bancoInvalidate_() {
  const cache=CacheService.getScriptCache();
  if (typeof cache.removeAll==='function') cache.removeAll(bancoBooks_().flatMap(b=>['Sisal Sport','PokerStars'].map(n=>'bn:'+BANCO_MENU_VERSION+':'+b.id+':'+n)).concat(['bn:root:'+BANCO_MENU_VERSION]));
}
