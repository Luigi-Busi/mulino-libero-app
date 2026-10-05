// ============================================================
// IL BANCO BOT
// Telegram -> Google Sheets
// ============================================================


// ============================================================
// CONFIGURAZIONE GENERALE
// ============================================================

const TIMEZONE = "Europe/Rome";

const CORRECTION_WINDOW_MINUTES = 60;


// ============================================================
// IMPORTANTE
// ============================================================
//
// MANTIENI QUI I TUOI VALORI REALI ATTUALI.
//
// ============================================================

const ADMIN_TELEGRAM_ID = "123456789";


const UTENTI = {"123456789": "Admin"};


// ============================================================
// RICONOSCIMENTO SITI
// ============================================================

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


  "GoldBet": {

    spreadsheetProperty:
      "SPREADSHEET_ID",

    foglio:
      "GoldBet",

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
  "GoldBet",
  "MyLotteriesPlay"
];


// ============================================================
// WEB APP
// ============================================================

function doGet() {

  return HtmlService.createHtmlOutput(
    "Il Banco Bot è attivo"
  );
}


// ============================================================
// WEBHOOK TELEGRAM
// ============================================================

function doPost(e) {

  let chatId = null;


  try {

    const props =
      PropertiesService
        .getScriptProperties();


    // ========================================================
    // CONTROLLO SEGRETO WEBHOOK
    // ========================================================

    const secret =
      props.getProperty(
        "WEBHOOK_SECRET"
      );


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


    // Authenticated state sync uses the same existing webhook secret.
    if (update && Array.isArray(update.banco_status_sync)) {
      const result=bancoRiceviStati_(update.banco_status_sync);
      bancoInvalidate_();
      return result;
    }
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


// ============================================================
// ANTI-DUPLICATO UPDATE TELEGRAM
// ============================================================

function prenotaUpdate(
  updateId
) {

  const cache =
    CacheService
      .getScriptCache();


  const lock =
    LockService
      .getScriptLock();


  try {

    lock.waitLock(
      10000
    );


    const chiave =
      "TG_UPDATE_" +
      updateId;


    if (
      cache.get(
        chiave
      )
    ) {

      return false;
    }


    cache.put(
      chiave,
      "1",
      21600
    );


    return true;


  } finally {

    try {

      lock.releaseLock();

    } catch (
      errore
    ) {

      // niente
    }
  }
}


// ============================================================
// SCADENZA /CORREGGI
// ============================================================

function correzioneScaduta(
  ultimo
) {

  if (
    !ultimo ||
    !ultimo.timestamp
  ) {

    return true;
  }


  const massimoMs =
    CORRECTION_WINDOW_MINUTES *
    60 *
    1000;


  return (
    Date.now() -
    Number(
      ultimo.timestamp
    )
  ) > massimoMs;
}


// ============================================================
// GESTIONE ACCOUNT
// ============================================================

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


// ============================================================
// EMAIL MATCHER DOPO NUOVO ACCOUNT
// ============================================================

function avviaEmailMatcherNuovoAccount(
  sito,
  riga
) {

  if (
    SITI_EMAIL_MATCHER
      .indexOf(
        sito
      ) === -1
  ) {

    return;
  }


  if (
    typeof completaEmailRiga !==
    "function"
  ) {

    console.error(
      "Email Matcher non disponibile: funzione completaEmailRiga() non trovata."
    );


    return;
  }


  try {

    const risultato =
      completaEmailRiga(
        sito,
        Number(riga)
      );


    if (
      risultato &&
      risultato.stato
    ) {

      console.log(
        "Email Matcher | " +
        sito +
        " | riga " +
        riga +
        " | " +
        risultato.stato
      );

    } else {

      console.log(
        "Email Matcher | " +
        sito +
        " | riga " +
        riga +
        " | completato"
      );
    }


  } catch (
    errore
  ) {

    console.error(
      "Errore Email Matcher su " +
      sito +
      " riga " +
      riga +
      ": " +
      errore.message
    );
  }
}


// ============================================================
// PARSER
// ============================================================

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


// ============================================================
// VALIDAZIONE
// ============================================================

function validaDatiAccount(
  dati
) {

  if (!dati.sito) {

    throw new Error(
      "sito non riconosciuto. Usa PokerStars, Sisal Sport, GoldBet, MyLotteriesPlay oppure Bet365."
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


// ============================================================
// CONTROLLO CAMPO RIPETUTO
// ============================================================

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


// ============================================================
// EMAIL
// ============================================================

function emailValida(
  email
) {

  const valore =
    String(
      email || ""
    ).trim();


  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/
    .test(
      valore
    );
}


// ============================================================
// DISPOSITIVO BET365
// ============================================================

function normalizzaDispositivo(
  dispositivo
) {

  const valore =
    normalizza(
      dispositivo
    );


  if (
    valore.includes(
      "android"
    )
  ) {

    return "Android";
  }


  if (
    valore.includes(
      "apple"
    ) ||

    valore.includes(
      "iphone"
    ) ||

    valore ===
      "ios" ||

    valore.includes(
      " ios "
    )
  ) {

    return "Apple";
  }


  throw new Error(
    'Dispositivo non riconosciuto. Scrivi "Android" oppure "Apple".'
  );
}


// ============================================================
// DATA NASCITA BET365
// ============================================================

function parseDataNascita(
  testo
) {

  const valore =
    String(
      testo || ""
    ).trim();


  let giorno;
  let mese;
  let anno;


  let match =
    valore.match(

      /^(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{4})$/
    );


  if (match) {

    giorno =
      Number(
        match[1]
      );


    mese =
      Number(
        match[2]
      );


    anno =
      Number(
        match[3]
      );

  } else {

    match =
      valore.match(

        /^(\d{4})[\/\-.](\d{1,2})[\/\-.](\d{1,2})$/
      );


    if (!match) {

      throw new Error(
        "Data di nascita non valida. Usa ad esempio 15/04/2000."
      );
    }


    anno =
      Number(
        match[1]
      );


    mese =
      Number(
        match[2]
      );


    giorno =
      Number(
        match[3]
      );
  }


  const controllo =
    new Date(

      Date.UTC(
        anno,
        mese - 1,
        giorno,
        12,
        0,
        0
      )
    );


  if (
    controllo
      .getUTCFullYear() !==
      anno ||

    controllo
      .getUTCMonth() !==
      mese - 1 ||

    controllo
      .getUTCDate() !==
      giorno
  ) {

    throw new Error(
      "Data di nascita non valida."
    );
  }


  return controllo;
}


// ============================================================
// TROVA FOGLIO
// ============================================================

function trovaFoglio(
  ss,
  nome
) {

  const target =
    compatta(
      nome
    );


  for (
    const foglio of
    ss.getSheets()
  ) {

    if (
      compatta(
        foglio.getName()
      ) === target
    ) {

      return foglio;
    }
  }


  return null;
}


// ============================================================
// TROVA INTESTAZIONI
// ============================================================

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


// ============================================================
// INTESTAZIONI STANDARD
// ============================================================

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


// ============================================================
// INTESTAZIONI BET365
// ============================================================

function trovaIntestazioniBet365(
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

      nome:
        null,

      email:
        null,

      password:
        null,

      dataNascita:
        null,

      dispositivo:
        null,

      codiceFiscale:
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
          "nome e cognome" ||

        intestazione ===
          "nome cognome"
      ) {

        colonne.nome =
          c + 1;
      }


      else if (
        intestazione ===
          "e mail usata" ||

        intestazione ===
          "email usata" ||

        intestazione ===
          "e mail" ||

        intestazione ===
          "email"
      ) {

        colonne.email =
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
          "data di nascita" ||

        intestazione ===
          "data nascita"
      ) {

        colonne.dataNascita =
          c + 1;
      }


      else if (
        intestazione ===
        "dispositivo"
      ) {

        colonne.dispositivo =
          c + 1;
      }


      else if (
        intestazione ===
        "codice fiscale"
      ) {

        colonne.codiceFiscale =
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
      colonne.email &&
      colonne.password &&
      colonne.dataNascita &&
      colonne.dispositivo &&
      colonne.codiceFiscale &&
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
      "intestazioni Bet365 non trovate. Controlla che siano presenti Nome e Cognome, E-mail usata, Password, Data di nascita, Dispositivo, Codice fiscale e Provenienza."
    );
  }


  return risultato;
}


// ============================================================
// DUPLICATO ESATTO
// ============================================================

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


// ============================================================
// POSSIBILE DUPLICATO
// ============================================================

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


// ============================================================
// PRIMA RIGA LIBERA
// ============================================================

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


// ============================================================
// SCRITTURA RIGA
// ============================================================

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


// ============================================================
// CORREZIONE
// ============================================================

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


// ============================================================
// CONFERMA
// ============================================================

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


// ============================================================
// NOTIFICA ADMIN
// ============================================================

function notificaAdminNuovoAccount(
  telegramId,
  sito
) {

  if (
    String(
      telegramId
    ) ===
    String(
      ADMIN_TELEGRAM_ID
    )
  ) {

    return;
  }


  const nomeUtente =
    UTENTI[
      telegramId
    ] ||
    "Utente autorizzato";


  try {

    inviaTelegram(

      ADMIN_TELEGRAM_ID,

      "🔔 Nuovo account inserito\n\n" +
      nomeUtente +
      " ha aggiunto un account su " +
      sito +
      "."
    );

  } catch (
    errore
  ) {

    console.error(
      "Errore notifica admin: " +
      errore.message
    );
  }
}


// ============================================================
// CRONOLOGIA CHAT
// ============================================================

function registraNuovoMessaggioAccount(
  telegramId,
  chatId,
  userMessageId,
  botMessageId,
  sito
) {

  const cronologia =
    caricaCronologiaMessaggi(
      telegramId
    );


  cronologia.push({

    chatId:
      String(
        chatId
      ),

    userMessageId:
      userMessageId,

    botMessageId:
      botMessageId,

    sito:
      sito,

    timestamp:
      Date.now()
  });


  const daEliminare =
    [];


  while (
    cronologia.length > 2
  ) {

    daEliminare.push(
      cronologia.shift()
    );
  }


  salvaCronologiaMessaggi(
    telegramId,
    cronologia
  );


  for (
    const operazione of
    daEliminare
  ) {

    // Account acquisition messages are retained.
  }
}


// ============================================================
// SOSTITUZIONE DOPO CORREZIONE
// ============================================================

function sostituisciUltimoMessaggioAccount(
  telegramId,
  chatId,
  userMessageId,
  botMessageId,
  sito
) {

  const cronologia =
    caricaCronologiaMessaggi(
      telegramId
    );


  let vecchiaOperazione =
    null;


  if (
    cronologia.length > 0
  ) {

    vecchiaOperazione =
      cronologia.pop();
  }


  cronologia.push({

    chatId:
      String(
        chatId
      ),

    userMessageId:
      userMessageId,

    botMessageId:
      botMessageId,

    sito:
      sito,

    timestamp:
      Date.now()
  });


  salvaCronologiaMessaggi(
    telegramId,
    cronologia
  );


  if (
    vecchiaOperazione
  ) {

    // The previous acquisition confirmation is retained after correction.
  }
}


// ============================================================
// CARICA CRONOLOGIA
// ============================================================

function caricaCronologiaMessaggi(
  telegramId
) {

  const valore =
    PropertiesService
      .getScriptProperties()
      .getProperty(
        "CHAT_HISTORY_" +
        telegramId
      );


  if (!valore) {

    return [];
  }


  try {

    const risultato =
      JSON.parse(
        valore
      );


    if (
      Array.isArray(
        risultato
      )
    ) {

      return risultato;
    }

  } catch (
    errore
  ) {

    // niente
  }


  return [];
}


// ============================================================
// SALVA CRONOLOGIA
// ============================================================

function salvaCronologiaMessaggi(
  telegramId,
  cronologia
) {

  PropertiesService
    .getScriptProperties()
    .setProperty(

      "CHAT_HISTORY_" +
      telegramId,

      JSON.stringify(
        cronologia
      )
    );
}


// ============================================================
// ELIMINA VECCHIA OPERAZIONE
// ============================================================

function eliminaOperazioneDallaChat(
  operazione
) {

  if (!operazione) {

    return;
  }


  if (
    operazione.userMessageId
  ) {

    eliminaMessaggioTelegram(
      operazione.chatId,
      operazione.userMessageId
    );
  }


  if (
    operazione.botMessageId
  ) {

    eliminaMessaggioTelegram(
      operazione.chatId,
      operazione.botMessageId
    );
  }
}


// ============================================================
// FUSO ORARIO
// ============================================================

function impostaFusoOrarioItaliano(
  ss
) {

  if (
    ss.getSpreadsheetTimeZone() !==
    TIMEZONE
  ) {

    ss.setSpreadsheetTimeZone(
      TIMEZONE
    );
  }
}


// ============================================================
// DATA OGGI
// ============================================================

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


// ============================================================
// /TEST
// ============================================================

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
    "GoldBet",
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


// ============================================================
// TELEGRAM SEND
// ============================================================

function inviaTelegram(
  chatId,
  testo
) {

  const token =
    PropertiesService
      .getScriptProperties()
      .getProperty(
        "TELEGRAM_TOKEN"
      );


  if (!token) {

    throw new Error(
      "TELEGRAM_TOKEN mancante."
    );
  }


  const risposta =
    UrlFetchApp.fetch(

      "https://api.telegram.org/bot" +
      token +
      "/sendMessage",

      {
        method:
          "post",

        payload: {

          chat_id:
            String(
              chatId
            ),

          text:
            String(
              testo
            )
        },

        muteHttpExceptions:
          true
      }
    );


  const codice =
    risposta.getResponseCode();


  if (
    codice < 200 ||
    codice >= 300
  ) {

    throw new Error(
      "Telegram sendMessage HTTP " +
      codice
    );
  }


  const json =
    JSON.parse(
      risposta.getContentText()
    );


  if (!json.ok) {

    throw new Error(
      "Telegram API: " +
      (
        json.description ||
        "errore sconosciuto"
      )
    );
  }


  if (
    json.result &&
    json.result.message_id
  ) {

    bancoLegacySent_(chatId,json.result.message_id,testo);
    return (
      json.result.message_id
    );
  }


  return null;
}


// ============================================================
// TELEGRAM DELETE
// ============================================================

function eliminaMessaggioTelegram(
  chatId,
  messageId
) {
  if (bancoSkipLegacyDelete_(chatId,messageId)) return;

  if (
    !chatId ||
    !messageId
  ) {

    return false;
  }


  const token =
    PropertiesService
      .getScriptProperties()
      .getProperty(
        "TELEGRAM_TOKEN"
      );


  if (!token) {

    return false;
  }


  try {

    const risposta =
      UrlFetchApp.fetch(

        "https://api.telegram.org/bot" +
        token +
        "/deleteMessage",

        {
          method:
            "post",

          payload: {

            chat_id:
              String(
                chatId
              ),

            message_id:
              String(
                messageId
              )
          },

          muteHttpExceptions:
            true
        }
      );


    const json =
      JSON.parse(
        risposta.getContentText()
      );


    return (
      risposta.getResponseCode() >=
        200 &&

      risposta.getResponseCode() <
        300 &&

      json.ok ===
        true
    );


  } catch (
    errore
  ) {

    console.error(
      "Impossibile eliminare messaggio Telegram: " +
      errore.message
    );


    return false;
  }
}


// ============================================================
// RISPOSTA WEBHOOK
// ============================================================

function rispostaOK() {
  bancoFinalize_();

  return HtmlService
    .createHtmlOutput(
      "OK"
    );
}


// ============================================================
// WEBHOOK SETUP
// ============================================================

function setupWebhook() {

  configuraWebhook(
    false
  );
}


function resetWebhook() {

  configuraWebhook(
    true
  );
}


function configuraWebhook(
  cancellaPendenti
) {

  const props =
    PropertiesService
      .getScriptProperties();


  const token =
    props.getProperty(
      "TELEGRAM_TOKEN"
    );


  const webAppUrl =
    props.getProperty(
      "WEB_APP_URL"
    );


  if (!token) {

    throw new Error(
      "TELEGRAM_TOKEN mancante."
    );
  }


  if (!webAppUrl) {

    throw new Error(
      "WEB_APP_URL mancante."
    );
  }


  if (
    !/\/exec\/?$/
      .test(
        webAppUrl
      )
  ) {

    throw new Error(
      "WEB_APP_URL deve terminare con /exec."
    );
  }


  let secret =
    props.getProperty(
      "WEBHOOK_SECRET"
    );


  if (!secret) {

    secret =
      Utilities
        .getUuid()
        .replace(
          /-/g,
          ""
        );


    props.setProperty(
      "WEBHOOK_SECRET",
      secret
    );
  }


  const webhookUrl =
    webAppUrl
      .replace(
        /\/$/,
        ""
      ) +
    "?key=" +
    encodeURIComponent(
      secret
    );


  const payload = {

    url:
      webhookUrl,

    max_connections:
      1
  };


  if (
    cancellaPendenti
  ) {

    payload
      .drop_pending_updates =
      true;
  }


  const risposta =
    UrlFetchApp.fetch(

      "https://api.telegram.org/bot" +
      token +
      "/setWebhook",

      {
        method:
          "post",

        payload:
          payload,

        muteHttpExceptions:
          true
      }
    );


  console.log(
    risposta.getContentText()
  );
}


// ============================================================
// CONTROLLO WEBHOOK
// ============================================================

function controllaWebhook() {

  const token =
    PropertiesService
      .getScriptProperties()
      .getProperty(
        "TELEGRAM_TOKEN"
      );


  const risposta =
    UrlFetchApp.fetch(

      "https://api.telegram.org/bot" +
      token +
      "/getWebhookInfo"
    );


  console.log(
    risposta.getContentText()
  );
}


// ============================================================
// NORMALIZZAZIONE
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


function normalizzaEmail(
  testo
) {

  return String(
    testo || ""
  )
    .trim()
    .toLowerCase();
}


// ============================================================
// NUMERO COLONNA -> LETTERA
// ============================================================

function numeroColonnaLettera(
  numero
) {

  let risultato =
    "";


  while (
    numero > 0
  ) {

    const resto =
      (
        numero - 1
      ) % 26;


    risultato =
      String.fromCharCode(
        65 + resto
      ) +
      risultato;


    numero =
      Math.floor(
        (
          numero - 1
        ) / 26
      );
  }


  return risultato;
}

// Il Banco: private account dashboard. No credentials in logs/cache/callback_data.
const BANCO_MENU_VERSION = '1.1.1';
const BANCO_STATUS_TAB = 'Stato Account Banco';
const BANCO_PAGE_SIZE = 8;
const BANCO_COLORS = ['#ffffff','#ff00ff','#9900ff','#d9d2e9','#b4a7d6','#8e7cc3','#674ea7','#351c75','#20124d'];

// Manual commissioning check: only the configured administrator receives views.
function bancoVerificaMenuPrivato() {
  const chat={id:String(ADMIN_TELEGRAM_ID),type:'private'};
  const root=bancoRender_(chat,null,bancoRoot_());
  const items=bancoSheets_(),item=items.find(s=>s.name==='Sisal Sport') || items[0];
  let detail=null;
  if (item) {
    const accounts=bancoAccounts_(item,false),mirror=bancoMirror_();
    const account=accounts.find(a=>bancoState_(item,a,mirror).code==='active') || accounts[0];
    if (account) detail=bancoRender_(chat,null,bancoAccount_(item.bookIndex,item.gid,account.row,account.fingerprint,0));
  }
  console.log(JSON.stringify({ok:true,version:BANCO_MENU_VERSION,worksheets:items.length,root_message:root.message_id,detail_message:detail && detail.message_id}));
}

function bancoRiceviStati_(rows) {
  const headers=['email','operatore','stato','ultima_variazione','monitorato','ultimo_controllo','consegna','id_evento'];
  if (rows.length<2 || rows.length>10000 || rows[0].join('|')!==headers.join('|') || rows[1][0]!=='__meta__') throw new Error('Stati non validi');
  rows.forEach((r,i)=>{
    if (!Array.isArray(r) || r.length!==8 || r.some(v=>typeof v!=='string' || v.length>320)) throw new Error('Formato stati non valido');
    if (i>1 && (['sisal','pokerstars','snai'].indexOf(r[1])===-1 || ['active','documents','reactivated'].indexOf(r[2])===-1 || !/^[01]$/.test(r[4]) || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(r[0]))) throw new Error('Record stato non valido');
  });
  const lock=LockService.getScriptLock();lock.waitLock(30000);
  try {
    const id=PropertiesService.getScriptProperties().getProperty('SPREADSHEET_ID_LOG_MAIL');
    if (!id) throw new Error('File log non configurato');
    const book=SpreadsheetApp.openById(id);
    let sheet=book.getSheetByName(BANCO_STATUS_TAB);
    if (!sheet) sheet=book.insertSheet(BANCO_STATUS_TAB);
    if (sheet.getLastRow() && sheet.getRange(1,1,1,8).getDisplayValues()[0].join('|')!==headers.join('|')) throw new Error('Scheda stati occupata da altri dati');
    const last=sheet.getLastRow(),total=Math.max(last,rows.length);
    if (sheet.getMaxRows()<total) sheet.insertRowsAfter(sheet.getMaxRows(),total-sheet.getMaxRows());
    const payload=rows.map(r=>r.map(v=>v.startsWith('=')?"'"+v:v));
    while (payload.length<total) payload.push(['','','','','','','','']);
    sheet.getRange(1,1,total,8).setNumberFormat('@').setValues(payload);
    SpreadsheetApp.flush();
    const digest=Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,JSON.stringify(rows),Utilities.Charset.UTF_8).map(v=>('0'+((v+256)%256).toString(16)).slice(-2)).join('');
    return ContentService.createTextOutput(JSON.stringify({ok:true,rows:rows.length,digest:digest,version:BANCO_MENU_VERSION,chat_state:bancoChatRead_()})).setMimeType(ContentService.MimeType.JSON);
  } finally {lock.releaseLock();}
}

function bancoApi_(method, data) {
  const token = PropertiesService.getScriptProperties().getProperty('TELEGRAM_TOKEN');
  if (!token) throw new Error('Banco non configurato');
  let response;
  try {
    response = UrlFetchApp.fetch('https://api.telegram.org/bot' + token + '/' + method, {
      method: 'post', contentType: 'application/json', payload: JSON.stringify(data), muteHttpExceptions: true
    });
  } catch (_) { throw new Error('Connessione Telegram non riuscita'); }
  let value;
  try { value = JSON.parse(response.getContentText()); } catch (_) { throw new Error('Risposta Telegram non valida'); }
  if (!value.ok) {
    if (method === 'editMessageText' && String(value.description || '').indexOf('message is not modified') !== -1) return;
    throw new Error('Operazione Telegram non riuscita');
  }
  return value.result;
}

function bancoPrivateAdmin_(actor, chat) {
  return !!actor && !!chat && !actor.is_bot && chat.type === 'private' &&
    String(actor.id) === String(ADMIN_TELEGRAM_ID) && String(chat.id) === String(ADMIN_TELEGRAM_ID);
}

function bancoRender_(chat,message,view) {return bancoPanelRender_(chat,message,view);}

function bancoGestisciUpdate(update) {
  const callback = update.callback_query;
  const message = callback ? callback.message : update.message;
  const text = String(message && message.text || '').trim();
  const command = text.split(/\s/)[0].split('@')[0].toLowerCase();
  let data = callback ? String(callback.data || '') : '';
  bancoForceRefresh_=data.indexOf('bn:r:')===0;
  if (bancoForceRefresh_) data=data.replace('bn:r:','bn:');
  const recognized = callback ? data.indexOf('bn:') === 0 : ['/start','/menu','/account','/stato','/help'].indexOf(command) !== -1;

  const actor = callback ? callback.from : message && message.from;
  const chat = message && message.chat;
  if (!bancoPrivateAdmin_(actor,chat)) {
    if (!recognized) return false;
    if (callback) bancoApi_('answerCallbackQuery',{callback_query_id:callback.id,text:'Menu riservato alla chat privata dell’amministratore.',show_alert:true});
    else if (chat) bancoApi_('sendMessage',{chat_id:chat.id,text:'Menu riservato alla chat privata dell’amministratore.'});
    return true;
  }
  bancoObserve_(message,callback && /^bn:cmd:/.test(data)?'/'+data.split(':')[2]:command,callback);
  if (!recognized) return false;
  if (callback) bancoApi_('answerCallbackQuery',{callback_query_id:callback.id});
  // Existing commands continue through the original authorization/correction code.
  if (callback && /^bn:cmd:(correggi|annulla|test|id)$/.test(data)) {
    update.message = {from:actor, chat:chat, message_id:message.message_id,text:'/'+data.split(':')[2]};
    return false;
  }
  try {
    let view;
    if (!callback) view = ['/account','/stato'].indexOf(command)!==-1 ? bancoRoot_() : command==='/help' ? bancoHelp_() : bancoHome_();
    else if (data==='bn:menu') view=bancoHome_();
    else if (data==='bn:help') view=bancoHelp_();
    else if (data==='bn:root') view=bancoRoot_();
    else {
      const pieces=data.split(':');
      if (pieces[1]==='s' && pieces.length===5 && pieces.slice(2).every(x=>/^\d+$/.test(x)))
        view=bancoSheet_(Number(pieces[2]),Number(pieces[3]),Number(pieces[4]));
      else if (pieces[1]==='a' && pieces.length===7 && pieces.slice(2,5).every(x=>/^\d+$/.test(x)) && /^[a-f0-9]{12}$/.test(pieces[5]) && /^\d+$/.test(pieces[6]))
        view=bancoAccount_(Number(pieces[2]),Number(pieces[3]),Number(pieces[4]),pieces[5],Number(pieces[6]));
      else view={text:'Questo pulsante non è più valido. Torna all’elenco aggiornato.',buttons:[[bancoButton_('📊 Stato account','bn:root')]]};
    }
    bancoRender_(chat,callback ? message.message_id : null,view);
  } catch (_) {
    bancoApi_('sendMessage',{chat_id:String(chat.id),text:'Non riesco ad aggiornare la schermata. Riprova con /menu. Nessuna modifica è stata effettuata agli account.'});
  }
  return true;
}

function bancoButton_(text,data) {return {text:text,callback_data:data};}
function bancoHome_() {
  return {text:'🏦 Il Banco\n\nConsulta gli account e il loro stato, oppure usa i comandi di gestione.\nPer inserire un account, invia il messaggio completo con i dati come fai già.',buttons:[
    [bancoButton_('📊 Stato account','bn:root')],
    [bancoButton_('✏️ Correggi ultimo inserimento','bn:cmd:correggi')],
    [bancoButton_('↩️ Annulla correzione','bn:cmd:annulla'),bancoButton_('🧪 Test','bn:cmd:test')],
    [bancoButton_('❓ Guida','bn:help'),bancoButton_('🆔 Il mio ID','bn:cmd:id')]]};
}
function bancoHelp_() {
  return {text:'🏦 Guida del Banco\n\n/menu — apre il menu\n/account o /stato — fogli e stato account\n/correggi — corregge il tuo ultimo inserimento entro 60 minuti; reinvia poi il messaggio completo\n/annulla — esce dalla correzione\n/test — verifica i collegamenti configurati\n/id — mostra il tuo identificativo Telegram\n\nNella scheda account puoi copiare username, password dell’account ed email. La password è nascosta nel testo.\n\n🟢 Attivo: nessuna richiesta documenti rilevata dal monitor.\n🟠 Richiesta documenti: mail individuata dal monitor.\n✅ Riattivato: successiva mail di riattivazione individuata.\n⚪ Non monitorato: fuori dai controlli attivi.\n\nIl monitor controlla ogni ora dalle 08:00 alle 21:00, ora italiana. Dopo la notifica della richiesta documento, la riattivazione viene cercata dalle 08:00 del giorno successivo, inclusa la posta arrivata nel frattempo.',buttons:[[bancoButton_('📊 Stato account','bn:root'),bancoButton_('🏠 Menu','bn:menu')]]};
}

function bancoBooks_() {
  const props=PropertiesService.getScriptProperties();
  return ['SPREADSHEET_ID'].map((key,index)=>({key:key,index:index,id:props.getProperty(key)})).filter(b=>!!b.id);
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
function bancoFindSheet_(bi,gid) {
  const item=bancoSheets_().find(s=>s.bookIndex===bi && s.gid===gid);
  if (!item) throw new Error('Foglio non disponibile');
  return item;
}
function bancoNorm_(v) {return String(v||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[-_]/g,' ').replace(/\s+/g,' ').trim();}
function bancoHeaders_(values) {
  for (let r=0;r<Math.min(30,values.length);r++) {
    const row=values[r].map(bancoNorm_);
    const find=names=>row.findIndex(v=>names.indexOf(v)!==-1);
    const h={row:r,name:find(['nome cognome','nome e cognome','nome cliente']),username:find(['username','user name']),password:find(['password','pass']),email:find(['e mail','email','email usata','e mail usata']),mailPassword:find(['password e mail','password email','pass e mail','pass email']),stable:find(['id mulino'])};
    if (h.name>=0 && h.password>=0 && (h.username>=0 || h.email>=0)) return h;
  }
  throw new Error('Intestazioni account non riconosciute');
}
function bancoFingerprint_(a) {
  const raw=[a.name,a.username,a.email,a.stable].join('\n');
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,raw,Utilities.Charset.UTF_8).map(v=>('0'+((v+256)%256).toString(16)).slice(-2)).join('').slice(0,12);
}
function bancoAccounts_(item,withPassword,rowNumber) {
  const sheet=item.sheet,cache=CacheService.getScriptCache(),key='bn:'+BANCO_MENU_VERSION+':'+item.book+':'+item.name;
  if (!withPassword && !bancoForceRefresh_) {
    try {const hit=cache.get(key);if (hit) return JSON.parse(hit);} catch (_) {}
  }
  const last=sheet.getLastRow();if (!last || last>10000) throw new Error('Dimensioni foglio non riconosciute');
  const width=Math.min(sheet.getLastColumn(),26);
  const headerValues=sheet.getRange(1,1,rowNumber?Math.min(last,30):last,width).getDisplayValues();
  const headers=bancoHeaders_(headerValues);
  if (rowNumber && (rowNumber<=headers.row+1 || rowNumber>last)) return [];
  const start=rowNumber||1;
  const values=rowNumber?sheet.getRange(rowNumber,1,1,width).getDisplayValues():headerValues;
  const colors=sheet.getRange(start,1,values.length,width).getBackgrounds();const result=[];
  for (let i=0;i<values.length;i++) {
    const physical=start+i;if (physical<=headers.row+1) continue;
    const row=values[i],get=n=>n>=0?String(row[n]||'').trim():'';
    const name=get(headers.name),username=get(headers.username),email=get(headers.email);
    if (!name || (!username && !email && !get(headers.password))) continue;
    const a={row:physical,name:name,username:username,email:email,stable:get(headers.stable),emailColor:headers.email>=0?colors[i][headers.email].toLowerCase():'unknown',mailPasswordColor:headers.mailPassword>=0?colors[i][headers.mailPassword].toLowerCase():'unknown',hasMailPassword:!!get(headers.mailPassword)};
    if (withPassword) a.password=get(headers.password);
    a.fingerprint=bancoFingerprint_(a);result.push(a);
  }
  if (!withPassword) {try {const raw=JSON.stringify(result);if (raw.length<80000) cache.put(key,raw,45);} catch (_) {}}
  return result;
}

function bancoMirror_() {
  const id=PropertiesService.getScriptProperties().getProperty('SPREADSHEET_ID_LOG_MAIL');
  const data={states:{},updated:'',available:false};
  if (!id) return data;
  const sheet=SpreadsheetApp.openById(id).getSheetByName(BANCO_STATUS_TAB);
  if (!sheet) return data;
  const rows=sheet.getDataRange().getDisplayValues();
  if (!rows.length || rows[0].join('|')!=='email|operatore|stato|ultima_variazione|monitorato|ultimo_controllo|consegna|id_evento') return data;
  rows.slice(1).forEach(r=>{
    if (r[0]==='__meta__') {data.updated=r[5];data.available=true;}
    else data.states[String(r[0]).trim().toLowerCase()+'\n'+r[1]]={state:r[2],changed:r[3],monitored:r[4]==='1',delivery:r[6]};
  });
  return data;
}
function bancoAllowedColor_(c) {return BANCO_COLORS.indexOf(c)!==-1 || (/^#[0-9a-f]{6}$/.test(c) && c!=='#000000' && c.slice(1,3)===c.slice(3,5) && c.slice(3,5)===c.slice(5,7));}
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
function bancoDate_(value) {
  if (!value) return '—';
  const d=new Date(value);return isNaN(d.getTime())?'—':Utilities.formatDate(d,'Europe/Rome','dd/MM/yyyy HH:mm');
}
function bancoCounts_(accounts,item,mirror) {
  const counts={active:0,documents:0,reactivated:0,unmonitored:0,unknown:0};
  accounts.forEach(a=>{const s=bancoState_(item,a,mirror);counts[s.code]=(counts[s.code]||0)+1;});
  return '🟢 '+counts.active+'  🟠 '+counts.documents+'  ✅ '+counts.reactivated+'  ⚪ '+counts.unmonitored+(counts.unknown?'  🔵 '+counts.unknown:'');
}
function bancoRoot_() {
  const mirror=bancoMirror_(),items=bancoSheets_(),buttons=[];
  let text='📊 Stato account\n\n';let lastBook=null;
  items.forEach(item=>{
    if (lastBook!==item.book) {text+='📁 '+item.bookTitle+'\n';lastBook=item.book;}
    const accounts=bancoAccounts_(item,false);
    text+=item.name+' · '+accounts.length+' account\n'+bancoCounts_(accounts,item,mirror)+'\n\n';
    buttons.push([bancoButton_('Apri '+item.name,'bn:s:'+item.bookIndex+':'+item.gid+':0')]);
  });
  text+='🟢 Attivo · 🟠 Richiesta documenti · ✅ Riattivato\n⚪ Non monitorato · 🔵 In attesa di controllo\n\nUltimo controllo: '+bancoDate_(mirror.updated);
  buttons.push([bancoButton_('🔄 Aggiorna','bn:r:root'),bancoButton_('🏠 Menu','bn:menu')]);
  return {text:text,buttons:buttons};
}
function bancoSheet_(bi,gid,requestedPage) {
  const item=bancoFindSheet_(bi,gid),mirror=bancoMirror_(),accounts=bancoAccounts_(item,false).slice().reverse();
  const pages=Math.max(1,Math.ceil(accounts.length/BANCO_PAGE_SIZE)),page=Math.min(requestedPage,pages-1);
  const batch=accounts.slice(page*BANCO_PAGE_SIZE,(page+1)*BANCO_PAGE_SIZE);
  let text='📁 '+item.bookTitle+'\n'+item.name+' · '+accounts.length+' account\n'+bancoCounts_(accounts,item,mirror)+'\n\nPagina '+(page+1)+'/'+pages+' · ultimi inseriti per primi\n';
  const buttons=batch.map(a=>[bancoButton_(bancoState_(item,a,mirror).label+' · '+a.name.slice(0,55),'bn:a:'+bi+':'+gid+':'+a.row+':'+a.fingerprint+':'+page)]);
  if (!batch.length) text+='\nNessun account presente.';
  const nav=[];
  if (page>0) nav.push(bancoButton_('◀️ Indietro','bn:s:'+bi+':'+gid+':'+(page-1)));
  if (page+1<pages) nav.push(bancoButton_('Avanti ▶️','bn:s:'+bi+':'+gid+':'+(page+1)));
  if (nav.length) buttons.push(nav);
  buttons.push([bancoButton_('🔄 Aggiorna','bn:r:s:'+bi+':'+gid+':'+page),bancoButton_('📂 Fogli','bn:root')]);
  return {text:text,buttons:buttons};
}
function bancoAccount_(bi,gid,row,fingerprint,page) {
  const item=bancoFindSheet_(bi,gid),account=bancoAccounts_(item,true,row).find(a=>a.row===row);
  const back='bn:s:'+bi+':'+gid+':'+page;
  if (!account || account.fingerprint!==fingerprint) return {text:'La riga dell’account è cambiata. Apri di nuovo l’elenco per consultare i dati aggiornati.',buttons:[[bancoButton_('📋 Torna agli account',back)]]};
  const mirror=bancoMirror_(),state=bancoState_(item,account,mirror);
  let text=account.name+' — '+item.name+'\n'+state.label+'\n\nUsername: '+(account.username||'—')+'\nEmail: '+(account.email||'—')+'\nPassword: '+(account.password?'nascosta · usa il pulsante Copia':'non presente');
  if (state.detail) text+='\n\n'+state.detail;
  if (state.changed) text+='\nUltimo cambio di stato: '+bancoDate_(state.changed);
  text+='\nUltimo controllo: '+bancoDate_(mirror.updated);
  const buttons=[],copy=[];
  [['📋 Copia username',account.username],['🔑 Copia password',account.password],['📧 Copia email',account.email]].forEach(pair=>{
    if (pair[1] && Array.from(pair[1]).length<=256) copy.push({text:pair[0],copy_text:{text:pair[1]}});
  });
  if (copy.length) buttons.push(copy);
  buttons.push([bancoButton_('🔄 Aggiorna','bn:r:a:'+bi+':'+gid+':'+row+':'+fingerprint+':'+page),bancoButton_('↩️ Account',back)]);
  return {text:text,buttons:buttons};
}


// Only message IDs, timestamps and explicitly allowed routine categories persist.
const BANCO_CHAT_KEY = 'BANCO_CHAT_V1';
let bancoContext_ = null;
let bancoSheetRefs_ = null;
let bancoForceRefresh_ = false;

function bancoChatRead_() {
  let s;
  try {s=JSON.parse(PropertiesService.getScriptProperties().getProperty(BANCO_CHAT_KEY)||'{}');} catch (_) {s={};}
  return {panel:Number(s.panel)||0,last:Number(s.last)||0,routines:Array.isArray(s.routines)?s.routines:[],retired:Array.isArray(s.retired)?s.retired:[]};
}
function bancoChatWrite_(s) {
  s.routines=s.routines.slice(-180);s.retired=s.retired.slice(-40);
  PropertiesService.getScriptProperties().setProperty(BANCO_CHAT_KEY,JSON.stringify(s));
}
function bancoChatLock_(fn) {
  const lock=LockService.getScriptLock();lock.waitLock(15000);
  try {return fn();} finally {lock.releaseLock();}
}
function bancoRoutine_(s,id,kind,at) {
  if (!Number.isSafeInteger(id)||id<=0||s.routines.some(r=>r[0]===id)) return;
  s.routines.push([id,at||Date.now(),kind]);
}
function bancoObserve_(message,command,callback) {
  bancoContext_={message:Number(message.message_id)||0,command:command,callback:!!callback};
  bancoChatLock_(()=>{
    const s=bancoChatRead_();s.last=Math.max(s.last,bancoContext_.message);
    if (!callback && ['/start','/menu','/account','/stato','/help','/test','/id','/correggi','/annulla'].indexOf(command)!==-1)
      bancoRoutine_(s,bancoContext_.message,'c',message.date?message.date*1000:Date.now());
    bancoChatWrite_(s);
  });
}
function bancoDeleteKnown_(id) {
  try {bancoApi_('deleteMessage',{chat_id:String(ADMIN_TELEGRAM_ID),message_id:id});return true;}
  catch (_) {return false;}
}
function bancoPanelRender_(chat,requested,view) {
  return bancoChatLock_(()=>{
    const s=bancoChatRead_();let result;
    const data={chat_id:String(chat.id),text:view.text.slice(0,3900),reply_markup:{inline_keyboard:view.buttons},link_preview_options:{is_disabled:true}};
    // Only a panel we own may be edited or retired. Notification buttons never own it.
    if (requested && requested===s.panel && s.last<=s.panel) {
      data.message_id=s.panel;
      try {result=bancoApi_('editMessageText',data);return result;} catch (_) {delete data.message_id;}
    }
    result=bancoApi_('sendMessage',data);
    const previous=s.panel;s.panel=result.message_id;s.last=Math.max(s.last,s.panel);
    if (previous && previous!==s.panel && !s.retired.includes(previous)) s.retired.push(previous);
    bancoChatWrite_(s);
    // Retired panels are removed immediately; ordinary replies have the 24h rule.
    s.retired=s.retired.filter(id=>id===s.panel?false:!bancoDeleteKnown_(id));bancoChatWrite_(s);
    return result;
  });
}
function bancoFinalize_() {
  if (!bancoContext_) return;
  const s=bancoChatRead_();
  if (s.panel && s.last>s.panel) bancoPanelRender_({id:ADMIN_TELEGRAM_ID},null,bancoHome_());
}
function bancoLegacySent_(chat,id,text) {
  if (String(chat)!==String(ADMIN_TELEGRAM_ID)) return;
  bancoChatLock_(()=>{
    const s=bancoChatRead_();s.last=Math.max(s.last,Number(id)||0);
    const ordinary=bancoContext_ && ['/test','/id','/correggi','/annulla'].indexOf(bancoContext_.command)!==-1;
    const problem=/errore|error|non riesco|fallit|problem|non trovato|mancant|⚠|❌/i.test(String(text));
    if (ordinary && !problem) bancoRoutine_(s,Number(id),'r');
    bancoChatWrite_(s);
  });
  bancoInvalidate_();
}
function bancoSkipLegacyDelete_(chat,id) {
  return String(chat)===String(ADMIN_TELEGRAM_ID) && bancoContext_ && Number(id)===bancoContext_.message;
}
function bancoExternalNotice_(id) {
  if (!Number.isSafeInteger(id)||id<=0) throw new Error('Identificativo messaggio non valido');
  bancoChatLock_(()=>{const s=bancoChatRead_();s.last=Math.max(s.last,id);bancoChatWrite_(s);});
  const s=bancoChatRead_();if (s.panel && s.last>s.panel) bancoPanelRender_({id:ADMIN_TELEGRAM_ID},null,bancoHome_());
  return ContentService.createTextOutput(JSON.stringify({ok:true})).setMimeType(ContentService.MimeType.JSON);
}
function bancoManutenzioneChat() {
  bancoChatLock_(()=>{
    const s=bancoChatRead_(),now=Date.now();
    const latest=Math.max(0,...s.routines.filter(r=>r[2]==='r').map(r=>r[0]));
    s.retired=s.retired.filter(id=>id===s.panel?false:!bancoDeleteKnown_(id));
    let count=0;
    s.routines=s.routines.filter(r=>{
      const id=r[0],age=now-r[1];
      if (id===s.panel || (r[2]==='r' && id===latest)) return true;
      if (age<86400000 || count>=12) return true;
      if (age>=172800000) return false; // Telegram can no longer delete it.
      count++;return !bancoDeleteKnown_(id);
    });
    bancoChatWrite_(s);
  });
}
function bancoConfiguraManutenzione() {
  const triggers=ScriptApp.getProjectTriggers().filter(t=>t.getHandlerFunction()==='bancoManutenzioneChat');
  if (!triggers.length) ScriptApp.newTrigger('bancoManutenzioneChat').timeBased().everyMinutes(15).create();
  console.log(JSON.stringify({ok:true,maintenance:'every_15_minutes',retention_hours:24,latest_reply_preserved:true}));
}
function bancoInvalidate_() {
  const cache=CacheService.getScriptCache();
  if (typeof cache.removeAll==='function') cache.removeAll(bancoBooks_().flatMap(b=>['Sisal Sport','PokerStars'].map(n=>'bn:'+BANCO_MENU_VERSION+':'+b.id+':'+n)));
}
