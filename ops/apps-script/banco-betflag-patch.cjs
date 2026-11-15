"use strict";
const fs=require('node:fs'),path=require('node:path');
function applyBetflag(source) {
  let text=source.replace(/\r\n/g,'\n');
  function once(from,to) {
    if(text.split(from).length!==2)throw Error('Banco baseline differs: '+from.slice(0,60));
    text=text.replace(from,to);
  }
  once('bancoSisalSlot600_(righe[0]) ? "Sisal Slot 600" : null;',
    'compatta(righe[0]) === "betflag" ? "Betflag" : bancoSisalSlot600_(righe[0]) ? "Sisal Slot 600" : null;');
  once('  const dati = {\n\n    sito:', '  if (sito === "Betflag") return bancoInterpretaBetflag_(righe);\n\n  const dati = {\n\n    sito:');
  once('function validaDatiAccount(\n  dati\n) {','function validaDatiAccount(\n  dati\n) {\n  if (dati.sito === "Betflag") return bancoValidaBetflag_(dati);');
  once('  "Sisal Slot 600": {\n','  "Betflag": {spreadsheetProperty:"SPREADSHEET_ID",foglio:"Betflag",tipo:"betflag"},\n\n  "Sisal Slot 600": {\n');
  once('const SITI_EMAIL_MATCHER = [\n','const SITI_EMAIL_MATCHER = [\n  "Betflag",\n');
  once('  const sitiDaTestare = [\n','  const sitiDaTestare = [\n    "Betflag",\n');
  once('Usa PokerStars, Sisal Sport, Sisal Slot 600, MyLotteriesPlay oppure Bet365.',
    'Usa PokerStars, Sisal Sport, Sisal Slot 600, Betflag, MyLotteriesPlay oppure Bet365.');
  once('function trovaIntestazioni(\n  foglio,\n  tipo\n) {',
    'function trovaIntestazioni(\n  foglio,\n  tipo\n) {\n  if (tipo === "betflag") return bancoIntestazioniBetflag_(foglio);');
  once('  inserisciDataApertura\n) {',
    '  inserisciDataApertura\n) {\n  if (tipo === "betflag") return bancoScriviBetflag_(foglio,riga,intestazioni,dati,provenienza,inserisciDataApertura);');
  once('  userMessageId,\n  testo\n) {','  userMessageId,\n  testo,\n  receivedAt\n) {');
  once('        userMessageId,\n        testo\n      );','        userMessageId,\n        testo,\n        message.date\n      );');
  once('  const config =\n    CONFIG_SITI[',
    '  if (dati.sito === "Betflag") dati.dataRicezione = bancoDataRicezioneBetflag_(receivedAt);\n\n  const config =\n    CONFIG_SITI[');
  once('  const tipoUltimo =\n',
    '  if (dati.sito === "Betflag" && ultimo.foglio !== "Betflag") throw Error("Betflag: gli archivi non sono modificabili.");\n\n  const tipoUltimo =\n');
  once("const BANCO_MENU_VERSION = '1.2.2';", "const BANCO_MENU_VERSION = '1.2.3';");
  once("['Sisal Sport','Sisal Slot 600','PokerStars'].indexOf(sheet.getName())", "['Sisal Sport','Sisal Slot 600','PokerStars','Betflag'].indexOf(sheet.getName())");
  once("['Sisal Sport','Sisal Slot 600','PokerStars'].map(n=>", "['Sisal Sport','Sisal Slot 600','PokerStars','Betflag'].map(n=>");
  if(text.includes('function bancoInterpretaBetflag_'))throw Error('Betflag already installed');
  return text+'\n\n'+fs.readFileSync(path.join(__dirname,'banco-betflag-helpers.gs'),'utf8').replace(/\r\n/g,'\n');
}
module.exports={applyBetflag};
