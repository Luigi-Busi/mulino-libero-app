// Il Segretario shares account data with Il Banco, with separate authentication,
// Telegram tokens, update deduplication and chat lifecycle records.
const SEGRETARIO_USERNAME = 'Il_SegretarioBot';
const SEGRETARIO_CHAT_KEY = 'SEGRETARIO_CHAT_V1';
const SEGRETARIO_WEBAPP = 'https://script.google.com/macros/s/AKfycbzYApZs3vAeAgIE-nsIGarBElHOO973FsEbrreBw6qNbCT9rj2D8MfO9cmQV-_J5B1e/exec';
let bancoDashboardContext_ = false;

function bancoTokenProperty_() {return bancoDashboardContext_?'DASHBOARD_TELEGRAM_TOKEN':'TELEGRAM_TOKEN';}
function bancoChatKey_() {return bancoDashboardContext_?SEGRETARIO_CHAT_KEY:BANCO_CHAT_KEY;}
function bancoConDashboard_(fn) {
  const previous=bancoDashboardContext_;
  try {bancoDashboardContext_=true;return fn();} finally {bancoDashboardContext_=previous;}
}
function bancoDashboardSnapshot_() {return bancoConDashboard_(()=>bancoChatRead_());}
function bancoMoved_() {
  return {text:'La consultazione degli account è ora disponibile su Il Segretario.\nIl Banco continua a ricevere gli account e gli avvisi del monitor email.',
    buttons:[[{text:'Apri Il Segretario',url:'https://t.me/'+SEGRETARIO_USERNAME}],[bancoButton_('🏠 Menu Banco','bn:menu')]]};
}
function segretarioHelp_() {
  return {text:'📋 Il Segretario\n\n/menu, /account o /stato — fogli e stato account\n/help — questa guida\n\nApri un account per consultare nome, username, email e stato. I pulsanti copiano username, password dell’account ed email. La password resta nascosta nel testo.\n\n🟢 Attivo: nessuna richiesta documenti rilevata.\n🟠 Richiesta documenti: mail individuata dal monitor.\n✅ Riattivato: successiva mail di riattivazione individuata.\n⚪ Non monitorato: fuori dai controlli attivi.\n\nGli account sono mostrati per foglio, dai più recenti ai più vecchi. Aggiorna rilegge i dati disponibili.\n\nInserimenti, correzioni e avvisi email restano sul Banco.',
    buttons:[[bancoButton_('📊 Stato account','bn:root')]]};
}
function segretarioRiceviUpdate_(update) {
  if (!update || (!update.message && !update.callback_query)) return;
  if (typeof update.update_id!=='undefined' && !prenotaUpdate('segretario:'+String(update.update_id))) return;
  if (!bancoGestisciUpdate(update)) {
    const callback=update.callback_query,message=callback?callback.message:update.message;
    const actor=callback?callback.from:message && message.from,chat=message && message.chat;
    if (bancoPrivateAdmin_(actor,chat)) bancoRender_(chat,callback?message.message_id:null,segretarioHelp_());
  }
}
function bancoManutenzioneChat() {
  const previous=bancoDashboardContext_;
  try {
    bancoDashboardContext_=false;bancoManutenzioneChatScope_();
    if (PropertiesService.getScriptProperties().getProperty('DASHBOARD_TELEGRAM_TOKEN'))
      bancoConDashboard_(()=>bancoManutenzioneChatScope_());
  } finally {bancoDashboardContext_=previous;}
}
// Run only after the new version has been published on the existing deployment.
function configuraIlSegretario() {
  const props=PropertiesService.getScriptProperties(),token=props.getProperty('DASHBOARD_TELEGRAM_TOKEN');
  if (!token || token===props.getProperty('TELEGRAM_TOKEN')) throw new Error('Configura il token distinto del Segretario nelle proprietà private.');
  return bancoConDashboard_(()=>{
    const me=bancoApi_('getMe',{});
    if (!me || me.username!==SEGRETARIO_USERNAME) throw new Error('Il token non appartiene al bot Il Segretario previsto.');
    let secret=props.getProperty('DASHBOARD_WEBHOOK_SECRET');
    if (!secret) {secret=Utilities.getUuid().replace(/-/g,'')+Utilities.getUuid().replace(/-/g,'');props.setProperty('DASHBOARD_WEBHOOK_SECRET',secret);}
    const url=SEGRETARIO_WEBAPP+'?bot=dashboard&key='+encodeURIComponent(secret);
    const before=bancoApi_('getWebhookInfo',{});
    if (before.url && before.url!==url) throw new Error('Il nuovo bot ha già un collegamento differente: verificare prima di sostituirlo.');
    bancoApi_('setWebhook',{url:url,max_connections:1,allowed_updates:['message','callback_query']});
    const after=bancoApi_('getWebhookInfo',{});
    if (after.url!==url) throw new Error('Collegamento del Segretario non confermato.');
    bancoApi_('setMyCommands',{commands:[{command:'menu',description:'Apri gli account e il loro stato'},{command:'stato',description:'Riepilogo degli stati account'},{command:'help',description:'Guida del Segretario'}]});
    console.log(JSON.stringify({ok:true,bot:me.username,private_admin_only:true,webhook_confirmed:true,version:BANCO_MENU_VERSION}));
  });
}
function aggiornaMenuBanco() {
  if (bancoDashboardContext_) throw new Error('Contesto Banco richiesto.');
  const result=bancoRender_({id:String(ADMIN_TELEGRAM_ID)},null,bancoHome_());
  console.log(JSON.stringify({ok:true,bot:'Il Banco',menu_message:result.message_id,state_account_entry:false}));
}
function verificaSeparazioneBot() {
  const props=PropertiesService.getScriptProperties();
  const main=bancoApi_('getMe',{}),dashboard=bancoConDashboard_(()=>bancoApi_('getMe',{}));
  if (main.id===dashboard.id || dashboard.username!==SEGRETARIO_USERNAME) throw new Error('Identità dei bot non coerenti.');
  const oldHome=bancoHome_();
  if (oldHome.buttons.flat().some(b=>b.callback_data==='bn:root')) throw new Error('Stato account ancora presente nel menu Banco.');
  console.log(JSON.stringify({ok:true,banco:main.username,segretario:dashboard.username,separate_chat_keys:BANCO_CHAT_KEY!==SEGRETARIO_CHAT_KEY,version:BANCO_MENU_VERSION}));
}
