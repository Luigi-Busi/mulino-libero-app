// Betflag uses its own validated layout; no bank/card details in notices or logs.
function bancoInterpretaBetflag_(righe) {
  const dati = {sito:'Betflag',nome:'',username:'',password:'',iban:'',carta:'',identita:'',occorrenze:{}};
  const fields = {
    'nome e cognome':'nome','nome cognome':'nome','nome cliente':'nome','nome':'nome',
    'username':'username','user':'username','nome utente':'username',
    'password':'password','pass':'password','iban':'iban',
    'spid cieid':'identita','spid':'identita','cieid':'identita',
    '16 cifre pp':'carta','16 cifre postepay':'carta'
  };
  for (const line of righe.slice(1)) {
    const pos = line.indexOf(':');
    if (pos < 0) continue;
    const field = fields[normalizza(line.slice(0,pos))];
    if (!field) continue;
    dati.occorrenze[field] = (dati.occorrenze[field] || 0) + 1;
    dati[field] = line.slice(pos+1).trim();
  }
  return dati;
}

function bancoValidaBetflag_(dati) {
  for (const field of ['nome','username','password','iban']) {
    if (!String(dati[field] || '').trim()) throw Error('Betflag: campo mancante: ' + field);
    if (dati.occorrenze[field] !== 1) throw Error('Betflag: campo ripetuto: ' + field);
  }
  if (dati.nome.length < 2) throw Error('Betflag: nome troppo corto.');
  if (dati.occorrenze.identita) {
    if (dati.occorrenze.identita !== 1 || dati.occorrenze.carta) {
      throw Error('Betflag: usa un solo formato, SPID/CIEID oppure 16 cifre pp.');
    }
    const identity = normalizza(dati.identita);
    if (!['spid','cieid'].includes(identity)) throw Error('Betflag: indica SPID oppure CIEID.');
    dati.tipologia = identity;
    dati.carta = '//';
  } else {
    if (dati.occorrenze.carta !== 1 || !/^\d{16}$/.test(String(dati.carta).replace(/\s/g,''))) {
      throw Error('Betflag: inserisci una sola riga con le 16 cifre pp.');
    }
    dati.tipologia = 'Normie';
  }
}

function bancoIntestazioniBetflag_(sheet) {
  const expected = [
    ['data registrazione'],['nome e cognome','nome cognome'],['username'],['password'],
    ['e mail'],['pass e mail','password e mail'],['iban pp'],['16 cifre postepay'],['tipologia'],['provenienza']
  ];
  const rows = sheet.getRange(1,1,Math.min(100,sheet.getMaxRows()),10).getDisplayValues();
  const matches=[];
  rows.forEach(function(row,i) {
    if (expected.every(function(aliases,j) {return aliases.includes(normalizza(row[j]));})) matches.push(i+1);
  });
  if (matches.length !== 1) throw Error('Betflag: intestazioni mancanti, spostate o duplicate; nessun dato scritto.');
  return {riga:matches[0],colonne:{data:1,nome:2,username:3,password:4,email:5,passwordEmail:6,iban:7,carta:8,tipologia:9,provenienza:10}};
}

function bancoDataRicezioneBetflag_(seconds) {
  if (!Number.isSafeInteger(seconds) || seconds <= 0) throw Error('Betflag: data del messaggio non disponibile.');
  const parts = Utilities.formatDate(new Date(seconds * 1000),'Europe/Rome','yyyy-MM-dd').split('-');
  return new Date(Date.UTC(Number(parts[0]),Number(parts[1])-1,Number(parts[2]),12,0,0));
}

function bancoTestoBetflag_(value) {
  const text=String(value);
  return text.startsWith('=') ? "'" + text : text;
}

function bancoScriviBetflag_(sheet,row,layout,dati,provenienza,insertDate) {
  // Validate before the first cell write, including direct/manual calls.
  bancoValidaBetflag_(dati);
  if (insertDate && (!(dati.dataRicezione instanceof Date) || !Number.isFinite(dati.dataRicezione.getTime()))) {
    throw Error('Betflag: data di ricezione mancante.');
  }
  sheet.getRange(row,2,1,3).setNumberFormat('@').setValues([
    [dati.nome,dati.username,dati.password].map(bancoTestoBetflag_)
  ]);
  sheet.getRange(row,7,1,4).setNumberFormat('@').setValues([
    [dati.iban,dati.carta,dati.tipologia,provenienza].map(bancoTestoBetflag_)
  ]);
  if (insertDate) sheet.getRange(row,1).setValue(dati.dataRicezione).setNumberFormat('dd/MM/yyyy');
}
