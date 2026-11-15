"use strict";
function applyBetsson(source) {
  let text=source.replace(/\r\n/g,'\n');
  function once(from,to) {
    if(text.split(from).length!==2)throw Error('Banco baseline differs: '+from.slice(0,60));
    text=text.replace(from,to);
  }
  once('compatta(righe[0]) === "betflag" ? "Betflag" :',
    'compatta(righe[0]) === "betsson" ? "Betsson" : compatta(righe[0]) === "betflag" ? "Betflag" :');
  once('  "Betflag": {spreadsheetProperty:',
    '  "Betsson": {spreadsheetProperty:"SPREADSHEET_ID",foglio:"Betsson",tipo:"standard"},\n\n  "Betflag": {spreadsheetProperty:');
  once('const SITI_EMAIL_MATCHER = [\n','const SITI_EMAIL_MATCHER = [\n  "Betsson",\n');
  once('  const sitiDaTestare = [\n','  const sitiDaTestare = [\n    "Betsson",\n');
  once('Sisal Slot 600, Betflag, MyLotteriesPlay oppure Bet365.',
    'Sisal Slot 600, Betflag, Betsson, MyLotteriesPlay oppure Bet365.');
  once("const BANCO_MENU_VERSION = '1.2.3';", "const BANCO_MENU_VERSION = '1.2.4';");
  once("['Sisal Sport','Sisal Slot 600','PokerStars','Betflag'].indexOf(sheet.getName())",
    "['Sisal Sport','Sisal Slot 600','PokerStars','Betflag','Betsson'].indexOf(sheet.getName())");
  once("['Sisal Sport','Sisal Slot 600','PokerStars','Betflag'].map(n=>",
    "['Sisal Sport','Sisal Slot 600','PokerStars','Betflag','Betsson'].map(n=>");
  return text;
}
module.exports={applyBetsson};
