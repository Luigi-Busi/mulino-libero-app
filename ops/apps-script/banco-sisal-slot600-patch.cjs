"use strict";
// Apply to a freshly read Codice.gs; never replace the private full project.
function applySisalSlot600(source) {
  let text = source.replace(/\r\n/g, '\n');
  function once(from, to) {
    if (text.split(from).length !== 2) throw Error('Banco source differs from reviewed baseline: ' + from.slice(0, 60));
    text = text.replace(from, to);
  }
  once('function interpretaMessaggio(\n',
    'function bancoSisalSlot600_(header) {\n' +
    '  return /^(?:sisal600|sisalslot600)$/.test(compatta(header));\n}\n\nfunction interpretaMessaggio(\n');
  once('  let sito =\n    null;',
    '  let sito =\n    bancoSisalSlot600_(righe[0]) ? "Sisal Slot 600" : null;');
  once('      primaRiga.includes(\n', '      sito === null && primaRiga.includes(\n');
  once('  "Sisal Sport": {\n',
    '  "Sisal Slot 600": {\n    spreadsheetProperty: "SPREADSHEET_ID",\n' +
    '    foglio: "Sisal Slot 600",\n    tipo: "standard"\n  },\n\n  "Sisal Sport": {\n');
  once('const SITI_EMAIL_MATCHER = [\n', 'const SITI_EMAIL_MATCHER = [\n  "Sisal Slot 600",\n');
  once('  const sitiDaTestare = [\n', '  const sitiDaTestare = [\n    "Sisal Slot 600",\n');
  once('Usa PokerStars, Sisal Sport, MyLotteriesPlay oppure Bet365.',
    'Usa PokerStars, Sisal Sport, Sisal Slot 600, MyLotteriesPlay oppure Bet365.');
  once("const BANCO_MENU_VERSION = '1.2.1';", "const BANCO_MENU_VERSION = '1.2.2';");
  once("['Sisal Sport','PokerStars'].indexOf(sheet.getName())", "['Sisal Sport','Sisal Slot 600','PokerStars'].indexOf(sheet.getName())");
  once("item.name==='Sisal Sport'?'sisal'", "['Sisal Sport','Sisal Slot 600'].includes(item.name)?'sisal'");
  once("['Sisal Sport','PokerStars'].map(n=>", "['Sisal Sport','Sisal Slot 600','PokerStars'].map(n=>");
  return text;
}
module.exports = {applySisalSlot600};
