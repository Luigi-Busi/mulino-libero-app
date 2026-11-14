
"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs"),path=require("node:path");
const {fixture,account,headers,Metadata}=require("./emailmatcher.test.cjs");
let passed=0;
function test(name,work) {
  try {work();passed++;process.stdout.write("ok telegram "+passed+" - "+name+"\n");}
  catch(e){process.stderr.write("FAIL telegram - "+name+"\n");throw e;}
}
const prefix="EM_TG_OMONIMO_V1_";
function setup(prior=account("old","01/11/2026","old@example.test")) {
  const f=fixture(prior,account("new","22/11/2026"));
  assert.equal(f.run().stato,"AMBIGUA");
  return f;
}
function session(f,nonce) {
  const keys=[...f.props.keys()].filter(k=>k.startsWith(prefix));
  return JSON.parse(f.props.get(nonce?prefix+nonce:keys.at(-1)));
}
function click(f,operation,nonce,change={}) {
  const s=session(f,nonce);
  const cb={id:"callback-"+Math.random(),data:"emh:"+s.nonce+":"+operation,
    from:{id:"fixture-owner",is_bot:false},
    message:{message_id:s.message,chat:{id:"fixture-owner",type:"private"}}};
  Object.assign(cb,change);
  assert.equal(f.context.EM_gestisciCallbackOmonimo_({callback_query:cb}),true);
  return session(f,s.nonce);
}
function choose(f,operation="s:0") {return click(f,operation);}
function confirm(f,nonce) {
  const s=session(f,nonce);
  return click(f,"c:"+s.selection.token,s.nonce);
}
function decision(f,row=f.sheet.cells.length) {return f.reg(row,false).metadata.data.decisione;}
function edits(f){return f.telegramCalls.filter(c=>c.method==="editMessageText");}
function immutable(f) {
  assert.equal(f.sheet.cells.at(-1)[3],"");
  assert.equal(f.queue().length,1);
  assert.equal(decision(f),undefined);
}
test("alert lists addresses, sources and new-mail button with short opaque callbacks",()=>{
  const f=setup(), sent=f.telegramCalls.find(c=>c.method==="sendMessage").payload;
  assert(sent.text.includes("old@example.test"));assert(sent.text.includes("Sisal Sport"));
  assert(sent.text.includes("\n"));assert(!sent.text.includes("\\n"));assert(sent.text.length<4096);
  const buttons=sent.reply_markup.inline_keyboard.flat();
  assert(buttons.some(b=>b.text==="➕ Crea nuova mail"));
  buttons.forEach(b=>{assert(Buffer.byteLength(b.callback_data)<=64);assert(!b.callback_data.includes("@"));});
  immutable(f);
});
test("choosing an email only opens a confirmation",()=>{
  const f=setup();const s=choose(f);
  assert.equal(s.status,"OPEN");assert.equal(s.selection.email,"old@example.test");
  immutable(f);
  assert(edits(f).at(-1).payload.reply_markup.inline_keyboard.flat().some(b=>b.text==="✅ Conferma"));
});
test("confirm writes the selected email and saves its decision",()=>{
  const f=setup();choose(f);const s=confirm(f);
  assert.equal(s.status,"DONE");assert.equal(f.sheet.cells[2][3],"old@example.test");
  assert.equal(decision(f).azione,"USA_EMAIL");
  assert.equal(decision(f).revisioneTelegram,s.nonce);
  assert.equal(f.queue().length,1);
  assert.equal(edits(f).at(-1).payload.reply_markup.inline_keyboard.length,0);
});
test("new-mail confirmation saves the choice and queues one normal request",()=>{
  const f=setup();choose(f,"n");const s=confirm(f);
  assert.equal(s.status,"DONE");assert(s.requestId);
  assert.equal(f.queue().length,2);assert.equal(f.queue()[1][3],"DA_COMPLETARE_ANAGRAFICA");
  assert.equal(decision(f).azione,"NUOVA_MAIL");assert.equal(f.sheet.cells[2][3],"");
});
test("replaying a confirmed button never queues twice",()=>{
  const f=setup();const s=choose(f,"n");confirm(f);
  click(f,"c:"+s.selection.token);click(f,"n");click(f,"s:0");
  assert.equal(f.queue().length,2);assert.equal(decision(f).azione,"NUOVA_MAIL");
});
test("back cancels the pending choice and old confirmation becomes harmless",()=>{
  const f=setup(),s=choose(f);click(f,"b");click(f,"c:"+s.selection.token);
  immutable(f);assert.equal(session(f).selection,undefined);
});
test("a superseded confirmation cannot apply a different choice",()=>{
  const f=setup(),old=choose(f);
  choose(f,"n");click(f,"c:"+old.selection.token);
  immutable(f);assert.equal(session(f).selection,undefined);
});
test("arbitrary and out-of-range candidate indexes cannot assign an email",()=>{
  const f=setup();click(f,"s:99999");immutable(f);
  assert.equal(session(f).selection,undefined);
});
for(const [name,change] of [
  ["another actor",{from:{id:"another-user"}}],
  ["a bot actor",{from:{id:"fixture-owner",is_bot:true}}],
  ["a group",{message:{message_id:1,chat:{id:"fixture-owner",type:"group"}}}],
  ["another private chat",{message:{message_id:1,chat:{id:"other-chat",type:"private"}}}],
  ["another message",{message:{message_id:999,chat:{id:"fixture-owner",type:"private"}}}]
]) test("rejects "+name,()=>{
  const f=setup();click(f,"n",undefined,change);immutable(f);
  assert.equal(session(f).selection,undefined);assert.equal(edits(f).length,0);
});
test("unknown or malformed callback data cannot write",()=>{
  const f=setup();click(f,"c:forged");immutable(f);
  assert.equal(session(f).selection,undefined);
  const s=session(f);click(f,"n",s.nonce,{data:"emh:"+"a".repeat(24)+":n"});immutable(f);
});
test("existing Banco callbacks are left to their own handler",()=>{
  const f=setup();
  assert.equal(f.context.EM_gestisciCallbackOmonimo_({callback_query:{data:"bn:menu"}}),false);
  immutable(f);
});
test("Segretario context never uses the Banco revision channel",()=>{
  const f=setup();f.context.bancoDashboardContext_=true;
  assert.equal(f.context.EM_gestisciCallbackOmonimo_({callback_query:{data:"emh:"+session(f).nonce+":n"}}),false);
  immutable(f);
});
test("changed source email invalidates the old choices and reissues a fresh alert",()=>{
  const f=setup(),old=choose(f);
  f.sheet.cells[1][3]="changed@example.test";
  click(f,"c:"+old.selection.token,old.nonce);
  assert.equal(session(f,old.nonce).status,"STALE");immutable(f);
  assert.notEqual(session(f).nonce,old.nonce);assert.equal(f.notifications.length,2);
});
test("a new candidate makes an old confirmation stale",()=>{
  const f=setup(),old=choose(f,"n");
  f.books.get("main").getSheetByName("PokerStars").cells.push(account("cross","","cross@example.test"));
  click(f,"c:"+old.selection.token,old.nonce);immutable(f);
  assert.equal(session(f,old.nonce).status,"STALE");
});
test("edited target username cannot receive an old choice",()=>{
  const f=setup(),s=choose(f);
  f.sheet.cells[2][2]="corrected";
  click(f,"c:"+s.selection.token,s.nonce);immutable(f);
  assert.equal(session(f,s.nonce).status,"STALE");
});
test("a fresh review can acknowledge a corrected row",()=>{
  const f=setup(),old=session(f);
  f.sheet.cells[2][2]="corrected";
  f.run();
  assert.notEqual(session(f).nonce,old.nonce);
  choose(f);assert.equal(confirm(f).status,"DONE");
  assert.equal(f.sheet.cells[2][3],"old@example.test");
});
test("moved full rows resolve by ID_MULINO rather than the old row number",()=>{
  const f=setup();
  f.sheet.cells.splice(2,0,account("other","","","Other Person"));
  f.sheet.meta.filter(m=>m.row>=3).forEach(m=>m.row++);
  choose(f);const s=confirm(f);
  assert.equal(s.row,4);assert.equal(f.sheet.cells[3][3],"old@example.test");
  assert.equal(f.sheet.cells[2][3],"");
});
test("duplicate account IDs block the callback",()=>{
  const f=setup();f.sheet.cells[1][6]=f.sheet.cells[2][6];
  click(f,"n");assert.equal(f.queue().length,1);assert.equal(decision(f),undefined);
});
test("an existing destination email is never overwritten",()=>{
  const f=setup();choose(f);f.sheet.cells[2][3]="already@example.test";
  confirm(f);assert.equal(f.sheet.cells[2][3],"already@example.test");
  assert.equal(decision(f),undefined);assert.equal(f.queue().length,1);
});
test("non-white destination rows cannot be resolved through old buttons",()=>{
  const f=setup();choose(f);f.sheet.colors[3]="#ffaaaa";confirm(f);immutable(f);
});
test("an expired review cannot save a choice",()=>{
  const f=setup(),s=session(f);s.created-=25*3600000;
  f.props.set(prefix+s.nonce,JSON.stringify(s));
  click(f,"n",s.nonce);immutable(f);assert.equal(session(f,s.nonce).status,"STALE");
});
test("the next scan renews an expired unresolved alert",()=>{
  const f=setup(),s=session(f);s.created-=25*3600000;
  f.props.set(prefix+s.nonce,JSON.stringify(s));f.run();
  assert.notEqual(session(f).nonce,s.nonce);assert.equal(f.notifications.length,2);
});
test("paging shows all candidates without saving a decision",()=>{
  const f=fixture(null,account("new","22/11/2026"));
  const archive=f.books.get("archive").getSheetByName("Sisal Old");
  for(let i=0;i<13;i++)archive.cells.push(account("old"+i,"01/11/2026","person"+i+"@example.test"));
  assert.equal(f.run().stato,"AMBIGUA");
  const first=f.telegramCalls.find(c=>c.method==="sendMessage").payload;
  assert.equal(first.reply_markup.inline_keyboard.filter(row=>row[0].callback_data.includes(":s:")).length,5);
  click(f,"p:2");
  const view=edits(f).at(-1).payload;
  assert(view.text.includes("pagina 3/3"));
  assert.equal(view.reply_markup.inline_keyboard.filter(row=>row[0].callback_data.includes(":s:")).length,3);
  click(f,"s:12");assert.equal(confirm(f).status,"DONE");assert(f.sheet.cells.at(-1)[3]);
});
test("a case without found emails still allows a new-mail confirmation",()=>{
  const f=setup(account("old","01/11/2026",""));
  const view=f.telegramCalls.find(c=>c.method==="sendMessage").payload;
  assert.equal(view.reply_markup.inline_keyboard.flat().length,1);
  choose(f,"n");assert.equal(confirm(f).status,"DONE");assert.equal(f.queue().length,2);
});
test("duplicate occurrences of one address produce a single choice",()=>{
  const f=fixture(undefined,account("new","22/11/2026"));
  f.books.get("main").getSheetByName("PokerStars").cells.push(account("same","","OLD@example.test"));
  f.run();
  const view=f.telegramCalls.find(c=>c.method==="sendMessage").payload;
  assert.equal(view.reply_markup.inline_keyboard.filter(row=>row[0].callback_data.includes(":s:")).length,1);
});
test("an open creation request blocks assigning another existing email",()=>{
  const f=setup(),c=f.context;
  c.EM_accodaCreazioneMail({getProperty:k=>f.props.get(k)},"main","Sisal Sport",3,4,"Mario Rossi");
  choose(f);confirm(f);
  assert.equal(decision(f),undefined);assert.equal(f.sheet.cells[2][3],"");
  assert.equal(f.queue().length,2);
  assert(edits(f).at(-1).payload.text.includes("richiesta di creazione aperta"));
});
test("new-mail choice reuses an existing request",()=>{
  const f=setup(),c=f.context;
  const id=c.EM_accodaCreazioneMail({getProperty:k=>f.props.get(k)},"main","Sisal Sport",3,4,"Mario Rossi");
  choose(f,"n");const s=confirm(f);assert.equal(s.requestId,id);assert.equal(f.queue().length,2);
});
test("queue failure retains a durable choice and retry completes it once",()=>{
  const f=setup(),original=f.context.EM_accodaCreazioneMail;
  let fail=true;
  f.context.EM_accodaCreazioneMail=function(...args){if(fail)throw Error("PRIVATE failure");return original(...args);};
  choose(f,"n");const pending=confirm(f);
  assert.equal(pending.status,"APPLYING");assert.equal(decision(f).azione,"NUOVA_MAIL");
  assert(!edits(f).at(-1).payload.text.includes("PRIVATE"));
  fail=false;confirm(f);confirm(f);
  assert.equal(session(f).status,"DONE");assert.equal(f.queue().length,2);
});
test("a lost DONE write is recovered without duplicating the email effect",()=>{
  const f=setup(),factory=f.context.PropertiesService.getScriptProperties;
  let fail=true;
  f.context.PropertiesService.getScriptProperties=()=>({
    ...factory(),setProperty(key,value) {
      if(fail&&key.startsWith(prefix)&&JSON.parse(value).status==="DONE"){fail=false;throw Error("write failure");}
      return factory().setProperty(key,value);
    }
  });
  choose(f);confirm(f);
  assert.equal(f.sheet.cells[2][3],"old@example.test");assert.equal(session(f).status,"APPLYING");
  confirm(f);assert.equal(session(f).status,"DONE");assert.equal(f.queue().length,1);
});
test("a failed Telegram acknowledgement does not swallow a valid confirmation",()=>{
  const f=setup(),api=f.context.bancoApi_;
  f.context.bancoApi_=(method,payload)=>{if(method==="answerCallbackQuery")throw Error("expired");return api(method,payload);};
  choose(f);assert.equal(confirm(f).status,"DONE");assert.equal(f.sheet.cells[2][3],"old@example.test");
});
test("a failed success-message edit cannot replay the applied action",()=>{
  const f=setup(),api=f.context.bancoApi_;let fail=false;
  f.context.bancoApi_=(method,payload)=>{if(fail&&method==="editMessageText")throw Error("edit failed");return api(method,payload);};
  choose(f,"n");fail=true;confirm(f);
  assert.equal(session(f).status,"DONE");assert.equal(f.queue().length,2);
  fail=false;confirm(f);assert.equal(f.queue().length,2);
});
test("lock contention cannot save or apply a decision",()=>{
  const f=setup();
  f.context.LockService.getScriptLock=()=>({tryLock:()=>false,releaseLock(){throw Error("not held");}});
  click(f,"n");immutable(f);assert.equal(session(f).selection,undefined);
});
test("callback sessions and choices survive a new script runtime",()=>{
  const first=setup();choose(first,"n");const saved=session(first);
  const next=fixture(undefined,account("new","22/11/2026"));
  for(const [key,value] of first.props)next.props.set(key,value);
  next.sheet.meta=first.sheet.meta.map(m=>new Metadata(next.sheet,m.row,m.key,m.value));
  assert.equal(confirm(next,saved.nonce).status,"DONE");assert.equal(next.queue().length,2);
});
test("retention removes only old review sessions, preserving other properties",()=>{
  const f=setup(),nonce="a".repeat(24);
  f.props.set(prefix+nonce,JSON.stringify({v:1,nonce,created:Date.now()-8*86400000}));
  f.props.set("UNRELATED_SETTING","keep");
  f.context.EM_tgPulisci_(f.context.PropertiesService.getScriptProperties());
  assert(!f.props.has(prefix+nonce));assert.equal(f.props.get("UNRELATED_SETTING"),"keep");
});
test("legacy text-only alerts gain buttons on the next scan",()=>{
  const f=fixture(undefined,account("new","22/11/2026"));
  const reg=f.reg(3,true),result=f.direct();
  reg.metadata.data.avviso=result.contesto;reg.metadata.item.setValue(JSON.stringify(reg.metadata.data));
  f.run();assert(session(f));assert(f.telegramCalls.some(c=>c.method==="sendMessage"&&c.payload.reply_markup));
});
test("a case decided outside Telegram cannot be overwritten by an old button",()=>{
  const f=setup(),s=choose(f,"n");
  f.context.decidiOmonimo_("Sisal Sport",3,"USA_EMAIL","manual@example.test");
  click(f,"c:"+s.selection.token,s.nonce);
  assert.equal(decision(f).email,"manual@example.test");assert.equal(f.queue().length,1);
});
test("the Banco hook is unique and routes before the existing menu handler",()=>{
  const h=JSON.parse(fs.readFileSync(path.join(__dirname,"..","ops","apps-script","banco-omonimi-hook.json")));
  assert(h.insert.includes("EM_gestisciCallbackOmonimo_(update)"));
  const input="function doPost(e) {\n  const update=e;\n"+h.marker+"\n  if (bancoGestisciUpdate(update)) return rispostaOK();\n}";
  assert.equal(input.split(h.marker).length,2);
  const patched=input.replace(h.marker,h.insert+h.marker);
  assert(patched.indexOf("EM_gestisciCallbackOmonimo_")<patched.indexOf("bancoGestisciUpdate(update)"));
  new(require("node:vm").Script)(patched);
});

test("a changed candidate refreshes a failed application instead of reviving the old choice",()=>{
  const f=setup(),original=f.context.EM_accodaCreazioneMail;
  f.context.EM_accodaCreazioneMail=()=>{throw Error("transient");};
  choose(f,"n");const old=confirm(f);assert.equal(old.status,"APPLYING");
  f.context.EM_accodaCreazioneMail=original;
  f.sheet.cells[1][3]="changed@example.test";
  assert.equal(f.run().stato,"AMBIGUA");
  assert.equal(session(f,old.nonce).status,"STALE");
  assert.notEqual(session(f).nonce,old.nonce);assert.equal(f.queue().length,1);
});
test("metadata-save failure can retry before applying any mail",()=>{
  const f=setup(),item=f.sheet.meta.find(m=>m.row===3),save=item.setValue.bind(item);let fail=true;
  item.setValue=value=>{if(fail&&JSON.parse(value).decisione){fail=false;throw Error("storage");}return save(value);};
  choose(f);assert.equal(confirm(f).status,"APPLYING");
  assert.equal(f.sheet.cells[2][3],"");
  assert.equal(confirm(f).status,"DONE");assert.equal(f.sheet.cells[2][3],"old@example.test");
});
test("addresses exceeding email length limits are never offered as buttons",()=>{
  const f=setup(account("old","01/11/2026","x".repeat(260)+"@example.test"));
  const view=f.telegramCalls.find(c=>c.method==="sendMessage").payload;
  assert.equal(view.reply_markup.inline_keyboard.filter(r=>r[0].callback_data.includes(":s:")).length,0);
  assert(view.text.length<4096);immutable(f);
});
test("long Unicode names cannot overflow the durable session or Telegram text",()=>{
  const name="à".repeat(500),f=fixture(account("old","01/11/2026","old@example.test",name),
    account("new","22/11/2026","",name));
  f.run();const s=session(f);
  assert(Buffer.byteLength(f.props.get(prefix+s.nonce))<8000);
  assert(f.notifications[0].length<4096);
  choose(f);assert.equal(confirm(f).status,"DONE");
});
test("a row edited while the index is read cannot receive the old email",()=>{
  const f=setup();choose(f);
  const original=f.context.EM_costruisciIndiceEmail;
  f.context.EM_costruisciIndiceEmail=props=>{
    const index=original(props);f.sheet.cells[2][2]="edited-during-confirmation";return index;
  };
  confirm(f);assert.equal(f.sheet.cells[2][3],"");assert.equal(f.queue().length,1);
});
test("a successful decision refreshes account views once",()=>{
  const f=setup();let invalidations=0;f.context.bancoInvalidate_=()=>invalidations++;
  choose(f);confirm(f);confirm(f);
  assert.equal(invalidations,1);assert.equal(session(f).status,"DONE");
});


for (const status of ["CREATA","ANNULLATA"]) test("the result explains an existing "+status+" request without creating another",()=>{
  const f=setup();
  f.context.EM_accodaCreazioneMail({getProperty:k=>f.props.get(k)},"main","Sisal Sport",3,4,"Mario Rossi");
  f.queue()[1][3]=status;
  choose(f,"n");const s=confirm(f);
  assert.equal(s.status,"DONE");assert.equal(s.requestStatus,status);assert.equal(f.queue().length,2);
  assert(edits(f).at(-1).payload.text.includes(status==="CREATA"?"già una richiesta completata":"va ripresa"));
});

process.stdout.write(passed+" Telegram homonym regression cases passed.\n");
