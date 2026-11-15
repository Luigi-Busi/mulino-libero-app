// Pure configuration/functions extracted from the verified Banco v40. No credentials or customer data.
const SITI = {

  "pokerstars": "PokerStars",

  "sisalsport": "Sisal Sport",
  "sisal": "Sisal Sport",

  "goldbet": "GoldBet",

  "mylotteriesplay": "MyLotteriesPlay",

  // SNAI
  "snaisport": "Snai Sport",
  "snai": "Snai Sport",

  "bet365": "Bet365"
};


// ============================================================
// CONFIGURAZIONE DESTINAZIONI
// ============================================================

const CONFIG_SITI = {

  "PokerStars": {

    spreadsheetProperty:
      "SPREADSHEET_ID",

    foglio:
      "PokerStars",

    tipo:
      "standard"
  },


  "Sisal Sport": {

    spreadsheetProperty:
      "SPREADSHEET_ID",

    foglio:
      "Sisal Sport",

    tipo:
      "standard"
  },


  "MyLotteriesPlay": {

    spreadsheetProperty:
      "SPREADSHEET_ID",

    foglio:
      "MyLotteriesPlay",

    tipo:
      "standard"
  },


  "Bet365": {

    spreadsheetProperty:
      "SPREADSHEET_ID_SUPPLYER",

    foglio:
      "Bet365",

    tipo:
      "bet365"
  }
};


// ============================================================
// SITI CHE USANO EMAIL MATCHER
// ============================================================

const SITI_EMAIL_MATCHER = [

  "PokerStars",
  "Sisal Sport",
  "MyLotteriesPlay"
];


// ============================================================

function normalizza(
  testo
) {

  return String(
    testo || ""
  )
    .toLowerCase()
    .normalize(
      "NFD"
    )
    .replace(
      /[\u0300-\u036f]/g,
      ""
    )
    .replace(
      /[^a-z0-9]+/g,
      " "
    )
    .trim();
}

function compatta(
  testo
) {

  return normalizza(
    testo
  )
    .replace(
      /\s+/g,
      ""
    );
}

function interpretaMessaggio(
  testo
) {

  const righe =
    String(
      testo || ""
    )
      .split(
        /\r?\n/
      )
      .map(
        function(riga) {

          return riga.trim();
        }
      )
      .filter(
        function(riga) {

          return riga !== "";
        }
      );


  if (
    righe.length === 0
  ) {

    return {};
  }


  const primaRiga =
    compatta(
      righe[0]
    );


  let sito =
    null;


  for (
    const chiave in SITI
  ) {

    if (
      primaRiga.includes(
        compatta(
          chiave
        )
      )
    ) {

      sito =
        SITI[
          chiave
        ];


      break;
    }
  }


  const dati = {

    sito:
      sito,

    nome:
      "",

    username:
      "",

    password:
      "",

    email:
      "",

    dataNascita:
      "",

    dispositivo:
      "",

    codiceFiscale:
      "",


    occorrenze: {

      nome:
        0,

      username:
        0,

      password:
        0,

      email:
        0,

      dataNascita:
        0,

      dispositivo:
        0,

      codiceFiscale:
        0
    }
  };


  // ==========================================================
  // BET365
  // ==========================================================

  if (
    sito ===
    "Bet365"
  ) {

    for (
      const riga of righe
    ) {

      const posizione =
        riga.indexOf(
          ":"
        );


      if (
        posizione === -1
      ) {

        continue;
      }


      const chiave =
        normalizza(

          riga.substring(
            0,
            posizione
          )
        );


      const valore =
        riga.substring(
          posizione + 1
        ).trim();


      if (
        chiave ===
          "nome cliente" ||

        chiave ===
          "nome e cognome" ||

        chiave ===
          "nome cognome" ||

        chiave ===
          "nome"
      ) {

        dati
          .occorrenze
          .nome++;


        dati.nome =
          valore;
      }


      else if (
        chiave ===
          "email usata" ||

        chiave ===
          "e mail usata" ||

        chiave ===
          "email" ||

        chiave ===
          "e mail"
      ) {

        dati
          .occorrenze
          .email++;


        dati.email =
          valore;
      }


      else if (
        chiave ===
          "password" ||

        chiave ===
          "pass"
      ) {

        dati
          .occorrenze
          .password++;


        dati.password =
          valore;
      }


      else if (
        chiave ===
          "data di nascita" ||

        chiave ===
          "data nascita" ||

        chiave ===
          "nascita"
      ) {

        dati
          .occorrenze
          .dataNascita++;


        dati.dataNascita =
          valore;
      }


      else if (
        chiave ===
          "dispositivo android o apple" ||

        chiave ===
          "dispositivo android o iphone" ||

        chiave ===
          "dispositivo"
      ) {

        dati
          .occorrenze
          .dispositivo++;


        dati.dispositivo =
          valore;
      }


      else if (
        chiave ===
          "codice fiscale" ||

        chiave ===
          "cf"
      ) {

        dati
          .occorrenze
          .codiceFiscale++;


        dati.codiceFiscale =
          valore;
      }
    }


    return dati;
  }


  // ==========================================================
  // SITI STANDARD
  // ==========================================================

  for (
    const riga of righe
  ) {

    const posizione =
      riga.indexOf(
        ":"
      );


    if (
      posizione === -1
    ) {

      continue;
    }


    const chiave =
      normalizza(

        riga.substring(
          0,
          posizione
        )
      );


    const valore =
      riga.substring(
        posizione + 1
      ).trim();


    if (
      chiave ===
        "nome e cognome" ||

      chiave ===
        "nome cognome" ||

      chiave ===
        "nome"
    ) {

      dati
        .occorrenze
        .nome++;


      dati.nome =
        valore;
    }


    else if (
      chiave ===
        "username" ||

      chiave ===
        "user" ||

      chiave ===
        "nome utente"
    ) {

      dati
        .occorrenze
        .username++;


      dati.username =
        valore;
    }


    else if (
      chiave ===
        "password" ||

      chiave ===
        "pass"
    ) {

      dati
        .occorrenze
        .password++;


      dati.password =
        valore;
    }
  }


  return dati;
}

function trovaIntestazioniStandard(
  foglio
) {

  const numeroRighe =
    Math.min(
      100,
      foglio.getMaxRows()
    );


  const numeroColonne =
    Math.max(
      1,
      foglio.getLastColumn()
    );


  const valori =
    foglio
      .getRange(
        1,
        1,
        numeroRighe,
        numeroColonne
      )
      .getDisplayValues();


  let risultato =
    null;


  for (
    let r = 0;
    r < valori.length;
    r++
  ) {

    const colonne = {

      data:
        null,

      nome:
        null,

      username:
        null,

      password:
        null,

      provenienza:
        null
    };


    for (
      let c = 0;
      c < valori[r].length;
      c++
    ) {

      const intestazione =
        normalizza(
          valori[r][c]
        );


      if (
        intestazione ===
          "data apertura" ||

        intestazione ===
          "data di apertura"
      ) {

        colonne.data =
          c + 1;
      }


      else if (
        intestazione ===
          "nome cognome" ||

        intestazione ===
          "nome e cognome"
      ) {

        colonne.nome =
          c + 1;
      }


      else if (
        intestazione ===
          "username" ||

        intestazione ===
          "user" ||

        intestazione ===
          "nome utente"
      ) {

        colonne.username =
          c + 1;
      }


      else if (
        intestazione ===
        "password"
      ) {

        colonne.password =
          c + 1;
      }


      else if (
        intestazione ===
        "provenienza"
      ) {

        colonne.provenienza =
          c + 1;
      }
    }


    if (
      colonne.nome &&
      colonne.username &&
      colonne.password &&
      colonne.provenienza
    ) {

      risultato = {

        riga:
          r + 1,

        colonne:
          colonne
      };
    }
  }


  if (!risultato) {

    throw new Error(
      "intestazioni necessarie non trovate nel foglio " +
      foglio.getName()
    );
  }


  return risultato;
}

function scriviRiga(
  foglio,
  riga,
  intestazioni,
  dati,
  provenienza,
  tipo,
  inserisciDataApertura
) {

  const c =
    intestazioni.colonne;


  if (
    tipo ===
    "bet365"
  ) {

    foglio
      .getRange(
        riga,
        c.nome
      )
      .setValue(
        dati.nome
      );


    foglio
      .getRange(
        riga,
        c.email
      )
      .setValue(
        dati.email
      );


    foglio
      .getRange(
        riga,
        c.password
      )
      .setValue(
        dati.password
      );


    foglio
      .getRange(
        riga,
        c.dataNascita
      )
      .setValue(
        dati.dataNascitaOggetto
      )
      .setNumberFormat(
        "dd/MM/yyyy"
      );


    foglio
      .getRange(
        riga,
        c.dispositivo
      )
      .setValue(
        dati.dispositivoNormalizzato
      );


    foglio
      .getRange(
        riga,
        c.codiceFiscale
      )
      .setValue(
        dati.codiceFiscale
      );


    foglio
      .getRange(
        riga,
        c.provenienza
      )
      .setValue(
        provenienza
      );


    return;
  }


  foglio
    .getRange(
      riga,
      c.nome
    )
    .setValue(
      dati.nome
    );


  foglio
    .getRange(
      riga,
      c.username
    )
    .setValue(
      dati.username
    );


  foglio
    .getRange(
      riga,
      c.password
    )
    .setValue(
      dati.password
    );


  foglio
    .getRange(
      riga,
      c.provenienza
    )
    .setValue(
      provenienza
    );


  if (
    inserisciDataApertura &&
    c.data
  ) {

    foglio
      .getRange(
        riga,
        c.data
      )
      .setValue(
        dataOggiItalia()
      )
      .setNumberFormat(
        "dd/MM/yyyy"
      );
  }
}

function validaDatiAccount(
  dati
) {

  if (!dati.sito) {

    throw new Error(
      "sito non riconosciuto. Usa PokerStars, Sisal Sport, MyLotteriesPlay oppure Bet365."
    );
  }


  if (
    dati.sito ===
    "Bet365"
  ) {

    const mancanti =
      [];


    if (!dati.nome) {

      mancanti.push(
        "Nome cliente"
      );
    }


    if (!dati.email) {

      mancanti.push(
        "Email usata"
      );
    }


    if (!dati.password) {

      mancanti.push(
        "Password"
      );
    }


    if (
      !dati.dataNascita
    ) {

      mancanti.push(
        "Data di nascita"
      );
    }


    if (
      !dati.dispositivo
    ) {

      mancanti.push(
        "Dispositivo"
      );
    }


    if (
      !dati.codiceFiscale
    ) {

      mancanti.push(
        "Codice fiscale"
      );
    }


    if (
      mancanti.length > 0
    ) {

      throw new Error(
        "manca: " +
        mancanti.join(
          ", "
        )
      );
    }


    controllaOccorrenzaSingola(
      dati.occorrenze.nome,
      "Nome cliente"
    );


    controllaOccorrenzaSingola(
      dati.occorrenze.email,
      "Email usata"
    );


    controllaOccorrenzaSingola(
      dati.occorrenze.password,
      "Password"
    );


    controllaOccorrenzaSingola(
      dati.occorrenze.dataNascita,
      "Data di nascita"
    );


    controllaOccorrenzaSingola(
      dati.occorrenze.dispositivo,
      "Dispositivo"
    );


    controllaOccorrenzaSingola(
      dati.occorrenze.codiceFiscale,
      "Codice fiscale"
    );


    if (
      String(
        dati.nome
      ).trim().length < 2
    ) {

      throw new Error(
        "Nome cliente sembra troppo corto."
      );
    }


    if (
      !emailValida(
        dati.email
      )
    ) {

      throw new Error(
        "Email usata non sembra valida."
      );
    }


    dati.dataNascitaOggetto =
      parseDataNascita(
        dati.dataNascita
      );


    dati.dispositivoNormalizzato =
      normalizzaDispositivo(
        dati.dispositivo
      );


    return;
  }


  const mancanti =
    [];


  if (!dati.nome) {

    mancanti.push(
      "Nome e Cognome"
    );
  }


  if (!dati.username) {

    mancanti.push(
      "Username"
    );
  }


  if (!dati.password) {

    mancanti.push(
      "Password"
    );
  }


  if (
    mancanti.length > 0
  ) {

    throw new Error(
      "manca: " +
      mancanti.join(
        ", "
      )
    );
  }


  controllaOccorrenzaSingola(
    dati.occorrenze.nome,
    "Nome e Cognome"
  );


  controllaOccorrenzaSingola(
    dati.occorrenze.username,
    "Username"
  );


  controllaOccorrenzaSingola(
    dati.occorrenze.password,
    "Password"
  );


  if (
    String(
      dati.nome
    ).trim().length < 2
  ) {

    throw new Error(
      "Nome e Cognome sembra troppo corto."
    );
  }
}

function eseguiTest(
  chatId
) {

  let risposta =
    "🔧 TEST IL BANCO BOT\n\n";


  risposta +=
    "✅ Fuso orario: " +
    TIMEZONE +
    "\n";


  risposta +=
    "✅ Finestra correzione: " +
    CORRECTION_WINDOW_MINUTES +
    " minuti\n";


  risposta +=
    typeof completaEmailRiga ===
      "function"

      ? "✅ Email Matcher collegato\n"

      : "❌ Email Matcher non trovato\n";


  const sitiDaTestare = [

    "PokerStars",
    "Sisal Sport",
    "MyLotteriesPlay",
    "Bet365"
  ];


  for (
    const sito of
    sitiDaTestare
  ) {

    const config =
      CONFIG_SITI[
        sito
      ];


    const spreadsheetId =
      PropertiesService
        .getScriptProperties()
        .getProperty(
          config.spreadsheetProperty
        );


    if (!spreadsheetId) {

      risposta +=
        "\n❌ " +
        sito +
        ": " +
        config.spreadsheetProperty +
        " mancante\n";


      continue;
    }


    try {

      const ss =
        SpreadsheetApp.openById(
          spreadsheetId
        );


      const foglio =
        trovaFoglio(
          ss,
          config.foglio
        );


      if (!foglio) {

        risposta +=
          "\n❌ " +
          sito +
          ": foglio non trovato\n";


        continue;
      }


      const intestazioni =
        trovaIntestazioni(
          foglio,
          config.tipo
        );


      risposta +=
        "\n✅ " +
        sito +
        ": tabella riconosciuta";


      risposta +=
        "\n   Nome: " +
        numeroColonnaLettera(
          intestazioni
            .colonne
            .nome
        );


      if (
        config.tipo ===
        "bet365"
      ) {

        risposta +=
          "\n   E-mail: " +
          numeroColonnaLettera(
            intestazioni
              .colonne
              .email
          );


        risposta +=
          "\n   Password: " +
          numeroColonnaLettera(
            intestazioni
              .colonne
              .password
          );


        risposta +=
          "\n   Data nascita: " +
          numeroColonnaLettera(
            intestazioni
              .colonne
              .dataNascita
          );


        risposta +=
          "\n   Dispositivo: " +
          numeroColonnaLettera(
            intestazioni
              .colonne
              .dispositivo
          );


        risposta +=
          "\n   Codice fiscale: " +
          numeroColonnaLettera(
            intestazioni
              .colonne
              .codiceFiscale
          );

      } else {

        risposta +=
          "\n   Username: " +
          numeroColonnaLettera(
            intestazioni
              .colonne
              .username
          );


        risposta +=
          "\n   Password: " +
          numeroColonnaLettera(
            intestazioni
              .colonne
              .password
          );
      }


      risposta +=
        "\n   Provenienza: " +
        numeroColonnaLettera(
          intestazioni
            .colonne
            .provenienza
        ) +
        "\n";


    } catch (
      errore
    ) {

      risposta +=
        "\n❌ " +
        sito +
        ": " +
        errore.message +
        "\n";
    }
  }


  inviaTelegram(
    chatId,
    risposta
  );
}

function bancoSheets_() {
  if (bancoSheetRefs_) return bancoSheetRefs_;
  const result=[];
  bancoBooks_().forEach(b=>{
    const book=SpreadsheetApp.openById(b.id);
    book.getSheets().forEach(sheet=>{
      const cfg=Object.keys(CONFIG_SITI).map(k=>CONFIG_SITI[k]).find(c=>c.spreadsheetProperty===b.key && c.foglio===sheet.getName());
      if (cfg && ['Sisal Sport','PokerStars'].indexOf(sheet.getName())!==-1) result.push({book:b.id,bookIndex:b.index,bookTitle:book.getName(),sheet:sheet,gid:sheet.getSheetId(),name:sheet.getName()});
    });
  });
  bancoSheetRefs_=result;return result;
}

function bancoState_(item,account,mirror) {
  const operator=item.name==='Sisal Sport'?'sisal':item.name==='PokerStars'?'pokerstars':null;
  const record=mirror.states[account.email.toLowerCase()+'\n'+operator];
  if (!operator) return {code:'unmonitored',label:'⚪ Non monitorato',detail:'Questo operatore non è incluso nel monitor delle email.'};
  if (!account.email || !account.hasMailPassword || account.emailColor!==account.mailPasswordColor || !bancoAllowedColor_(account.emailColor))
    return {code:'unmonitored',label:'⚪ Non monitorato',detail:'Account escluso dagli attuali controlli sulle celle email/password email.'};
  if (!mirror.available || !record) return {code:'unknown',label:'🔵 In attesa di controllo',detail:'Lo stato sarà disponibile dopo il prossimo controllo del monitor.'};
  if (!record.monitored) return {code:'unmonitored',label:'⚪ Non monitorato',detail:'Account escluso dall’ultimo controllo del monitor.'};
  const labels={active:'🟢 Attivo',documents:'🟠 Richiesta documenti',reactivated:'✅ Riattivato'};
  return {code:record.state,label:labels[record.state]||'🔵 In attesa di controllo',changed:record.changed,detail:record.state==='active'?'Nessuna richiesta documenti rilevata dal monitor.':''};
}

function bancoInvalidate_() {
  const cache=CacheService.getScriptCache();
  if (typeof cache.removeAll==='function') cache.removeAll(bancoBooks_().flatMap(b=>['Sisal Sport','PokerStars'].map(n=>'bn:'+BANCO_MENU_VERSION+':'+b.id+':'+n)).concat(['bn:root:'+BANCO_MENU_VERSION]));
}
const BANCO_MENU_VERSION = '1.2.1';
