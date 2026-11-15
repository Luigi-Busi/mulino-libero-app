const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const {applyBetflag}=require('../ops/apps-script/banco-betflag-patch.cjs');
const baseline=fs.readFileSync(path.join(__dirname,'fixtures/banco-betflag-baseline.gs'),'utf8');
const patched=applyBetflag(baseline);
const source=process.env.BETFLAG_BANCO_TEST_SOURCE?fs.readFileSync(process.env.BETFLAG_BANCO_TEST_SOURCE,'utf8'):patched;
const c=vm.createContext({console});vm.runInContext(source,c);
const originalInsert=c.gestisciInserimento;
c.Utilities={formatDate:(d,tz)=>new Intl.DateTimeFormat('sv-SE',{timeZone:tz,year:'numeric',month:'2-digit',day:'2-digit'}).format(d)};
let count=0;
function test(name,fn){fn();count++;console.log('ok - '+name);}
const pp='0000123412341234',iban='IT00TEST0000000000000000000';
const identity=(v='SPID')=>`Betflag🎰\nNome e Cognome: Persona Test\nSPID/CIEID?: ${v}\nIban: ${iban}\nUsername: fixture\nPassword: dummy:password`;
const normie=()=>`Betflag🎰\nNome cliente: Persona Test\nUsername: fixture\nPassword: dummy\nIban: ${iban}\n16 cifre pp: ${pp}`;
function parse(text){const d=c.interpretaMessaggio(text);c.validaDatiAccount(d);return d;}
for(const v of ['SPID','spid','CIEID','cieid'])test('identity '+v,()=>{const d=parse(identity(v));assert.equal(d.tipologia,v.toLowerCase());assert.equal(d.carta,'//');assert.equal(d.password,'dummy:password');});
test('Normie and leading-zero card are preserved',()=>{const d=parse(normie());assert.equal(d.nome,'Persona Test');assert.equal(d.tipologia,'Normie');assert.equal(d.carta,pp);assert.equal(typeof d.carta,'string');});
test('formatted card is stored as supplied',()=>assert.equal(parse(normie().replace(pp,'0000 1234 1234 1234')).carta,'0000 1234 1234 1234'));
for(const h of ['BETFLAG 🎰','**Betflag🎰**','🎰 Betflag'])test('title '+h,()=>assert.equal(parse(normie().replace('Betflag🎰',h)).sito,'Betflag'));
for(const h of ['Betflag Grandi🎰','Betflag Luigi','Betflag Normie','Betflag Davide'])test('not an insertion target: '+h,()=>assert.notEqual(c.interpretaMessaggio(h).sito,'Betflag'));
const invalid=[
 ['missing identity',identity('')],['ambiguous identity',identity('SPID/CIEID')],['unknown identity',identity('altro')],
 ['mixed templates',identity()+'\n16 cifre pp: '+pp],['duplicate identity',identity()+'\nSPID/CIEID?: SPID'],
 ['duplicate card',normie()+'\n16 cifre pp: '+pp],['short card',normie().replace(pp,'0000')],
 ['non-digit card',normie().replace(pp,'not-a-card')],['missing IBAN',normie().replace(iban,'')],
 ['duplicate name alias',normie()+'\nNome e Cognome: Altro Nome'],['missing password',normie().replace('Password: dummy','Password:')]
];
for(const [name,text]of invalid)test('reject '+name,()=>assert.throws(()=>parse(text),/Betflag/));
const headers=['Data Registrazione','Nome e Cognome','Username','Password','E-mail','Pass E-mail','Iban PP','16 cifre postepay','Tipologia','Provenienza'];
const cells=Array.from({length:12},()=>Array(14).fill(''));cells[10]=headers.slice();cells[11][4]='kept@example.test';cells[11][5]='mail-password';cells[11][10]='bonus-kept';
const writes=[],formats=[];
const sheet={getName:()=> 'Betflag',getMaxRows:()=>1000,getLastRow:()=>12,getLastColumn:()=>14,
 getRange:(row,col,h=1,w=1)=>({getDisplayValues:()=>Array.from({length:h},(_,i)=>Array.from({length:w},(_,j)=>cells[row+i-1]?.[col+j-1]||'')),
 setNumberFormat(f){formats.push([row,col,w,f]);return this;},setValues(values){writes.push([row,col,values]);values.forEach((r,i)=>r.forEach((v,j)=>{cells[row+i-1]||=[];cells[row+i-1][col+j-1]=v;}));return this;},
 setValue(v){return this.setValues([[v]]);}})};
const received=Math.floor(Date.UTC(2026,10,14,23,30)/1000);
test('receipt date uses message time in Rome across midnight',()=>{const d=c.bancoDataRicezioneBetflag_(received);assert.equal(d.toISOString(),'2026-11-15T12:00:00.000Z');});
test('missing receipt timestamp is rejected',()=>assert.throws(()=>c.bancoDataRicezioneBetflag_(undefined),/data/));
const layout=c.trovaIntestazioni(sheet,'betflag');
test('actual row eleven layout is verified',()=>{assert.equal(layout.riga,11);assert.equal(layout.colonne.email,5);assert.equal(layout.colonne.provenienza,10);});
test('SPID writes requested columns and preserves email/password/bonus',()=>{
 const d=parse(identity());d.dataRicezione=c.bancoDataRicezioneBetflag_(received);c.scriviRiga(sheet,12,layout,d,'Fixture Origin','betflag',true);
 assert.equal(cells[11][1],'Persona Test');assert.equal(cells[11][2],'fixture');assert.equal(cells[11][3],'dummy:password');
 assert.equal(cells[11][6],iban);assert.equal(cells[11][7],'//');assert.equal(cells[11][8],'spid');assert.equal(cells[11][9],'Fixture Origin');
 assert.equal(cells[11][4],'kept@example.test');assert.equal(cells[11][5],'mail-password');assert.equal(cells[11][10],'bonus-kept');
 assert.equal(cells[11][0].toISOString(),'2026-11-15T12:00:00.000Z');
});
test('correction to Normie overwrites identification but preserves original date',()=>{
 const originalDate=cells[11][0];const d=parse(normie());c.scriviRiga(sheet,12,layout,d,'Fixture Origin','betflag',false);
 assert.equal(cells[11][7],pp);assert.equal(cells[11][8],'Normie');assert.equal(cells[11][0],originalDate);
 assert(formats.some(x=>x[1]===7&&x[3]==='@'));
});
test('correction back to CIEID clears the old card',()=>{c.scriviRiga(sheet,12,layout,parse(identity('CIEID')),'Fixture Origin','betflag',false);assert.equal(cells[11][7],'//');assert.equal(cells[11][8],'cieid');});
test('invalid data never partially writes',()=>{const before=writes.length;assert.throws(()=>c.scriviRiga(sheet,12,layout,c.interpretaMessaggio(identity('bad')),'fixture','betflag',true));assert.equal(writes.length,before);});
test('moved headers are rejected before any write',()=>{cells[10][7]='Unexpected';assert.throws(()=>c.trovaIntestazioni(sheet,'betflag'));cells[10][7]=headers[7];});
test('webhook forwards reception timestamp and retains routing protection',()=>{
 let args;c.bancoGestisciUpdate=()=>false;c.EM_gestisciCallbackOmonimo_=()=>false;c.bancoDashboardContext_=false;
 c.PropertiesService={getScriptProperties:()=>({getProperty:()=> 'fixture-secret'})};c.UTENTI={'11':'Fixture Origin'};
 c.prenotaUpdate=()=>true;c.inviaTelegram=()=>1;c.eliminaMessaggioTelegram=()=>{};c.rispostaOK=()=>({ok:true});
 c.gestisciInserimento=(...a)=>{args=a;};
 const author=vm.runInContext('Object.keys(UTENTI)[0]',c);
 const event={parameter:{key:'fixture-secret'},postData:{contents:JSON.stringify({update_id:1,message:{date:received,text:normie(),from:{id:Number(author)},chat:{id:11},message_id:1}})}};
 c.doPost(event);assert.equal(args[4],received);args=null;event.parameter.key='wrong';c.doPost(event);assert.equal(args,null);
});
test('archive corrections are rejected without cell writes',()=>{
 const before=writes.length;c.trovaFoglio=()=>sheet;c.correzioneScaduta=()=>false;
 const props={getProperty:()=>JSON.stringify({sito:'Betflag',foglio:'Betflag Luigi',tipo:'standard',riga:12}),deleteProperty(){}};
 assert.throws(()=>c.correggiUltimo({},props,'11',11,1,parse(identity()),{tipo:'betflag'}),/archivi/);assert.equal(writes.length,before);
});
test('patch cannot be applied twice or to stale source',()=>assert.throws(()=>applyBetflag(patched)));
test('complete insertion uses original provenance and starts EmailMatcher once',()=>{
 const propsMap=new Map([['SPREADSHEET_ID','fixture-main']]),calls=[],notices=[];
 const props={getProperty:k=>propsMap.get(k)||null,setProperty:(k,v)=>propsMap.set(k,v)};
 c.PropertiesService={getScriptProperties:()=>props};c.SpreadsheetApp={openById:()=>({}),flush(){}};
 c.impostaFusoOrarioItaliano=()=>{};c.trovaFoglio=()=>sheet;c.trovaAccountDuplicato=()=>null;c.trovaPossibileDuplicato=()=>null;c.trovaPrimaRigaLibera=()=>12;
 c.LockService={getScriptLock:()=>({tryLock:()=>true,releaseLock(){}})};
 c.avviaEmailMatcherNuovoAccount=(...args)=>calls.push(args);c.inviaTelegram=(chat,text)=>{notices.push(text);return 1;};c.registraNuovoMessaggioAccount=()=>{};c.notificaAdminNuovoAccount=()=>{};
 const author=vm.runInContext('Object.keys(UTENTI)[0]',c),origin=vm.runInContext('UTENTI[Object.keys(UTENTI)[0]]',c);
 originalInsert(11,author,1,normie(),received);
 assert.equal(cells[11][9],origin);assert.equal(cells[11][0].toISOString(),'2026-11-15T12:00:00.000Z');
 assert.deepEqual(calls,[['Betflag',12]]);assert(propsMap.has('LAST_'+author));
 assert(notices.every(t=>!t.includes(iban)&&!t.includes(pp)));
});

const {fixture,account}=require('./emailmatcher.test.cjs');
function row(name='Persona Betflag',email=''){return ['15/11/2026',name,'bf-fixture','unused',email,'',iban,pp,'Normie','Fixture Origin'];}
function addFlag(f,rows){const s=f.books.get('main').getSheetByName('Betflag');s.cells=[...Array.from({length:10},()=>[]),headers.slice(),...rows];return s;}
test('Betflag queues mail to E with stable ID and no duplicate request',()=>{
 const f=fixture(null,account('sport','01/11/2026','','Altra Persona'));const s=addFlag(f,[row()]);
 assert.equal(f.context.completaEmailRiga('Betflag',12).stato,'ACCODATA_CREAZIONE');assert.equal(f.queue()[1][5],'Betflag');assert.equal(Number(f.queue()[1][7]),5);assert(f.queue()[1][17]);
 f.context.completaEmailRiga('Betflag',12);assert.equal(f.queue().length,2);assert.equal(s.cells[11][6],iban);assert.equal(s.cells[11][7],pp);
});
test('existing unrelated operator email is added to Betflag E',()=>{
 const f=fixture(account('sport','01/11/2026','found@example.test'),account('other','01/11/2026','','Altra Persona'));const s=addFlag(f,[row('Mario Rossi')]);
 assert.equal(f.context.completaEmailRiga('Betflag',12).stato,'TROVATA');assert.equal(s.cells[11][4],'found@example.test');
});
test('Betflag is searched for other insertions',()=>{const f=fixture(null,account('sport'));addFlag(f,[row('Mario Rossi','betflag@example.test')]);assert.equal(f.run().stato,'TROVATA');assert.equal(f.sheet.cells.at(-1)[3],'betflag@example.test');});
for(const name of ['Betflag Luigi','Betflag Normie','Betflag Davide'])test('archive remains searchable and never an insertion target: '+name,()=>{
 const f=fixture(null,account('sport'));const s=f.books.get('slot').getSheetByName(name);s.cells=[['Nome e Cognome','Username','E-mail'],['Mario Rossi','legacy','legacy@example.test']];
 assert.equal(f.run().stato,'TROVATA');assert.equal(f.sheet.cells.at(-1)[3],'legacy@example.test');
 assert(!vm.runInContext('EM_TARGET_SHEETS',f.context).includes(name));assert.equal(vm.runInContext('CONFIG_SITI',c)[name],undefined);
});
test('same operator archive names trigger homonym review before reuse',()=>{
 const f=fixture(null,account('other','01/11/2026','','Altra Persona'));addFlag(f,[row('Mario Rossi')]);
 f.books.get('slot').getSheetByName('Betflag Luigi').cells=[['Nome Cognome','Username','E-mail'],['Mario Rossi','old','legacy@example.test']];
 assert.equal(f.context.completaEmailRiga('Betflag',12).stato,'AMBIGUA');assert.equal(f.queue().length,1);
});
console.log(count+' Betflag regression cases passed.');
