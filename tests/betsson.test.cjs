const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const {applyBetflag}=require('../ops/apps-script/banco-betflag-patch.cjs');
const {applyBetsson}=require('../ops/apps-script/banco-betsson-patch.cjs');
const baseline=applyBetflag(fs.readFileSync(path.join(__dirname,'fixtures/banco-betflag-baseline.gs'),'utf8'));
const patched=applyBetsson(baseline);
const source=process.env.BETSSON_BANCO_TEST_SOURCE?fs.readFileSync(process.env.BETSSON_BANCO_TEST_SOURCE,'utf8'):patched;
const c=vm.createContext({console});vm.runInContext(source,c);
let count=0;
function test(name,fn){fn();count++;console.log('ok - '+name);}
const message=(header='Betsson🎰')=>`${header}\nNome e Cognome: Persona Test\n\nUsername: fixture.user\nPassword: fake:password`;
function parse(text){const d=c.interpretaMessaggio(text);c.validaDatiAccount(d);return d;}
for(const title of ['Betsson🎰','BETSSON 🎰','🎰 Betsson','**Betsson🎰**'])test('route '+title,()=>{
 const d=parse(message(title));assert.equal(d.sito,'Betsson');assert.equal(d.nome,'Persona Test');assert.equal(d.username,'fixture.user');assert.equal(d.password,'fake:password');
});
test('unrecognized variant is not silently inserted as Betsson',()=>assert.notEqual(c.interpretaMessaggio(message('Betsson 600🎰')).sito,'Betsson'));
for(const [name,text]of [
 ['empty name',message().replace('Persona Test','')],['empty username',message().replace('fixture.user','')],
 ['empty password',message().replace('fake:password','')],['duplicate name',message()+'\nNome: Altro Nome'],
 ['duplicate username',message()+'\nUsername: other'],['duplicate password',message()+'\nPassword: other']
])test('reject '+name,()=>assert.throws(()=>parse(text)));
test('earlier routes retain their behavior',()=>{
 assert.equal(c.interpretaMessaggio('SISAL 600 🎰').sito,'Sisal Slot 600');assert.equal(c.interpretaMessaggio('SISAL 🎰').sito,'Sisal Sport');
 assert.equal(c.interpretaMessaggio('Betflag🎰').sito,'Betflag');assert.equal(c.interpretaMessaggio('POKERSTARS').sito,'PokerStars');
});
test('destination and matcher configuration',()=>{
 const cfg=vm.runInContext('CONFIG_SITI.Betsson',c);assert.equal(cfg.foglio,'Betsson');assert.equal(cfg.tipo,'standard');assert.equal(cfg.spreadsheetProperty,'SPREADSHEET_ID');
 assert(vm.runInContext('SITI_EMAIL_MATCHER.includes("Betsson")',c));assert(source.includes("'Betflag','Betsson'].indexOf(sheet.getName())"));
});
const headers=['Data Apertura','Diffida','Nome Cognome','Username','Password','E-mail','Password E-mail','Provenienza','Netto Bonus 1','Totale'];
const cells=Array.from({length:10},()=>Array(10).fill(''));cells[8]=headers.slice();cells[9][1]='kept-diffida';cells[9][5]='kept@example.test';cells[9][6]='kept-mail-password';cells[9][8]='kept-bonus';
const writes=[];
const sheet={getName:()=> 'Betsson',getMaxRows:()=>1001,getLastRow:()=>10,getLastColumn:()=>10,getRange:(row,col,h=1,w=1)=>({
 getDisplayValues:()=>Array.from({length:h},(_,i)=>Array.from({length:w},(_,j)=>cells[row+i-1]?.[col+j-1]||'')),
 setValue(v){writes.push([row,col,v]);cells[row-1]||=[];cells[row-1][col-1]=v;return this;},setNumberFormat(){return this;}
})};
const layout=c.trovaIntestazioni(sheet,'standard'),date=new Date('2026-11-15T12:00:00Z');c.dataOggiItalia=()=>date;
test('real row-nine layout maps correct columns',()=>{assert.equal(layout.riga,9);assert.equal(layout.colonne.nome,3);assert.equal(layout.colonne.username,4);assert.equal(layout.colonne.password,5);assert.equal(layout.colonne.provenienza,8);});
test('standard insertion writes only requested account fields and date',()=>{
 c.scriviRiga(sheet,10,layout,parse(message()),'Fixture Origin','standard',true);
 assert.deepEqual(writes.map(w=>w[1]),[3,4,5,8,1]);assert.equal(cells[9][2],'Persona Test');assert.equal(cells[9][3],'fixture.user');assert.equal(cells[9][4],'fake:password');
 assert.equal(cells[9][1],'kept-diffida');assert.equal(cells[9][5],'kept@example.test');assert.equal(cells[9][6],'kept-mail-password');assert.equal(cells[9][8],'kept-bonus');assert.equal(cells[9][0],date);
});
test('existing duplicate protection includes Betsson as a standard site',()=>assert.equal(c.trovaAccountDuplicato(sheet,layout,parse(message()),'standard',null).riga,10));
test('correction preserves original date and email columns',()=>{
 const props={getProperty:()=>JSON.stringify({sito:'Betsson',foglio:'Betsson',tipo:'standard',riga:10,timestamp:Date.now()}),deleteProperty(){}};
 c.UTENTI={'11':'Fixture Origin'};const author=vm.runInContext('Object.keys(UTENTI)[0]',c);
 c.trovaFoglio=()=>sheet;c.correzioneScaduta=()=>false;c.trovaAccountDuplicato=()=>null;c.trovaPossibileDuplicato=()=>null;
 c.LockService={getScriptLock:()=>({tryLock:()=>true,releaseLock(){}})};c.SpreadsheetApp={flush(){}};
 c.inviaTelegram=()=>1;c.sostituisciUltimoMessaggioAccount=()=>{};
 c.correggiUltimo({},props,author,11,1,parse(message().replace('fixture.user','corrected.user')),{tipo:'standard'});
 assert.equal(cells[9][3],'corrected.user');assert.equal(cells[9][0],date);assert.equal(cells[9][5],'kept@example.test');assert.equal(cells[9][6],'kept-mail-password');
});
test('complete insertion preserves provenance and invokes matcher once',()=>{
 const propsMap=new Map([['SPREADSHEET_ID','fixture-main']]),calls=[];c.PropertiesService={getScriptProperties:()=>({getProperty:k=>propsMap.get(k)||null,setProperty:(k,v)=>propsMap.set(k,v)})};
 c.SpreadsheetApp={openById:()=>({}),flush(){}};c.impostaFusoOrarioItaliano=()=>{};c.trovaPrimaRigaLibera=()=>10;
 c.avviaEmailMatcherNuovoAccount=(...a)=>calls.push(a);c.registraNuovoMessaggioAccount=()=>{};c.notificaAdminNuovoAccount=()=>{};
 const author=vm.runInContext('Object.keys(UTENTI)[0]',c),origin=vm.runInContext('UTENTI[Object.keys(UTENTI)[0]]',c);
 c.gestisciInserimento(11,author,1,message(),Math.floor(Date.now()/1000));
 assert.equal(cells[9][7],origin);assert.deepEqual(calls,[['Betsson',10]]);assert(propsMap.has('LAST_'+author));
});
test('patch rejects replay and unexpected baseline',()=>assert.throws(()=>applyBetsson(patched)));
const {fixture,account}=require('./emailmatcher.test.cjs');
const row=(email='',name='Persona Betsson')=>['15/11/2026','',name,'bs-fixture','unused',email,'','Fixture Origin','',''];
function addBetsson(f,rows){const s=f.books.get('main').getSheetByName('Betsson');s.cells=[...Array.from({length:8},()=>[]),headers.slice(),...rows];return s;}
test('missing mail queues the correct F destination idempotently',()=>{
 const f=fixture(null,account('other','01/11/2026','','Altra Persona'));const s=addBetsson(f,[row()]);
 assert.equal(f.context.completaEmailRiga('Betsson',10).stato,'ACCODATA_CREAZIONE');assert.equal(f.queue()[1][5],'Betsson');assert.equal(Number(f.queue()[1][7]),6);assert(f.queue()[1][17]);
 f.context.completaEmailRiga('Betsson',10);assert.equal(f.queue().length,2);assert.equal(s.cells[9][5],'');
});
test('existing mail from another operator is added to Betsson F',()=>{
 const f=fixture(account('sport','01/11/2026','existing@example.test'),account('other','01/11/2026','','Altra Persona'));const s=addBetsson(f,[row('','Mario Rossi')]);
 assert.equal(f.context.completaEmailRiga('Betsson',10).stato,'TROVATA');assert.equal(s.cells[9][5],'existing@example.test');assert.equal(f.queue().length,1);
});
test('Betsson mail is searchable for another insertion',()=>{
 const f=fixture(null,account('sport'));addBetsson(f,[row('betsson@example.test','Mario Rossi')]);assert.equal(f.run().stato,'TROVATA');assert.equal(f.sheet.cells.at(-1)[3],'betsson@example.test');
});
test('same-site homonym requires review without unconfirmed temporal inference',()=>{
 const f=fixture(null,account('other','01/11/2026','','Altra Persona'));const s=addBetsson(f,[row('prior@example.test'),row()]);s.cells[10][3]='different-user';
 assert.equal(f.context.completaEmailRiga('Betsson',11).stato,'AMBIGUA');assert.equal(f.queue().length,1);assert.equal(s.cells[10][5],'');
});
console.log(count+' Betsson regression cases passed.');
