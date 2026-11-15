// Pure Banco v41 configurations/functions. No credentials or customer data.
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


  "Sisal Slot 600": {
    spreadsheetProperty: "SPREADSHEET_ID",
    foglio: "Sisal Slot 600",
    tipo: "standard"
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
  "Sisal Slot 600",

  "PokerStars",
  "Sisal Sport",
  "MyLotteriesPlay"
];


// ============================================================

function bancoSisalSlot600_(header) {
  return /^(?:sisal600|sisalslot600)$/.test(compatta(header));
}
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
    bancoSisalSlot600_(righe[0]) ? "Sisal Slot 600" : null;


  for (
    const chiave in SITI
  ) {

    if (
      sito === null && primaRiga.includes(
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

function validaDatiAccount(
  dati
) {

  if (!dati.sito) {

    throw new Error(
      "sito non riconosciuto. Usa PokerStars, Sisal Sport, Sisal Slot 600, MyLotteriesPlay oppure Bet365."
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

function controllaOccorrenzaSingola(
  numero,
  nomeCampo
) {

  if (
    Number(
      numero
    ) > 1
  ) {

    throw new Error(
      'il campo "' +
      nomeCampo +
      '" compare più di una volta.'
    );
  }
}

function trovaIntestazioni(
  foglio,
  tipo
) {

  if (
    tipo ===
    "bet365"
  ) {

    return trovaIntestazioniBet365(
      foglio
    );
  }


  return trovaIntestazioniStandard(
    foglio
  );
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

function trovaAccountDuplicato(
  foglio,
  intestazioni,
  dati,
  tipo,
  rigaDaIgnorare
) {

  const primaRiga =
    intestazioni.riga +
    1;


  const ultimaRiga =
    foglio.getLastRow();


  if (
    ultimaRiga <
    primaRiga
  ) {

    return null;
  }


  const numeroRighe =
    ultimaRiga -
    primaRiga +
    1;


  const numeroColonne =
    Math.max(
      1,
      foglio.getLastColumn()
    );


  const valori =
    foglio
      .getRange(
        primaRiga,
        1,
        numeroRighe,
        numeroColonne
      )
      .getDisplayValues();


  const nomeNuovo =
    normalizzaConfronto(
      dati.nome
    );


  const passwordNuova =
    String(
      dati.password
    ).trim();


  for (
    let i = 0;
    i < valori.length;
    i++
  ) {

    const numeroRiga =
      primaRiga +
      i;


    if (
      rigaDaIgnorare &&
      numeroRiga ===
        rigaDaIgnorare
    ) {

      continue;
    }


    const nomeEsistente =
      normalizzaConfronto(

        valori[i][
          intestazioni
            .colonne
            .nome - 1
        ]
      );


    const passwordEsistente =
      String(

        valori[i][
          intestazioni
            .colonne
            .password - 1
        ] || ""

      ).trim();


    if (
      tipo ===
      "bet365"
    ) {

      const emailEsistente =
        normalizzaEmail(

          valori[i][
            intestazioni
              .colonne
              .email - 1
          ]
        );


      if (
        nomeEsistente ===
          nomeNuovo &&

        emailEsistente ===
          normalizzaEmail(
            dati.email
          ) &&

        passwordEsistente ===
          passwordNuova
      ) {

        return {
          riga:
            numeroRiga
        };
      }
    }


    else {

      const usernameEsistente =
        normalizzaUsername(

          valori[i][
            intestazioni
              .colonne
              .username - 1
          ]
        );


      if (
        nomeEsistente ===
          nomeNuovo &&

        usernameEsistente ===
          normalizzaUsername(
            dati.username
          ) &&

        passwordEsistente ===
          passwordNuova
      ) {

        return {
          riga:
            numeroRiga
        };
      }
    }
  }


  return null;
}

function trovaPossibileDuplicato(
  foglio,
  intestazioni,
  dati,
  tipo,
  rigaDaIgnorare
) {

  const primaRiga =
    intestazioni.riga +
    1;


  const ultimaRiga =
    foglio.getLastRow();


  if (
    ultimaRiga <
    primaRiga
  ) {

    return null;
  }


  const numeroRighe =
    ultimaRiga -
    primaRiga +
    1;


  if (
    tipo ===
    "bet365"
  ) {

    const valori =
      foglio
        .getRange(
          primaRiga,
          intestazioni
            .colonne
            .email,
          numeroRighe,
          1
        )
        .getDisplayValues();


    const emailNuova =
      normalizzaEmail(
        dati.email
      );


    for (
      let i = 0;
      i < valori.length;
      i++
    ) {

      const numeroRiga =
        primaRiga +
        i;


      if (
        rigaDaIgnorare &&
        numeroRiga ===
          rigaDaIgnorare
      ) {

        continue;
      }


      const emailEsistente =
        normalizzaEmail(
          valori[i][0]
        );


      if (
        emailEsistente &&
        emailEsistente ===
          emailNuova
      ) {

        return {
          riga:
            numeroRiga
        };
      }
    }


    return null;
  }


  const valori =
    foglio
      .getRange(
        primaRiga,
        intestazioni
          .colonne
          .username,
        numeroRighe,
        1
      )
      .getDisplayValues();


  const usernameNuovo =
    normalizzaUsername(
      dati.username
    );


  for (
    let i = 0;
    i < valori.length;
    i++
  ) {

    const numeroRiga =
      primaRiga +
      i;


    if (
      rigaDaIgnorare &&
      numeroRiga ===
        rigaDaIgnorare
    ) {

      continue;
    }


    const usernameEsistente =
      normalizzaUsername(
        valori[i][0]
      );


    if (
      usernameEsistente &&
      usernameEsistente ===
        usernameNuovo
    ) {

      return {
        riga:
          numeroRiga
      };
    }
  }


  return null;
}

function trovaPrimaRigaLibera(
  foglio,
  intestazioni,
  tipo
) {

  const primaRiga =
    intestazioni.riga +
    1;


  const ultimaRiga =
    foglio.getMaxRows();


  const numeroRighe =
    ultimaRiga -
    primaRiga +
    1;


  const numeroColonne =
    Math.max(
      1,
      foglio.getLastColumn()
    );


  if (
    numeroRighe > 0
  ) {

    const valori =
      foglio
        .getRange(
          primaRiga,
          1,
          numeroRighe,
          numeroColonne
        )
        .getDisplayValues();


    for (
      let i = 0;
      i < valori.length;
      i++
    ) {

      const nomeVuoto =
        String(

          valori[i][
            intestazioni
              .colonne
              .nome - 1
          ] || ""

        ).trim() === "";


      const passwordVuota =
        String(

          valori[i][
            intestazioni
              .colonne
              .password - 1
          ] || ""

        ).trim() === "";


      let identificativoVuoto;


      if (
        tipo ===
        "bet365"
      ) {

        identificativoVuoto =
          String(

            valori[i][
              intestazioni
                .colonne
                .email - 1
            ] || ""

          ).trim() === "";

      } else {

        identificativoVuoto =
          String(

            valori[i][
              intestazioni
                .colonne
                .username - 1
            ] || ""

          ).trim() === "";
      }


      if (
        nomeVuoto &&
        identificativoVuoto &&
        passwordVuota
      ) {

        return (
          primaRiga +
          i
        );
      }
    }
  }


  const ultima =
    foglio.getMaxRows();


  foglio.insertRowAfter(
    ultima
  );


  if (
    ultima >= 1
  ) {

    const origine =
      foglio.getRange(
        ultima,
        1,
        1,
        numeroColonne
      );


    const destinazione =
      foglio.getRange(
        ultima + 1,
        1,
        1,
        numeroColonne
      );


    origine.copyTo(

      destinazione,

      SpreadsheetApp
        .CopyPasteType
        .PASTE_FORMAT,

      false
    );


    try {

      destinazione
        .setDataValidations(

          origine
            .getDataValidations()
        );

    } catch (
      errore
    ) {

      // niente
    }
  }


  return ultima + 1;
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

function correggiUltimo(
  ss,
  props,
  telegramId,
  chatId,
  userMessageId,
  dati,
  config
) {

  const ultimoJson =
    props.getProperty(
      "LAST_" +
      telegramId
    );


  if (!ultimoJson) {

    props.deleteProperty(
      "CORRECT_" +
      telegramId
    );


    throw new Error(
      "ultimo inserimento non trovato."
    );
  }


  const ultimo =
    JSON.parse(
      ultimoJson
    );


  if (
    correzioneScaduta(
      ultimo
    )
  ) {

    props.deleteProperty(
      "CORRECT_" +
      telegramId
    );


    throw new Error(
      "il tempo disponibile per correggere questo account è scaduto."
    );
  }


  if (
    compatta(
      ultimo.sito
    ) !==
    compatta(
      dati.sito
    )
  ) {

    throw new Error(
      "il tuo ultimo inserimento appartiene a " +
      ultimo.sito +
      ".\n\n" +
      "Invia i dati di " +
      ultimo.sito +
      " oppure usa /annulla."
    );
  }


  const foglio =
    trovaFoglio(
      ss,
      ultimo.foglio
    );


  if (!foglio) {

    throw new Error(
      "foglio dell'ultimo inserimento non trovato."
    );
  }


  const tipoUltimo =
    ultimo.tipo ||
    config.tipo;


  const intestazioni =
    trovaIntestazioni(
      foglio,
      tipoUltimo
    );


  const lock =
    LockService
      .getScriptLock();


  let lockOttenuto =
    false;


  try {

    lockOttenuto =
      lock.tryLock(
        30000
      );


    if (!lockOttenuto) {

      throw new Error(
        "il foglio è momentaneamente occupato."
      );
    }


    const duplicato =
      trovaAccountDuplicato(
        foglio,
        intestazioni,
        dati,
        tipoUltimo,
        ultimo.riga
      );


    if (duplicato) {

      inviaTelegram(
        chatId,

        "⚠️ Correzione non effettuata.\n\n" +
        "Esiste già un altro account identico su " +
        dati.sito +
        ".\n\n" +
        "Puoi inviare nuovamente i dati corretti oppure usare /annulla."
      );


      return;
    }


    const possibileDuplicato =
      trovaPossibileDuplicato(
        foglio,
        intestazioni,
        dati,
        tipoUltimo,
        ultimo.riga
      );


    if (
      possibileDuplicato
    ) {

      if (
        tipoUltimo ===
        "bet365"
      ) {

        inviaTelegram(
          chatId,

          "⚠️ Correzione non effettuata.\n\n" +
          "Esiste già un altro account Bet365 con la stessa E-mail.\n\n" +
          "Puoi inviare nuovamente i dati corretti oppure usare /annulla."
        );

      } else {

        inviaTelegram(
          chatId,

          "⚠️ Correzione non effettuata.\n\n" +
          "Esiste già un altro account su " +
          dati.sito +
          " con lo stesso Username.\n\n" +
          "Puoi inviare nuovamente i dati corretti oppure usare /annulla."
        );
      }


      return;
    }


    scriviRiga(
      foglio,
      ultimo.riga,
      intestazioni,
      dati,
      UTENTI[
        telegramId
      ],
      tipoUltimo,
      false
    );


    SpreadsheetApp.flush();


    props.deleteProperty(
      "CORRECT_" +
      telegramId
    );


  } finally {

    if (
      lockOttenuto
    ) {

      try {

        lock.releaseLock();

      } catch (
        errore
      ) {

        // niente
      }
    }
  }


  const botMessageId =
    inviaTelegram(

      chatId,

      creaMessaggioConferma(
        dati,
        UTENTI[
          telegramId
        ],
        tipoUltimo,
        true
      )
    );


  sostituisciUltimoMessaggioAccount(
    telegramId,
    chatId,
    userMessageId,
    botMessageId,
    dati.sito
  );
}

function gestisciInserimento(
  chatId,
  telegramId,
  userMessageId,
  testo
) {

  const props =
    PropertiesService
      .getScriptProperties();


  const dati =
    interpretaMessaggio(
      testo
    );


  // GoldBet diventa un archivio: non aprire fogli né modificare LAST/CORRECT.
  if (dati.sito === "GoldBet") {
    inviaTelegram(chatId, "ℹ️ GoldBet è archiviato. Nuovi inserimenti e correzioni sono disattivati; nessun dato salvato.");
    return;
  }

  // SNAI e sospeso: il foglio resta soltanto un archivio email.
  // Non scrivere dati, non modificare LAST/CORRECT e non avviare EmailMatcher.
  if (dati.sito === "Snai Sport") {
    inviaTelegram(chatId, "ℹ️ Gli inserimenti Snai sono temporaneamente disattivati. Nessun dato salvato.");
    return;
  }

  validaDatiAccount(
    dati
  );


  const config =
    CONFIG_SITI[
      dati.sito
    ];


  if (!config) {

    throw new Error(
      "configurazione del sito non trovata."
    );
  }


  const spreadsheetId =
    props.getProperty(
      config.spreadsheetProperty
    );


  if (!spreadsheetId) {

    throw new Error(
      config.spreadsheetProperty +
      " non configurato."
    );
  }


  let ss;


  try {

    ss =
      SpreadsheetApp.openById(
        spreadsheetId
      );

  } catch (errore) {

    throw new Error(
      "non riesco ad aprire il Google Sheet di " +
      dati.sito +
      "."
    );
  }


  impostaFusoOrarioItaliano(
    ss
  );


  const correzione =
    props.getProperty(
      "CORRECT_" +
      telegramId
    ) === "1";


  if (correzione) {

    correggiUltimo(
      ss,
      props,
      telegramId,
      chatId,
      userMessageId,
      dati,
      config
    );


    return;
  }


  const foglio =
    trovaFoglio(
      ss,
      config.foglio
    );


  if (!foglio) {

    throw new Error(
      'non trovo il foglio "' +
      config.foglio +
      '".'
    );
  }


  const intestazioni =
    trovaIntestazioni(
      foglio,
      config.tipo
    );


  const lock =
    LockService
      .getScriptLock();


  let lockOttenuto =
    false;


  let nuovaRiga =
    null;


  try {

    lockOttenuto =
      lock.tryLock(
        30000
      );


    if (!lockOttenuto) {

      throw new Error(
        "il foglio è momentaneamente occupato. Riprova tra qualche secondo."
      );
    }


    const duplicato =
      trovaAccountDuplicato(
        foglio,
        intestazioni,
        dati,
        config.tipo,
        null
      );


    if (duplicato) {

      inviaTelegram(
        chatId,

        "⚠️ Account già inserito.\n\n" +
        "Questo account è già presente su " +
        dati.sito +
        " e non è stato aggiunto di nuovo."
      );


      return;
    }


    const possibileDuplicato =
      trovaPossibileDuplicato(
        foglio,
        intestazioni,
        dati,
        config.tipo,
        null
      );


    if (
      possibileDuplicato
    ) {

      if (
        config.tipo ===
        "bet365"
      ) {

        inviaTelegram(
          chatId,

          "⚠️ Possibile duplicato.\n\n" +
          "Esiste già un account su Bet365 con la stessa E-mail.\n\n" +
          "L'account NON è stato aggiunto.\n" +
          "Controlla i dati oppure usa /correggi se devi modificare il tuo ultimo inserimento."
        );

      } else {

        inviaTelegram(
          chatId,

          "⚠️ Possibile duplicato.\n\n" +
          "Esiste già un account su " +
          dati.sito +
          " con lo stesso Username.\n\n" +
          "L'account NON è stato aggiunto.\n" +
          "Controlla i dati oppure usa /correggi se devi modificare il tuo ultimo inserimento."
        );
      }


      return;
    }


    nuovaRiga =
      trovaPrimaRigaLibera(
        foglio,
        intestazioni,
        config.tipo
      );


    scriviRiga(
      foglio,
      nuovaRiga,
      intestazioni,
      dati,
      UTENTI[
        telegramId
      ],
      config.tipo,
      true
    );


    SpreadsheetApp.flush();


    props.setProperty(

      "LAST_" +
      telegramId,

      JSON.stringify({

        sito:
          dati.sito,

        foglio:
          foglio.getName(),

        spreadsheetProperty:
          config.spreadsheetProperty,

        tipo:
          config.tipo,

        riga:
          nuovaRiga,

        timestamp:
          Date.now()
      })
    );


  } finally {

    if (
      lockOttenuto
    ) {

      try {

        lock.releaseLock();

      } catch (
        errore
      ) {

        // niente
      }
    }
  }


  // ==========================================================
  // EMAIL MATCHER
  // ==========================================================

  avviaEmailMatcherNuovoAccount(
    dati.sito,
    nuovaRiga
  );


  const botMessageId =
    inviaTelegram(

      chatId,

      creaMessaggioConferma(
        dati,
        UTENTI[
          telegramId
        ],
        config.tipo,
        false
      )
    );


  registraNuovoMessaggioAccount(
    telegramId,
    chatId,
    userMessageId,
    botMessageId,
    dati.sito
  );


  notificaAdminNuovoAccount(
    telegramId,
    dati.sito
  );
}

function doPost(e) {

  let chatId = null;


  try {

    const props =
      PropertiesService
        .getScriptProperties();


    // ========================================================
    // CONTROLLO SEGRETO WEBHOOK
    // ========================================================

    bancoDashboardContext_=!!(e && e.parameter && e.parameter.bot==='dashboard');
    const secret=props.getProperty(bancoDashboardContext_?'DASHBOARD_WEBHOOK_SECRET':'WEBHOOK_SECRET');


    if (
      !secret ||
      !e ||
      !e.parameter ||
      e.parameter.key !== secret
    ) {

      return rispostaOK();
    }


    if (
      !e.postData ||
      !e.postData.contents
    ) {

      return rispostaOK();
    }


    // ========================================================
    // LETTURA UPDATE
    // ========================================================

    let update;


    try {

      update =
        JSON.parse(
          e.postData.contents
        );

    } catch (errore) {

      return rispostaOK();
    }


    if (bancoDashboardContext_) {segretarioRiceviUpdate_(update);return rispostaOK();}

    // Authenticated state sync uses the same existing webhook secret.
    if (update && Array.isArray(update.banco_status_sync)) {
      const result=bancoRiceviStati_(update.banco_status_sync);
      bancoInvalidate_();
      return result;
    }
    if (update && update.banco_monitor_notice) return bancoMonitorNotice_(update.banco_monitor_notice);
    if (update && Number.isSafeInteger(update.banco_notice_message)) {
      return bancoExternalNotice_(update.banco_notice_message);
    }

    // ========================================================
    // ANTI-RETRY TELEGRAM
    // ========================================================

    if (
      typeof update.update_id !==
      "undefined"
    ) {

      const updateId =
        String(
          update.update_id
        );


      if (
        !prenotaUpdate(
          updateId
        )
      ) {

        return rispostaOK();
      }
    }


    // EmailMatcher: callbacks owner-only, after webhook authentication and deduplication.
    if (typeof EM_gestisciCallbackOmonimo_ === "function" && EM_gestisciCallbackOmonimo_(update)) {
      return rispostaOK();
    }

    // Private dashboard and callbacks; existing commands retain their handlers.
    if (typeof bancoGestisciUpdate === "function" && bancoGestisciUpdate(update)) {
      return rispostaOK();
    }

    const message =
      update.message;


    if (
      !message ||
      !message.text ||
      !message.from ||
      !message.chat
    ) {

      return rispostaOK();
    }


    chatId =
      message.chat.id;


    const telegramId =
      String(
        message.from.id
      );


    const userMessageId =
      message.message_id;


    const testo =
      String(
        message.text
      ).trim();


    // ========================================================
    // /id
    // ========================================================

    if (
      /^\/id(?:@\w+)?(?:\s|$)/i
        .test(testo)
    ) {

      inviaTelegram(
        chatId,

        "Il tuo Telegram ID è:\n" +
        telegramId
      );


      return rispostaOK();
    }


    // ========================================================
    // AUTORIZZAZIONE
    // ========================================================

    if (
      !UTENTI[
        telegramId
      ]
    ) {

      inviaTelegram(
        chatId,
        "⛔ Utente non autorizzato."
      );


      return rispostaOK();
    }


    // ========================================================
    // /test
    // ========================================================

    if (
      /^\/test(?:@\w+)?(?:\s|$)/i
        .test(testo)
    ) {

      eseguiTest(
        chatId
      );


      return rispostaOK();
    }


    // ========================================================
    // /annulla
    // ========================================================

    if (
      /^\/annulla(?:@\w+)?(?:\s|$)/i
        .test(testo)
    ) {

      const chiave =
        "CORRECT_" +
        telegramId;


      if (
        props.getProperty(
          chiave
        ) === "1"
      ) {

        props.deleteProperty(
          chiave
        );


        inviaTelegram(
          chatId,

          "✅ Correzione annullata.\n\n" +
          "Il prossimo account verrà inserito normalmente."
        );

      } else {

        inviaTelegram(
          chatId,

          "ℹ️ Nessuna correzione è attualmente attiva."
        );
      }


      return rispostaOK();
    }


    // ========================================================
    // /correggi
    // ========================================================

    if (
      /^\/correggi(?:@\w+)?(?:\s|$)/i
        .test(testo)
    ) {

      const ultimoJson =
        props.getProperty(
          "LAST_" +
          telegramId
        );


      if (!ultimoJson) {

        inviaTelegram(
          chatId,

          "❌ Non risulta nessun tuo inserimento da correggere."
        );


        return rispostaOK();
      }


      let ultimo;


      try {

        ultimo =
          JSON.parse(
            ultimoJson
          );

      } catch (errore) {

        inviaTelegram(
          chatId,

          "❌ Non riesco a recuperare il tuo ultimo inserimento."
        );


        return rispostaOK();
      }


      if (
        correzioneScaduta(
          ultimo
        )
      ) {

        props.deleteProperty(
          "CORRECT_" +
          telegramId
        );


        inviaTelegram(
          chatId,

          "⌛ Correzione non disponibile.\n\n" +
          "Sono trascorsi più di " +
          CORRECTION_WINDOW_MINUTES +
          " minuti dall'inserimento."
        );


        return rispostaOK();
      }


      props.setProperty(
        "CORRECT_" +
        telegramId,

        "1"
      );


      inviaTelegram(
        chatId,

        "✏️ Invia ora nuovamente il messaggio completo con i dati corretti.\n\n" +
        "Verrà modificato esclusivamente il tuo ultimo inserimento.\n\n" +
        "Per uscire senza modificare nulla usa /annulla."
      );


      return rispostaOK();
    }


    // ========================================================
    // ACCOUNT
    // ========================================================

    let messaggioCaricamentoId =
      null;


    try {

      messaggioCaricamentoId =
        inviaTelegram(
          chatId,

          "⏳ Dati ricevuti, inserimento in corso..."
        );


      gestisciInserimento(
        chatId,
        telegramId,
        userMessageId,
        testo
      );


    } catch (
      erroreInserimento
    ) {

      inviaTelegram(
        chatId,

        "❌ Inserimento non riuscito.\n\n" +
        "Errore: " +
        erroreInserimento.message
      );


    } finally {

      if (
        messaggioCaricamentoId
      ) {

        eliminaMessaggioTelegram(
          chatId,
          messaggioCaricamentoId
        );
      }
    }


  } catch (
    erroreGenerale
  ) {

    console.error(
      "Errore generale: " +
      erroreGenerale.message
    );


    if (
      chatId !== null
    ) {

      try {

        inviaTelegram(
          chatId,

          "❌ Si è verificato un errore tecnico."
        );

      } catch (
        erroreTelegram
      ) {

        // niente
      }
    }
  }


  return rispostaOK();
}

function creaMessaggioConferma(
  dati,
  provenienza,
  tipo,
  correzione
) {

  const titolo =
    correzione
      ?
      "✅ Ultimo inserimento corretto."
      :
      "✅ Inserimento completato.";


  if (
    tipo ===
    "bet365"
  ) {

    return (
      titolo +
      "\n\n" +
      "Bet365\n" +
      "Nome: " +
      dati.nome +
      "\n" +
      "E-mail: " +
      dati.email +
      "\n" +
      "Password: ✅ ricevuta\n" +
      "Dispositivo: " +
      dati.dispositivoNormalizzato +
      "\n" +
      "Provenienza: " +
      provenienza
    );
  }


  return (
    titolo +
    "\n\n" +
    dati.sito +
    "\n" +
    "Nome: " +
    dati.nome +
    "\n" +
    "Username: " +
    dati.username +
    "\n" +
    "Password: ✅ ricevuta\n" +
    "Provenienza: " +
    provenienza
  );
}

function dataOggiItalia() {

  const oggi =
    Utilities.formatDate(
      new Date(),
      TIMEZONE,
      "yyyy-MM-dd"
    );


  const parti =
    oggi.split(
      "-"
    );


  return new Date(

    Date.UTC(
      Number(
        parti[0]
      ),
      Number(
        parti[1]
      ) - 1,
      Number(
        parti[2]
      ),
      12,
      0,
      0
    )
  );
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
    "Sisal Slot 600",

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
      if (cfg && ['Sisal Sport','Sisal Slot 600','PokerStars'].indexOf(sheet.getName())!==-1) result.push({book:b.id,bookIndex:b.index,bookTitle:book.getName(),sheet:sheet,gid:sheet.getSheetId(),name:sheet.getName()});
    });
  });
  bancoSheetRefs_=result;return result;
}

function bancoState_(item,account,mirror) {
  const operator=['Sisal Sport','Sisal Slot 600'].includes(item.name)?'sisal':item.name==='PokerStars'?'pokerstars':null;
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
  if (typeof cache.removeAll==='function') cache.removeAll(bancoBooks_().flatMap(b=>['Sisal Sport','Sisal Slot 600','PokerStars'].map(n=>'bn:'+BANCO_MENU_VERSION+':'+b.id+':'+n)).concat(['bn:root:'+BANCO_MENU_VERSION]));
}

function normalizzaConfronto(
  testo
) {

  return normalizza(
    testo
  )
    .replace(
      /\s+/g,
      " "
    )
    .trim();
}

function normalizzaUsername(
  testo
) {

  return String(
    testo || ""
  )
    .trim()
    .toLowerCase();
}
const BANCO_MENU_VERSION = '1.2.2';
