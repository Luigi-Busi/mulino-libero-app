const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const {applySisalSlot600}=require('../ops/apps-script/banco-sisal-slot600-patch.cjs');
const baseline=fs.readFileSync(path.join(__dirname,'fixtures/banco-sisal-baseline.gs'),'utf8');
const patched=applySisalSlot600(baseline);
const banco=process.env.BANCO_TEST_SOURCE?fs.readFileSync(process.env.BANCO_TEST_SOURCE,'utf8'):patched;
const ctx=vm.createContext({console}); vm.runInContext(banco,ctx);
let count=0;
function check(name,fn){fn();count++;console.log('ok - '+name);}
for(const header of ['SISAL 600 🎰','🎰 SISAL 600','sisal 600 🎰','**SISAL 600 🎰**','SISAL SLOT 600 🎰'])
  check(header,()=>assert.equal(ctx.interpretaMessaggio(header+'\nNome: Persona Test\nUsername: fixture\nPassword: fake').sito,'Sisal Slot 600'));
for(const header of ['SISAL 🎰','SISAL SPORT','SISAL 6000 🎰','SISAL 1600 🎰'])
  check('existing/other title: '+header,()=>assert.equal(ctx.interpretaMessaggio(header).sito,'Sisal Sport'));
check('other operator untouched',()=>assert.equal(ctx.interpretaMessaggio('POKERSTARS').sito,'PokerStars'));
check('target, matcher and menu config',()=>{
  const cfg=vm.runInContext('CONFIG_SITI["Sisal Slot 600"]',ctx);
  assert.equal(cfg.foglio,'Sisal Slot 600');assert.equal(cfg.spreadsheetProperty,'SPREADSHEET_ID');assert.equal(cfg.tipo,'standard');
  assert(vm.runInContext('SITI_EMAIL_MATCHER.includes("Sisal Slot 600")',ctx));
  assert(banco.includes("['Sisal Sport','Sisal Slot 600','PokerStars'].indexOf(sheet.getName())"));
  assert(banco.includes("['Sisal Sport','Sisal Slot 600'].includes(item.name)?'sisal'"));
});
const slotHeaders=['Data Apertura','Chiusura','Diffida','Nome Cognome','Username','Password','E-mail','Password E-mail','Provenienza'];
const writes=[];
const sheet={getName:()=> 'Sisal Slot 600',getMaxRows:()=>1000,getLastColumn:()=>9,getRange:(row,col,h,w)=>({
  getDisplayValues:()=>Array.from({length:h},(_,i)=>row+i===9?slotHeaders:Array(w).fill('')),
  setValue(v){writes.push({row,col,v});return this;},setNumberFormat(){return this;}
})};
check('real row-nine layout and insertion leave mail for matcher',()=>{
  const layout=ctx.trovaIntestazioniStandard(sheet);assert.equal(layout.riga,9);
  assert.equal(layout.colonne.nome,4);assert.equal(layout.colonne.username,5);
  ctx.dataOggiItalia=()=> '15/11/2026';
  ctx.scriviRiga(sheet,10,layout,{nome:'Persona Test',username:'fixture',password:'fake'},'fixture','standard',true);
  assert.deepEqual(writes.map(x=>x.col),[4,5,6,9,1]);assert(writes.every(x=>x.row===10));
});
check('patch rejects replay and unexpected source',()=>{
  assert.throws(()=>applySisalSlot600(patched));
  assert.throws(()=>applySisalSlot600(baseline.replace('const SITI_EMAIL_MATCHER = [','const SITI_EMAIL_MATCHER = [];//')));
});

const {fixture,account}=require('./emailmatcher.test.cjs');
function addSlot(f,rows){const s=f.books.get('main').getSheetByName('Sisal Slot 600');s.cells=[...Array.from({length:8},()=>[]),slotHeaders.slice(),...rows];return s;}
function slotRow(username,date='01/11/2026',email='',name='Mario Rossi'){return [date,'','',name,username,'unused',email,'','fixture'];}
check('new slot row queues mail with stable identity and correct real columns',()=>{
  const f=fixture(null,account('sport','01/11/2026','','Altra Persona'));const s=addSlot(f,[slotRow('slot')]);
  assert.equal(f.context.completaEmailRiga('Sisal Slot 600',10).stato,'ACCODATA_CREAZIONE');
  assert.equal(f.queue()[1][5],'Sisal Slot 600');assert.equal(Number(f.queue()[1][6]),10);assert.equal(Number(f.queue()[1][7]),7);
  assert(f.queue()[1][17]);assert.equal(s.cells[9][6],'');
  f.context.completaEmailRiga('Sisal Slot 600',10);assert.equal(f.queue().length,2);
});
check('slot receives an existing mail from another sheet',()=>{
  const f=fixture(account('sport','01/11/2026','sport@example.test'),account('other','01/11/2026','','Altra Persona'));
  const s=addSlot(f,[slotRow('slot')]);assert.equal(f.context.completaEmailRiga('Sisal Slot 600',10).stato,'TROVATA');
  assert.equal(s.cells[9][6],'sport@example.test');assert.equal(f.queue().length,1);
});
check('slot mail is searched for later insertions into other sheets',()=>{
  const f=fixture(null,account('sport'));addSlot(f,[slotRow('slot','01/11/2026','slot@example.test')]);
  assert.equal(f.run().stato,'TROVATA');assert.equal(f.sheet.cells.at(-1)[3],'slot@example.test');
});
check('same slot names within 20 days create a separate mail',()=>{
  const f=fixture(null,account('other','01/11/2026','','Altra Persona'));
  const s=addSlot(f,[slotRow('slotold','01/11/2026','old@example.test'),slotRow('slotnew','21/11/2026')]);
  assert.equal(f.context.completaEmailRiga('Sisal Slot 600',11).stato,'ACCODATA_CREAZIONE');assert.equal(s.cells[10][6],'');
});
check('same slot names beyond 20 days require review',()=>{
  const f=fixture(null,account('other','01/11/2026','','Altra Persona'));
  const s=addSlot(f,[slotRow('slotold','01/11/2026','old@example.test'),slotRow('slotnew','22/11/2026')]);
  assert.equal(f.context.completaEmailRiga('Sisal Slot 600',11).stato,'AMBIGUA');assert.equal(f.queue().length,1);assert.equal(s.cells[10][6],'');
});
console.log(count+' Sisal Slot 600 regression cases passed.');
