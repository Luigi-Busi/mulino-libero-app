// ============================================================
// EMAIL MATCHER
// Ricerca e-mail tramite Nome e Cognome
// ============================================================
//
// - testEmailMatcher():
//     anteprima generale, NON scrive mail.
//
// - testScritturaEmailRiga():
//     test REALE su UNA SOLA riga.
//
// - cercaEmailMancanti():
//     compilazione reale di tutte le righe valide.
//
// - completaEmailRiga(nomeFoglio, numeroRiga):
//     funzione chiamata direttamente da Il Banco.
//
// Le righe con sfondo non bianco vengono ignorate.
//
// ============================================================


// ============================================================
// CONFIGURAZIONE
// ============================================================

const EM_TIMEZONE = "Europe/Rome";

// Solo questi fogli hanno il vincolo operativo dei 20 giorni.
// La normalizzazione non accorpa "Sisal Old", "Sisal Sport", "Snai", ecc.
const EM_SITI_REGOLA_20_GIORNI = ["PokerStars", "Sisal Sport", "Snai Sport"];
// Confermato dal proprietario: questi fogli contengono solo conti gia aperti.
// Lasciare vuoto se il processo di inserimento cambia.
// In alternativa usare impostaValiditaRegistrazione_() dopo verifica manuale.
const EM_FOGLI_SOLO_REGISTRAZIONI_VALIDE = ["PokerStars", "Sisal Sport", "Snai Sport"];
const EM_METADATA_KEY = "EM_REGISTRAZIONE_V1";
const EM_REVISIONI_SHEET = "RevisioniOmonimi";
const EM_REVISIONI_HEADERS = [
  "ID_REGISTRAZIONE", "AGGIORNATA_IL", "STATO", "FOGLIO", "RIGA",
  "NOME", "MOTIVO", "CONTESTO"
];

const EM_LOG_SHEET_NAME = "Log";

const EM_CREAZIONE_MAIL_PROPERTY =
  "SPREADSHEET_ID_CREAZIONE_MAIL";

const EM_CODA_SHEET_NAME = "Coda";

const EM_WHITELIST_SHEET_NAME = "Whitelist";

const EM_CODA_HEADERS = [
  "ID_RICHIESTA",
  "CREATA_IL",
  "AGGIORNATA_IL",
  "STATO",
  "SPREADSHEET_DESTINAZIONE",
  "FOGLIO_DESTINAZIONE",
  "RIGA_DESTINAZIONE",
  "COLONNA_EMAIL",
  "NOME_COMPLETO",
  "TELEGRAM_ASSEGNATO",
  "TELEFONO_MASCHERATO",
  "USERNAME_LIBERO",
  "EMAIL_CREATA",
  "TENTATIVI",
  "ERRORE",
  "MESSAGGIO_GRUPPO_ID",
  "NOTE"
];

const EM_WHITELIST_HEADERS = [
  "TELEGRAM_ID",
  "NUMERO_TELEFONO"
];

const EM_STATI_CODA_CHIUSI = [
  "CREATA",
  "ANNULLATA"
];


// ============================================================
// TEST REALE SU SINGOLA RIGA
// ============================================================

const EM_TEST_TARGET_SHEET = "Sisal Sport";
const EM_TEST_TARGET_ROW = 0;


// ============================================================
// FOGLI DA COMPLETARE
// ============================================================

const EM_TARGET_SHEETS = [
  "PokerStars",
  "Sisal Sport",
  "GoldBet",
  "MyLotteriesPlay",
  "Snai Sport"
];


// ============================================================
// ARCHIVI IN CUI CERCARE
// ============================================================

const EM_SOURCE_GROUPS = [

  {
    property: "SPREADSHEET_ID",
    label: "Matched & Arbitrage",

    sheets: [
      "PokerStars",
      "Sisal Sport",
      "GoldBet",
      "MyLotteriesPlay",
      "Sisal Lott.",

      // NUOVO FOGLIO SNAI
      "Snai Sport",

      // VECCHIO FOGLIO:
      // resta utilizzabile come archivio e-mail
      "Snai",

      "Sisal"
    ]
  },

  {
    property: "SPREADSHEET_ID_ARCHIVIO_MATCHED",
    label: "Archivio Matched",

    sheets: [
      "MyLotteriesPlay",
      "Sisal Old",
      "Sisal Old 2",
      "PokerStars",
      "LottoGold"
    ]
  },

  {
    property: "SPREADSHEET_ID_SLOTTING",
    label: "Slotting",

    sheets: [
      "Betflag Luigi"
    ]
  }
];


// ============================================================
// TEST GENERALE IN ANTEPRIMA
// ============================================================

function testEmailMatcher() {

  EM_eseguiRicercaEmail(true);
}


// ============================================================
// TEST REALE SU UNA SOLA RIGA
// ============================================================

function testScritturaEmailRiga() {

  if (
    !EM_TEST_TARGET_SHEET ||
    EM_TEST_TARGET_ROW < 1
  ) {

    throw new Error(
      "Imposta EM_TEST_TARGET_SHEET e EM_TEST_TARGET_ROW prima del test."
    );
  }


  const risultato =
    EM_completaEmailRigaInterna(
      EM_TEST_TARGET_SHEET,
      EM_TEST_TARGET_ROW,
      true
    );


  console.log(
    "TEST REALE EMAIL MATCHER\n" +
    "Foglio: " +
    EM_TEST_TARGET_SHEET +
    "\n" +
    "Riga: " +
    EM_TEST_TARGET_ROW +
    "\n" +
    "Esito: " +
    risultato.stato
  );
}


// ============================================================
// FUNZIONE REALE GENERALE
// ============================================================

function cercaEmailMancanti() {

  EM_eseguiRicercaEmail(false);
}


// ============================================================
// FUNZIONE PER IL BOT
// ============================================================

function completaEmailRiga(
  nomeFoglio,
  numeroRiga
) {

  return EM_completaEmailRigaInterna(
    nomeFoglio,
    numeroRiga,
    false
  );
}


// ============================================================
// COMPLETA UNA SINGOLA RIGA
// ============================================================

function EM_completaEmailRigaInterna(
  nomeFoglio,
  numeroRiga,
  modalitaTest
) {

  const lock =
    LockService.getScriptLock();


  let lockOttenuto = false;


  try {

    lockOttenuto =
      lock.tryLock(30000);


    if (!lockOttenuto) {

      throw new Error(
        "Email Matcher è già in esecuzione."
      );
    }


    if (
      EM_TARGET_SHEETS.indexOf(
        nomeFoglio
      ) === -1
    ) {

      throw new Error(
        'Il foglio "' +
        nomeFoglio +
        '" non è tra quelli da completare.'
      );
    }


    if (
      !Number.isInteger(
        Number(numeroRiga)
      ) ||
      Number(numeroRiga) < 1
    ) {

      throw new Error(
        "Numero riga non valido."
      );
    }


    numeroRiga =
      Number(numeroRiga);


    const props =
      PropertiesService.getScriptProperties();


    const targetSpreadsheetId =
      props.getProperty(
        "SPREADSHEET_ID"
      );


    const logSpreadsheetId =
      props.getProperty(
        "SPREADSHEET_ID_LOG_MAIL"
      );


    if (!targetSpreadsheetId) {

      throw new Error(
        "SPREADSHEET_ID mancante."
      );
    }


    if (!logSpreadsheetId) {

      throw new Error(
        "SPREADSHEET_ID_LOG_MAIL mancante."
      );
    }


    const targetSS =
      SpreadsheetApp.openById(
        targetSpreadsheetId
      );


    const foglio =
      targetSS.getSheetByName(
        nomeFoglio
      );


    if (!foglio) {

      throw new Error(
        'Foglio "' +
        nomeFoglio +
        '" non trovato.'
      );
    }


    const tabella =
      EM_trovaTabellaDestinazione(
        foglio
      );


    if (
      numeroRiga <=
      tabella.headerRow
    ) {

      throw new Error(
        "La riga indicata non appartiene alla tabella dati."
      );
    }


    if (
      numeroRiga >
      foglio.getMaxRows()
    ) {

      throw new Error(
        "La riga indicata non esiste."
      );
    }


    const ultimaColonna =
      Math.max(
        foglio.getLastColumn(),
        tabella.nameCol,
        tabella.emailCol
      );


    const rigaRange =
      foglio.getRange(
        numeroRiga,
        1,
        1,
        ultimaColonna
      );


    const valori =
      rigaRange
        .getDisplayValues()[0];


    const sfondi =
      rigaRange
        .getBackgrounds()[0];


    if (
      EM_rigaHaSfondoNonBianco(
        sfondi
      )
    ) {

      return {
        stato: "IGNORATA_COLORE"
      };
    }


    const nome =
      String(
        valori[
          tabella.nameCol - 1
        ] || ""
      ).trim();


    const emailAttuale =
      String(
        valori[
          tabella.emailCol - 1
        ] || ""
      ).trim();


    if (!nome) {

      return {
        stato: "NOME_MANCANTE"
      };
    }


    if (
      !EM_emailMancante(
        emailAttuale
      )
    ) {

      return {
        stato: "EMAIL_GIA_PRESENTE"
      };
    }


    const destinazione = EM_leggiRegistrazione_(
      foglio, tabella, numeroRiga, valori, !modalitaTest
    );
    const indice = EM_costruisciIndiceEmail(props);
    const risultato = EM_cercaNomeInIndice_(indice, nome, destinazione);
    if (!modalitaTest) EM_aggiornaRevisione_(props, destinazione, risultato);


    if (
      risultato.stato ===
      "TROVATA"
    ) {

      foglio
        .getRange(
          numeroRiga,
          tabella.emailCol
        )
        .setValue(
          risultato.email
        );


      SpreadsheetApp.flush();


      EM_scriviLog(
        logSpreadsheetId,
        [[

          EM_dataOra(),

          nomeFoglio,

          numeroRiga,

          nome,

          modalitaTest
            ? "TEST_REALE_TROVATA"
            : "TROVATA",

          risultato.fonti
        ]]
      );


      return {
        stato: "TROVATA",
        fonte: risultato.fonti
      };
    }


    if (
      risultato.stato ===
      "AMBIGUA"
    ) {

      EM_scriviLog(
        logSpreadsheetId,
        [[

          EM_dataOra(),

          nomeFoglio,

          numeroRiga,

          nome,

          modalitaTest
            ? "TEST_REALE_AMBIGUA"
            : "AMBIGUA",

          risultato.fonti
        ]]
      );


      return {
        stato: "AMBIGUA",
        fonte: risultato.fonti
      };
    }


    let statoFinale =
      modalitaTest
        ? "TEST_REALE_NON_TROVATA"
        : "NON TROVATA";


    let richiestaId = "";


    let dettaglioCoda = "";


    if (!modalitaTest) {

      try {

        richiestaId =
          EM_accodaCreazioneMail(
            props,
            targetSpreadsheetId,
            nomeFoglio,
            numeroRiga,
            tabella.emailCol,
            nome
          );


        statoFinale =
          "ACCODATA_CREAZIONE";


        dettaglioCoda =
          "Richiesta " +
          richiestaId;

      } catch (erroreCoda) {

        statoFinale =
          "ERRORE_CODA_CREAZIONE";


        dettaglioCoda =
          String(
            erroreCoda.message ||
            erroreCoda
          );


        console.error(
          "Impossibile accodare la creazione mail per " +
          nomeFoglio +
          " riga " +
          numeroRiga +
          ": " +
          dettaglioCoda
        );
      }
    }


    EM_scriviLog(
      logSpreadsheetId,
      [[

        EM_dataOra(),

        nomeFoglio,

        numeroRiga,

        nome,

        statoFinale,

        dettaglioCoda
      ]]
    );


    return {
      stato: statoFinale,
      richiestaId: richiestaId,
      dettaglio: dettaglioCoda
    };


  } finally {

    if (lockOttenuto) {

      try {

        lock.releaseLock();

      } catch (errore) {

        // niente
      }
    }
  }
}


// ============================================================
// MOTORE GENERALE
// ============================================================

function EM_eseguiRicercaEmail(
  soloAnteprima
) {

  const lock =
    LockService.getScriptLock();


  let lockOttenuto = false;


  try {

    lockOttenuto =
      lock.tryLock(30000);


    if (!lockOttenuto) {

      throw new Error(
        "Email Matcher è già in esecuzione."
      );
    }


    const props =
      PropertiesService.getScriptProperties();


    const targetSpreadsheetId =
      props.getProperty(
        "SPREADSHEET_ID"
      );


    if (!targetSpreadsheetId) {

      throw new Error(
        "SPREADSHEET_ID mancante."
      );
    }


    const logSpreadsheetId =
      props.getProperty(
        "SPREADSHEET_ID_LOG_MAIL"
      );


    if (!logSpreadsheetId) {

      throw new Error(
        "SPREADSHEET_ID_LOG_MAIL mancante."
      );
    }


    const indice =
      EM_costruisciIndiceEmail(
        props
      );


    const targetSS =
      SpreadsheetApp.openById(
        targetSpreadsheetId
      );


    const righeLog = [];


    const riepilogo = {

      controllate: 0,
      trovate: 0,
      nonTrovate: 0,
      ambigue: 0,
      saltatePerColore: 0
    };


    for (
      const nomeFoglio of EM_TARGET_SHEETS
    ) {

      const foglio =
        targetSS.getSheetByName(
          nomeFoglio
        );


      if (!foglio) {

        throw new Error(
          'Foglio destinazione "' +
          nomeFoglio +
          '" non trovato.'
        );
      }


      const tabella =
        EM_trovaTabellaDestinazione(
          foglio
        );


      const ultimaRiga =
        foglio.getLastRow();


      if (
        ultimaRiga <=
        tabella.headerRow
      ) {

        continue;
      }


      const ultimaColonna =
        Math.max(
          foglio.getLastColumn(),
          tabella.nameCol,
          tabella.emailCol
        );


      const areaDati =
        foglio.getRange(
          tabella.headerRow + 1,
          1,
          ultimaRiga -
            tabella.headerRow,
          ultimaColonna
        );


      const valori =
        areaDati.getDisplayValues();


      const sfondi =
        areaDati.getBackgrounds();


      for (
        let i = 0;
        i < valori.length;
        i++
      ) {

        const numeroRiga =
          tabella.headerRow +
          1 +
          i;


        if (
          EM_rigaHaSfondoNonBianco(
            sfondi[i]
          )
        ) {

          riepilogo.saltatePerColore++;

          continue;
        }


        const nome =
          String(
            valori[i][
              tabella.nameCol - 1
            ] || ""
          ).trim();


        const emailAttuale =
          String(
            valori[i][
              tabella.emailCol - 1
            ] || ""
          ).trim();


        if (!nome) {

          continue;
        }


        if (
          !EM_emailMancante(
            emailAttuale
          )
        ) {

          continue;
        }


        riepilogo.controllate++;


        const destinazione = EM_leggiRegistrazione_(
          foglio, tabella, numeroRiga, valori[i], !soloAnteprima
        );
        const risultato = EM_cercaNomeInIndice_(indice, nome, destinazione);
        if (!soloAnteprima) EM_aggiornaRevisione_(props, destinazione, risultato);


        if (
          risultato.stato ===
          "TROVATA"
        ) {

          riepilogo.trovate++;


          if (!soloAnteprima) {

            foglio
              .getRange(
                numeroRiga,
                tabella.emailCol
              )
              .setValue(
                risultato.email
              );
          }


          righeLog.push([

            EM_dataOra(),

            nomeFoglio,

            numeroRiga,

            nome,

            soloAnteprima
              ? "ANTEPRIMA_TROVATA"
              : "TROVATA",

            risultato.fonti
          ]);


          continue;
        }


        if (
          risultato.stato ===
          "AMBIGUA"
        ) {

          riepilogo.ambigue++;


          righeLog.push([

            EM_dataOra(),

            nomeFoglio,

            numeroRiga,

            nome,

            soloAnteprima
              ? "ANTEPRIMA_AMBIGUA"
              : "AMBIGUA",

            risultato.fonti
          ]);


          continue;
        }


        riepilogo.nonTrovate++;


        let esitoNonTrovata =
          soloAnteprima
            ? "ANTEPRIMA_NON_TROVATA"
            : "NON TROVATA";


        let dettaglioCoda = "";


        if (!soloAnteprima) {

          try {

            const richiestaId =
              EM_accodaCreazioneMail(
                props,
                targetSpreadsheetId,
                nomeFoglio,
                numeroRiga,
                tabella.emailCol,
                nome
              );


            esitoNonTrovata =
              "ACCODATA_CREAZIONE";


            dettaglioCoda =
              "Richiesta " +
              richiestaId;

          } catch (erroreCoda) {

            esitoNonTrovata =
              "ERRORE_CODA_CREAZIONE";


            dettaglioCoda =
              String(
                erroreCoda.message ||
                erroreCoda
              );


            console.error(
              "Impossibile accodare la creazione mail per " +
              nomeFoglio +
              " riga " +
              numeroRiga +
              ": " +
              dettaglioCoda
            );
          }
        }


        righeLog.push([

          EM_dataOra(),

          nomeFoglio,

          numeroRiga,

          nome,

          esitoNonTrovata,

          dettaglioCoda
        ]);
      }
    }


    if (!soloAnteprima) {

      SpreadsheetApp.flush();
    }


    EM_scriviLog(
      logSpreadsheetId,
      righeLog
    );


    console.log(
      "EMAIL MATCHER COMPLETATO\n" +
      "Modalità: " +
      (
        soloAnteprima
          ? "ANTEPRIMA"
          : "REALE"
      ) +
      "\n" +
      "Righe controllate: " +
      riepilogo.controllate +
      "\n" +
      "Trovate: " +
      riepilogo.trovate +
      "\n" +
      "Non trovate: " +
      riepilogo.nonTrovate +
      "\n" +
      "Ambigue: " +
      riepilogo.ambigue +
      "\n" +
      "Ignorate perché colorate: " +
      riepilogo.saltatePerColore
    );


  } finally {

    if (lockOttenuto) {

      try {

        lock.releaseLock();

      } catch (errore) {

        // niente
      }
    }
  }
}


// ============================================================
// CONTROLLO COLORE
// ============================================================

function EM_rigaHaSfondoNonBianco(
  colori
) {

  if (
    !colori ||
    !Array.isArray(colori)
  ) {

    return false;
  }


  for (
    const coloreRaw of colori
  ) {

    const colore =
      String(
        coloreRaw || ""
      )
        .trim()
        .toLowerCase();


    if (
      colore === "" ||
      colore === "#ffffff" ||
      colore === "white"
    ) {

      continue;
    }


    return true;
  }


  return false;
}


// ============================================================
// COSTRUISCE INDICE EMAIL
// ============================================================

function EM_costruisciIndiceEmail(
  props
) {

  const indice = Object.create(null);

  const spreadsheetCache = {};


  for (
    const gruppo of EM_SOURCE_GROUPS
  ) {

    const spreadsheetId =
      props.getProperty(
        gruppo.property
      );


    if (!spreadsheetId) {

      throw new Error(
        gruppo.property +
        " mancante."
      );
    }


    let ss =
      spreadsheetCache[
        spreadsheetId
      ];


    if (!ss) {

      ss =
        SpreadsheetApp.openById(
          spreadsheetId
        );


      spreadsheetCache[
        spreadsheetId
      ] = ss;
    }


    for (
      const nomeFoglio of gruppo.sheets
    ) {

      const foglio =
        ss.getSheetByName(
          nomeFoglio
        );


      if (!foglio) {

        throw new Error(
          'Foglio sorgente "' +
          nomeFoglio +
          '" non trovato in ' +
          gruppo.label +
          "."
        );
      }


      EM_aggiungiFoglioAllIndice(
        indice,
        foglio,
        gruppo.label
      );
    }
  }


  return indice;
}


// ============================================================
// AGGIUNGE FOGLIO ALL'INDICE
// ============================================================

function EM_aggiungiFoglioAllIndice(indice, foglio, nomeFile) {
  const righe = foglio.getLastRow();
  const colonne = foglio.getLastColumn();
  if (!righe || !colonne) return;
  const valori = foglio.getRange(1, 1, righe, colonne).getDisplayValues();
  const metadata = EM_mappaMetadata_(foglio);
  for (const tabella of EM_trovaTabelleSorgente(valori)) {
    for (let r = tabella.headerRow + 1; r <= valori.length; r++) {
      const cells = valori[r - 1];
      const nome = String(cells[tabella.nameCol - 1] || "").trim();
      const email = String(cells[tabella.emailCol - 1] || "").trim();
      if (EM_eIntestazioneNome(nome) || EM_eIntestazioneEmail(email)) break;
      const key = EM_normalizzaNome(nome);
      if (!key) continue;
      if (!indice[key]) {
        indice[key] = {emails: Object.create(null), registrazioni: []};
      }
      // Anche le righe prive di mail devono poter bloccare un riuso errato.
      const reg = EM_leggiRegistrazione_(foglio, tabella, r, cells, false, metadata);
      reg.email = EM_emailValida(email) ? email : "";
      reg.fonte = nomeFile + " → " + foglio.getName() + " riga " + r;
      indice[key].registrazioni.push(reg);
      if (!reg.email) continue;
      const emailKey = EM_normalizzaEmail(email);
      if (!indice[key].emails[emailKey]) {
        indice[key].emails[emailKey] = {email: email, fonti: Object.create(null)};
      }
      indice[key].emails[emailKey].fonti[reg.fonte] = true;
    }
  }
}


// ============================================================
// TROVA TABELLE SORGENTE
// ============================================================

function EM_trovaTabelleSorgente(
  valori
) {

  const risultati = [];


  const righeDaControllare =
    Math.min(
      100,
      valori.length
    );


  for (
    let r = 0;
    r < righeDaControllare;
    r++
  ) {

    const nameCols = [];
    const emailCols = [];


    for (
      let c = 0;
      c < valori[r].length;
      c++
    ) {

      const valore =
        valori[r][c];


      if (
        EM_eIntestazioneNome(
          valore
        )
      ) {

        nameCols.push(
          c + 1
        );
      }


      if (
        EM_eIntestazioneEmail(
          valore
        )
      ) {

        emailCols.push(
          c + 1
        );
      }
    }


    if (
      nameCols.length === 0 ||
      emailCols.length === 0
    ) {

      continue;
    }


    const emailUsate = {};


    for (
      const nameCol of nameCols
    ) {

      let miglioreEmail =
        null;


      let distanzaMigliore =
        Infinity;


      for (
        const emailCol of emailCols
      ) {

        if (
          emailUsate[emailCol]
        ) {

          continue;
        }


        const distanza =
          Math.abs(
            emailCol -
            nameCol
          );


        if (
          distanza <
          distanzaMigliore
        ) {

          distanzaMigliore =
            distanza;

          miglioreEmail =
            emailCol;
        }
      }


      if (
        miglioreEmail !== null
      ) {

        emailUsate[
          miglioreEmail
        ] = true;


        risultati.push({

          headerRow:
            r + 1,

          nameCol:
            nameCol,

          emailCol: miglioreEmail,
          // Campi riconosciuti da trovaIntestazioniStandard di Il Banco.
          usernameCol: EM_colonnaUnica_(valori[r], nameCols, nameCol,
            ["username", "user", "nome utente"]),
          dateCol: EM_colonnaUnica_(valori[r], nameCols, nameCol,
            ["data apertura", "data di apertura"])
        });
      }
    }
  }


  return risultati;
}


// ============================================================
// TABELLA DESTINAZIONE
// ============================================================

function EM_trovaTabellaDestinazione(
  foglio
) {

  const ultimaRiga =
    Math.min(
      100,
      foglio.getMaxRows()
    );


  const ultimaColonna =
    Math.max(
      1,
      foglio.getLastColumn()
    );


  const valori =
    foglio
      .getRange(
        1,
        1,
        ultimaRiga,
        ultimaColonna
      )
      .getDisplayValues();


  const tabelle =
    EM_trovaTabelleSorgente(
      valori
    );


  if (
    tabelle.length === 0
  ) {

    throw new Error(
      "Non trovo Nome e Cognome + E-mail nel foglio " +
      foglio.getName() +
      "."
    );
  }


  tabelle.sort(
    function(a, b) {

      if (
        a.headerRow !==
        b.headerRow
      ) {

        return (
          b.headerRow -
          a.headerRow
        );
      }


      return (
        a.nameCol -
        b.nameCol
      );
    }
  );


  return tabelle[0];
}


// ============================================================
// CERCA NOME NELL'INDICE
// ============================================================

function EM_cercaEmailStorica(
  indice,
  nome
) {

  const normalizzato =
    EM_normalizzaNome(
      nome
    );


  const record =
    indice[
      normalizzato
    ];


  if (!record) {

    return {
      stato: "NON TROVATA",
      email: "",
      fonti: ""
    };
  }


  const emails =
    Object.keys(
      record.emails
    );


  if (
    emails.length === 0
  ) {

    return {
      stato: "NON TROVATA",
      email: "",
      fonti: ""
    };
  }


  if (
    emails.length === 1
  ) {

    const recordEmail =
      record.emails[
        emails[0]
      ];


    return {

      stato: "TROVATA",

      email:
        recordEmail.email,

      fonti:
        Object.keys(
          recordEmail.fonti
        )
          .sort()
          .join(" | ")
    };
  }


  const tutteLeFonti = {};


  for (
    const emailKey of emails
  ) {

    const fonti =
      record.emails[
        emailKey
      ].fonti;


    for (
      const fonte in fonti
    ) {

      tutteLeFonti[
        fonte
      ] = true;
    }
  }


  return {

    stato: "AMBIGUA",

    email: "",

    fonti:
      Object.keys(
        tutteLeFonti
      )
        .sort()
        .join(" | ")
  };
}


// ============================================================
// SCRITTURA LOG
// ============================================================

function EM_scriviLog(
  spreadsheetId,
  righe
) {

  if (
    !righe ||
    righe.length === 0
  ) {

    return;
  }


  const ss =
    SpreadsheetApp.openById(
      spreadsheetId
    );


  if (
    ss.getSpreadsheetTimeZone() !==
    EM_TIMEZONE
  ) {

    ss.setSpreadsheetTimeZone(
      EM_TIMEZONE
    );
  }


  const foglio =
    ss.getSheetByName(
      EM_LOG_SHEET_NAME
    );


  if (!foglio) {

    throw new Error(
      'Nel file Log Ricerca Mail non trovo il foglio "' +
      EM_LOG_SHEET_NAME +
      '".'
    );
  }


  if (
    String(
      foglio
        .getRange("A1")
        .getDisplayValue()
    ).trim() === ""
  ) {

    foglio
      .getRange(
        1,
        1,
        1,
        6
      )
      .setValues([[
        "Data/Ora",
        "Foglio destinazione",
        "Riga",
        "Nome",
        "Esito",
        "Fonte"
      ]]);
  }


  const primaRiga =
    foglio.getLastRow() + 1;


  foglio
    .getRange(
      primaRiga,
      1,
      righe.length,
      6
    )
    .setValues(
      righe
    );


  foglio
    .getRange(
      primaRiga,
      1,
      righe.length,
      1
    )
    .setNumberFormat(
      "dd/MM/yyyy HH:mm:ss"
    );


  SpreadsheetApp.flush();
}


// ============================================================
// DATA / ORA
// ============================================================

function EM_dataOra() {

  const adesso =
    Utilities.formatDate(
      new Date(),
      EM_TIMEZONE,
      "yyyy-MM-dd HH:mm:ss"
    );


  const match =
    adesso.match(
      /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})$/
    );


  return new Date(
    Date.UTC(
      Number(match[1]),
      Number(match[2]) - 1,
      Number(match[3]),
      Number(match[4]),
      Number(match[5]),
      Number(match[6])
    )
  );
}


// ============================================================
// EMAIL MANCANTE
// ============================================================

function EM_emailMancante(
  valore
) {

  const testo =
    String(
      valore || ""
    )
      .trim()
      .toLowerCase();


  if (
    EM_emailValida(
      testo
    )
  ) {

    return false;
  }


  const placeholders = [

    "",
    "//",
    "/",
    "-",
    "--",
    ".",
    "..",
    "?",
    "??",
    "n/a",
    "na",
    "null",
    "nessuna",
    "nessuno",
    "non presente",
    "da inserire",
    "da trovare",
    "la sua"
  ];


  return (
    placeholders.indexOf(
      testo
    ) !== -1
  );
}


// ============================================================
// EMAIL VALIDA
// ============================================================

function EM_emailValida(
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
// INTESTAZIONE NOME
// ============================================================

function EM_eIntestazioneNome(
  valore
) {

  const n =
    EM_normalizzaTesto(
      valore
    );


  return (
    n === "nome cognome" ||
    n === "nome e cognome" ||
    n === "nome cliente"
  );
}


// ============================================================
// INTESTAZIONE EMAIL
// ============================================================

function EM_eIntestazioneEmail(
  valore
) {

  const n =
    EM_normalizzaTesto(
      valore
    );


  return (
    n === "email" ||
    n === "e mail" ||
    n === "email usata" ||
    n === "e mail usata"
  );
}


// ============================================================
// NORMALIZZAZIONE NOME
// ============================================================

function EM_normalizzaNome(
  valore
) {

  return EM_normalizzaTesto(
    valore
  );
}


// ============================================================
// NORMALIZZAZIONE EMAIL
// ============================================================

function EM_normalizzaEmail(
  valore
) {

  return String(
    valore || ""
  )
    .trim()
    .toLowerCase();
}


// ============================================================
// NORMALIZZAZIONE TESTO
// ============================================================

function EM_normalizzaTesto(
  valore
) {

  return String(
    valore || ""
  )
    .toLowerCase()
    .normalize("NFD")
    .replace(
      /[\u0300-\u036f]/g,
      ""
    )
    .replace(
      /[^a-z0-9]+/g,
      " "
    )
    .replace(
      /\s+/g,
      " "
    )
    .trim();
}


// ============================================================
// INIZIALIZZAZIONE SISTEMA CREAZIONE LIBERO MAIL
// Eseguire UNA VOLTA dall'editor Apps Script.
// ============================================================

function inizializzaSistemaCreazioneMail() {

  const props =
    PropertiesService
      .getScriptProperties();


  let spreadsheetId =
    props.getProperty(
      EM_CREAZIONE_MAIL_PROPERTY
    );


  let ss;


  if (spreadsheetId) {

    ss =
      SpreadsheetApp.openById(
        spreadsheetId
      );

  } else {

    ss =
      SpreadsheetApp.create(
        "Creazione Mail Libero"
      );


    spreadsheetId =
      ss.getId();


    props.setProperty(
      EM_CREAZIONE_MAIL_PROPERTY,
      spreadsheetId
    );
  }


  if (
    ss.getSpreadsheetTimeZone() !==
    EM_TIMEZONE
  ) {

    ss.setSpreadsheetTimeZone(
      EM_TIMEZONE
    );
  }


  let coda =
    ss.getSheetByName(
      EM_CODA_SHEET_NAME
    );


  if (!coda) {

    const fogli =
      ss.getSheets();


    if (
      fogli.length === 1 &&
      fogli[0].getLastRow() === 0
    ) {

      coda =
        fogli[0];


      coda.setName(
        EM_CODA_SHEET_NAME
      );

    } else {

      coda =
        ss.insertSheet(
          EM_CODA_SHEET_NAME
        );
    }
  }


  let whitelist =
    ss.getSheetByName(
      EM_WHITELIST_SHEET_NAME
    );


  if (!whitelist) {

    whitelist =
      ss.insertSheet(
        EM_WHITELIST_SHEET_NAME
      );
  }


  EM_preparaFoglioSistema(
    coda,
    EM_CODA_HEADERS
  );


  EM_preparaFoglioSistema(
    whitelist,
    EM_WHITELIST_HEADERS
  );


  // Mantiene invariati ID Telegram e numeri internazionali (es. +39...).
  whitelist
    .getRange(
      1,
      1,
      whitelist.getMaxRows(),
      2
    )
    .setNumberFormat("@");


  console.log(
    "Sistema Creazione Mail inizializzato.\n" +
    "Spreadsheet ID: " +
    spreadsheetId +
    "\nURL: " +
    ss.getUrl()
  );


  return {
    spreadsheetId: spreadsheetId,
    url: ss.getUrl()
  };
}


// ============================================================
// TEST COLLEGAMENTO CODA
// ============================================================

function testSistemaCreazioneMail() {

  const props =
    PropertiesService
      .getScriptProperties();


  const spreadsheetId =
    props.getProperty(
      EM_CREAZIONE_MAIL_PROPERTY
    );


  if (!spreadsheetId) {

    throw new Error(
      "Esegui prima inizializzaSistemaCreazioneMail()."
    );
  }


  const ss =
    SpreadsheetApp.openById(
      spreadsheetId
    );


  const coda =
    ss.getSheetByName(
      EM_CODA_SHEET_NAME
    );


  const whitelist =
    ss.getSheetByName(
      EM_WHITELIST_SHEET_NAME
    );


  if (
    !coda ||
    !whitelist
  ) {

    throw new Error(
      "Mancano i fogli Coda o Whitelist. Esegui di nuovo inizializzaSistemaCreazioneMail()."
    );
  }


  EM_verificaIntestazioniSistema(
    coda,
    EM_CODA_HEADERS
  );


  EM_verificaIntestazioniSistema(
    whitelist,
    EM_WHITELIST_HEADERS
  );


  console.log(
    "✅ Sistema Creazione Mail collegato.\n" +
    "Richieste presenti: " +
    Math.max(
      0,
      coda.getLastRow() - 1
    ) +
    "\nNumeri in whitelist: " +
    Math.max(
      0,
      whitelist.getLastRow() - 1
    )
  );
}


// ============================================================
// ACCODAMENTO CREAZIONE MAIL
// ============================================================

function EM_accodaCreazioneMail(
  props,
  targetSpreadsheetId,
  nomeFoglio,
  numeroRiga,
  colonnaEmail,
  nomeCompleto
) {

  const queueSpreadsheetId =
    props.getProperty(
      EM_CREAZIONE_MAIL_PROPERTY
    );


  if (!queueSpreadsheetId) {

    throw new Error(
      "SPREADSHEET_ID_CREAZIONE_MAIL mancante. Esegui inizializzaSistemaCreazioneMail()."
    );
  }


  const ss =
    SpreadsheetApp.openById(
      queueSpreadsheetId
    );


  const coda =
    ss.getSheetByName(
      EM_CODA_SHEET_NAME
    );


  if (!coda) {

    throw new Error(
      'Foglio "' +
      EM_CODA_SHEET_NAME +
      '" non trovato nel file Creazione Mail Libero.'
    );
  }


  EM_verificaIntestazioniSistema(
    coda,
    EM_CODA_HEADERS
  );


  const ultimaRiga =
    coda.getLastRow();


  if (ultimaRiga > 1) {

    const valori =
      coda
        .getRange(
          2,
          1,
          ultimaRiga - 1,
          EM_CODA_HEADERS.length
        )
        .getDisplayValues();


    for (
      let i = 0;
      i < valori.length;
      i++
    ) {

      const riga =
        valori[i];


      const stessaDestinazione =
        String(riga[4]) ===
          String(targetSpreadsheetId) &&
        String(riga[5]) ===
          String(nomeFoglio) &&
        Number(riga[6]) ===
          Number(numeroRiga);


      const stato =
        String(
          riga[3] ||
          ""
        ).trim();


      if (
        stessaDestinazione &&
        EM_STATI_CODA_CHIUSI.indexOf(
          stato
        ) === -1
      ) {

        return String(
          riga[0]
        );
      }
    }
  }


  const adesso =
    EM_dataOra();


  const richiestaId =
    Utilities.getUuid();


  const nuovaRiga = [[
    richiestaId,
    adesso,
    adesso,
    "DA_COMPLETARE_ANAGRAFICA",
    String(targetSpreadsheetId),
    String(nomeFoglio),
    Number(numeroRiga),
    Number(colonnaEmail),
    String(nomeCompleto),
    "",
    "",
    "",
    "",
    0,
    "",
    "",
    ""
  ]];


  const rigaDaScrivere =
    coda.getLastRow() + 1;


  coda
    .getRange(
      rigaDaScrivere,
      1,
      1,
      EM_CODA_HEADERS.length
    )
    .setValues(
      nuovaRiga
    );


  coda
    .getRange(
      rigaDaScrivere,
      2,
      1,
      2
    )
    .setNumberFormat(
      "dd/MM/yyyy HH:mm:ss"
    );


  SpreadsheetApp.flush();


  return richiestaId;
}


// ============================================================
// PREPARAZIONE / VERIFICA FOGLI DI SISTEMA
// ============================================================

function EM_preparaFoglioSistema(
  foglio,
  intestazioni
) {

  if (
    foglio.getMaxColumns() <
    intestazioni.length
  ) {

    foglio.insertColumnsAfter(
      foglio.getMaxColumns(),
      intestazioni.length -
        foglio.getMaxColumns()
    );
  }


  if (
    foglio.getLastRow() === 0 ||
    String(
      foglio
        .getRange(1, 1)
        .getDisplayValue()
    ).trim() === ""
  ) {

    foglio
      .getRange(
        1,
        1,
        1,
        intestazioni.length
      )
      .setValues([
        intestazioni
      ]);

  } else {

    EM_verificaIntestazioniSistema(
      foglio,
      intestazioni
    );
  }


  foglio.setFrozenRows(1);


  foglio
    .getRange(
      1,
      1,
      1,
      intestazioni.length
    )
    .setFontWeight("bold")
    .setBackground("#d9ead3");


  foglio.autoResizeColumns(
    1,
    intestazioni.length
  );
}


function EM_verificaIntestazioniSistema(
  foglio,
  intestazioni
) {

  const presenti =
    foglio
      .getRange(
        1,
        1,
        1,
        intestazioni.length
      )
      .getDisplayValues()[0]
      .map(
        function(valore) {

          return String(
            valore ||
            ""
          ).trim();
        }
      );


  for (
    let i = 0;
    i < intestazioni.length;
    i++
  ) {

    if (
      presenti[i] !==
      intestazioni[i]
    ) {

      throw new Error(
        'Intestazioni non valide nel foglio "' +
        foglio.getName() +
        '". Colonna ' +
        (i + 1) +
        ': attesa "' +
        intestazioni[i] +
        '", trovata "' +
        presenti[i] +
        '".'
      );
    }
  }
}


// ============================================================
// IDENTITA DELLA REGISTRAZIONE E REVISIONE OMONIMI (v1.3.21)
// Nessuna nuova colonna nei fogli account. Metadati di riga e un
// foglio separato nel file di log conservano identita e decisioni.
// ============================================================

function EM_normalizzaSito_(value) {
  return EM_normalizzaTesto(value).replace(/ /g, "");
}

function EM_normalizzaUsername_(value) {
  // Conserva punteggiatura e accenti: a.b e ab possono essere account diversi.
  const text = String(value || "").trim().toLowerCase();
  if (!text || /\s/.test(text) || EM_emailMancante(text)) return "";
  if (["username", "user", "nome utente", "da definire", "non disponibile",
       "n.d.", "nd", "n.d", "da verificare", "sconosciuto"].indexOf(text) !== -1) return "";
  return text;
}

function EM_colonnaUnica_(headers, nameCols, nameCol, aliases) {
  // Gli archivi possono contenere blocchi affiancati. Senza confini
  // espliciti non attribuire una data/username al blocco sbagliato.
  if (nameCols.length !== 1) return null;
  const found = [];
  headers.forEach(function(value, i) {
    if (aliases.indexOf(EM_normalizzaTesto(value)) !== -1) found.push(i + 1);
  });
  return found.length === 1 ? found[0] : null;
}

function EM_giornoRegistrazione_(value) {
  // Solo la Data apertura del foglio, mai data della scansione o nascita.
  // getDisplayValues: formato italiano documentato da scriviRiga di Il Banco.
  const text = String(value || "").trim();
  const m = text.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
  if (!m) return null;
  const day = Number(m[1]), month = Number(m[2]), year = Number(m[3]);
  if (year < 1900 || year > 9999) return null;
  const date = new Date(Date.UTC(year, month - 1, day));
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 ||
      date.getUTCDate() !== day) return null;
  // Giorni di calendario, indipendenti dall'ora legale in Italia.
  return Math.floor(date.getTime() / 86400000);
}

function EM_hash_(value) {
  return Utilities.computeDigest(
    Utilities.DigestAlgorithm.SHA_256, JSON.stringify(value), Utilities.Charset.UTF_8
  ).map(function(b) { return ("0" + ((b + 256) % 256).toString(16)).slice(-2); }).join("");
}

function EM_mappaMetadata_(sheet) {
  const map = Object.create(null);
  const ids = Object.create(null);
  for (const item of sheet.createDeveloperMetadataFinder().withKey(EM_METADATA_KEY).find()) {
    if (item.getKey() !== EM_METADATA_KEY) continue;
    const row = item.getLocation().getRow();
    if (!row) continue;
    const data = JSON.parse(item.getValue());
    const key = row.getRow() + ":" + data.colonna;
    if (map[key]) throw new Error("Identita registrazione duplicata: riga/blocco " + key);
    if (data.v !== 1 || !data.id || !data.firma ||
        !Number.isInteger(data.colonna) || data.colonna < 1 || ids[data.id]) {
      throw new Error("Metadati registrazione non validi o duplicati.");
    }
    ids[data.id] = true;
    map[key] = {item: item, data: data};
  }
  return map;
}

function EM_leggiRegistrazione_(sheet, table, row, values, persist, metadata) {
  const map = metadata || EM_mappaMetadata_(sheet);
  let saved = map[row + ":" + table.nameCol];
  const nome = String(values[table.nameCol - 1] || "").trim();
  const username = EM_normalizzaUsername_(table.usernameCol ? values[table.usernameCol - 1] : "");
  const dateRaw = String(table.dateCol ? values[table.dateCol - 1] || "" : "").trim();
  const giorno = EM_giornoRegistrazione_(dateRaw);
  const firma = EM_hash_([EM_normalizzaNome(nome), username, dateRaw]);
  if (!saved && persist) {
    const data = {v: 1, id: Utilities.getUuid(), firma: firma, colonna: table.nameCol};
    sheet.getRange(row, 1, 1, sheet.getMaxColumns()).addDeveloperMetadata(
      EM_METADATA_KEY, JSON.stringify(data)
    );
    saved = EM_mappaMetadata_(sheet)[row + ":" + table.nameCol];
    if (!saved) throw new Error("Identita registrazione non salvata.");
  }
  const data = saved ? saved.data : {};
  const sito = EM_normalizzaSito_(sheet.getName());
  const defaultValid = EM_FOGLI_SOLO_REGISTRAZIONI_VALIDE.some(function(n) {
    return EM_normalizzaSito_(n) === sito;
  });
  const modificata = !!data.firma && data.firma !== firma;
  return {
    id: [sheet.getParent().getId(), sheet.getSheetId(), data.id || (row + ":" + table.nameCol)].join(":"),
    spreadsheet: sheet.getParent().getId(), sheetId: sheet.getSheetId(),
    sito: sito, foglio: sheet.getName(), riga: row, nameCol: table.nameCol, nome: nome,
    username: username, giorno: giorno, firma: firma,
    // Un'attestazione negativa ha precedenza sul contratto di inserimento.
    valida: !modificata && (data.validita ? data.validita.firma === firma &&
      data.validita.completata === true : defaultValid),
    modificata: modificata, metadata: saved || null
  };
}

function EM_stessaRiga_(a, b) {
  return a.spreadsheet === b.spreadsheet && a.sheetId === b.sheetId && a.riga === b.riga && a.nameCol === b.nameCol;
}

function EM_contestoOmonimo_(indice, nome, dest) {
  const record = indice[EM_normalizzaNome(nome)];
  const regs = record ? record.registrazioni : [];
  // Non dipende dall'ordine di scansione. Un nuovo candidato o un'email
  // cambiata riapre la revisione. La riga con UUID puo essere spostata.
  return EM_hash_([dest.id, dest.firma, dest.valida,
    regs.filter(function(r) { return !EM_stessaRiga_(r, dest); }).map(function(r) {
      return [r.id, r.spreadsheet, r.sheetId, r.sito, r.firma, r.valida,
              r.modificata, EM_normalizzaEmail(r.email)];
    }).map(function(r) { return JSON.stringify(r); }).sort()
  ]);
}

function EM_cercaNomeInIndice_(indice, nome, dest) {
  if (!dest) return {stato: "AMBIGUA", email: "", fonti: "Contesto registrazione mancante"};
  const contesto = EM_contestoOmonimo_(indice, nome, dest);
  const saved = dest.metadata && dest.metadata.data.decisione;
  if (saved && saved.contesto === contesto && !dest.modificata &&
      (saved.azione === "NUOVA_MAIL" ||
       (saved.azione === "USA_EMAIL" && EM_emailValida(saved.email)))) {
    return {
      stato: saved.azione === "USA_EMAIL" ? "TROVATA" : "NON TROVATA",
      email: saved.email || "", fonti: "Decisione manuale persistente", contesto: contesto
    };
  }
  if (dest.metadata && dest.metadata.data.daRivedere) {
    return {stato: "AMBIGUA", email: "", contesto: contesto,
      fonti: "Decisione manuale da riconfermare: contesto cambiato"};
  }
  const record = indice[EM_normalizzaNome(nome)];
  const regs = record ? record.registrazioni.filter(function(r) {
    return !EM_stessaRiga_(r, dest) && r.sito === dest.sito;
  }) : [];
  const ambiguous = function(reason) {
    return {stato: "AMBIGUA", email: "", contesto: contesto,
      fonti: reason + (regs.length ? " | " + regs.map(function(r) { return r.fonte; }).join(" | ") : "")};
  };
  if (dest.modificata) return ambiguous("Riga modificata/corretta: verificare l'identita");
  if (saved) return ambiguous("Decisione manuale da riconfermare: contesto cambiato");
  if (regs.length) {
    const special = EM_SITI_REGOLA_20_GIORNI.some(function(n) {
      return EM_normalizzaSito_(n) === dest.sito;
    });
    for (const prior of regs) {
      if (!dest.username || !prior.username) return ambiguous("Username mancante o non affidabile");
      if (!dest.valida || !prior.valida) return ambiguous("Registrazione non confermata valida/completata");
      if (dest.giorno === null || prior.giorno === null) return ambiguous("Data apertura mancante o non interpretabile");
      if (dest.username === prior.username) return ambiguous("Stesso username su righe diverse: possibile duplicato/correzione");
      if (!special) return ambiguous("Sito senza regola temporale configurata");
      if (Math.abs(dest.giorno - prior.giorno) > 20) return ambiguous("Omonimo oltre 20 giorni: revisione manuale");
    }
    // Tutti i confronti nello stesso sito provano persone distinte.
    // Non recuperare la stessa mail da un'altra fonte/sito con quel nome.
    return {stato: "NON TROVATA", email: "", contesto: contesto,
      fonti: "Persone distinte: username diversi e registrazioni entro 20 giorni"};
  }
  // Tra siti diversi resta la ricerca storica; nessuna deduzione temporale.
  const result = EM_cercaEmailStorica(indice, nome);
  result.contesto = contesto;
  return result;
}

function EM_foglioRevisioni_(props, create) {
  const id = props.getProperty("SPREADSHEET_ID_LOG_MAIL");
  if (!id) throw new Error("SPREADSHEET_ID_LOG_MAIL mancante.");
  const ss = SpreadsheetApp.openById(id);
  let sheet = ss.getSheetByName(EM_REVISIONI_SHEET);
  if (!sheet && create) {
    sheet = ss.insertSheet(EM_REVISIONI_SHEET);
    EM_preparaFoglioSistema(sheet, EM_REVISIONI_HEADERS);
  }
  if (sheet) EM_verificaIntestazioniSistema(sheet, EM_REVISIONI_HEADERS);
  return sheet;
}

function EM_aggiornaRevisione_(props, dest, result) {
  const ambiguous = result.stato === "AMBIGUA";
  if (dest.metadata && dest.metadata.data.decisione &&
      dest.metadata.data.decisione.contesto !== result.contesto) {
    delete dest.metadata.data.decisione;
    dest.metadata.data.daRivedere = true;
    dest.metadata.item.setValue(JSON.stringify(dest.metadata.data));
  }
  const sheet = EM_foglioRevisioni_(props, ambiguous);
  if (!sheet) return;
  const rows = sheet.getLastRow() > 1 ?
    sheet.getRange(2, 1, sheet.getLastRow() - 1, EM_REVISIONI_HEADERS.length).getDisplayValues() : [];
  const i = rows.findIndex(function(r) { return r[0] === dest.id; });
  if (!ambiguous && i < 0) return;
  const status = ambiguous ? "DA_REVISIONARE" : "RISOLTA";
  if (i >= 0 && rows[i][2] === status && rows[i][7] === result.contesto &&
      Number(rows[i][4]) === dest.riga && rows[i][3] === dest.foglio) {
    if (ambiguous) EM_notificaRevisione_(dest, result);
    return;
  }
  sheet.getRange(i < 0 ? sheet.getLastRow() + 1 : i + 2, 1, 1, EM_REVISIONI_HEADERS.length)
    .setValues([[dest.id, EM_dataOra(), status, dest.foglio, dest.riga,
      dest.nome, result.fonti, result.contesto]]);
  if (ambiguous) EM_notificaRevisione_(dest, result);
}

function EM_notificaRevisione_(dest, result) {
  const saved = dest.metadata;
  if (!saved || saved.data.avviso === result.contesto) return;
  if (typeof inviaTelegram !== "function" || typeof ADMIN_TELEGRAM_ID === "undefined") {
    console.warn("Revisione omonimo salvata; notifiche di Il Banco non disponibili.");
    return;
  }
  try {
    inviaTelegram(ADMIN_TELEGRAM_ID,
      "⚠️ Omonimo da revisionare\n" + dest.foglio + " · riga " + dest.riga +
      "\n" + dest.nome + "\n" + result.fonti.slice(0, 2500) +
      "\nIn questa verifica nessuna mail assegnata o accodata. Vedi RevisioniOmonimi nel file di log.");
    saved.data.avviso = result.contesto;
    saved.item.setValue(JSON.stringify(saved.data));
  } catch (error) {
    // Il dubbio resta bloccato e visibile nel foglio. La scansione ritenta l'avviso.
    console.warn("Avviso omonimo non inviato; revisione salvata nel file di log.");
  }
}

// Da eseguire solo dopo verifica manuale, per qualsiasi sorgente configurata.
// Non usa password, non aggiunge colonne e non crea richieste in coda.
function impostaValiditaRegistrazione_(spreadsheetProperty, nomeFoglio, numeroRiga, completata) {
  if (typeof completata !== "boolean") throw new Error("completata deve essere true oppure false.");
  return EM_conLock_(function() {
    const ctx = EM_contestoRigaManuale_(spreadsheetProperty, nomeFoglio, numeroRiga, false);
    const reg = ctx.reg;
    const data = reg.metadata.data;
    data.firma = reg.firma;
    data.validita = {firma: reg.firma, completata: completata};
    delete data.decisione;
    reg.metadata.item.setValue(JSON.stringify(data));
    SpreadsheetApp.flush();
    return {stato: completata ? "REGISTRAZIONE_CONFERMATA" : "REGISTRAZIONE_NON_VALIDA"};
  });
}

// azione: USA_EMAIL (email obbligatoria) oppure NUOVA_MAIL.
// Salva la scelta; la successiva esecuzione del matcher la applichera.
// Il contesto e ricalcolato sotto lock: nessuna scelta per il solo nome.
function decidiOmonimo_(nomeFoglio, numeroRiga, azione, email) {
  if (["USA_EMAIL", "NUOVA_MAIL"].indexOf(azione) === -1 ||
      (azione === "USA_EMAIL" && !EM_emailValida(email))) {
    throw new Error("Usa USA_EMAIL con email valida, oppure NUOVA_MAIL.");
  }
  return EM_conLock_(function() {
    const ctx = EM_contestoRigaManuale_("SPREADSHEET_ID", nomeFoglio, numeroRiga, true);
    const reg = ctx.reg, data = reg.metadata.data;
    if (data.firma !== reg.firma) delete data.validita;
    data.firma = reg.firma;
    reg.modificata = false;
    reg.valida = data.validita ? data.validita.completata === true :
      EM_FOGLI_SOLO_REGISTRAZIONI_VALIDE.some(function(n) { return EM_normalizzaSito_(n) === reg.sito; });
    const indice = EM_costruisciIndiceEmail(ctx.props);
    const contesto = EM_contestoOmonimo_(indice, reg.nome, reg);
    delete data.daRivedere;
    data.decisione = {contesto: contesto, azione: azione,
      email: azione === "USA_EMAIL" ? EM_normalizzaEmail(email) : ""};
    reg.metadata.item.setValue(JSON.stringify(data));
    EM_aggiornaRevisione_(ctx.props, reg, {
      stato: "DECISA", contesto: contesto, fonti: "Decisione manuale: " + azione
    });
    SpreadsheetApp.flush();
    return {stato: "DECISIONE_SALVATA"};
  });
}

function EM_contestoRigaManuale_(property, name, row, targetOnly) {
  const allowed = EM_SOURCE_GROUPS.some(function(g) {
    return g.property === property && g.sheets.indexOf(name) !== -1;
  });
  if (!allowed || (targetOnly && EM_TARGET_SHEETS.indexOf(name) === -1)) {
    throw new Error("Foglio non configurato.");
  }
  const props = PropertiesService.getScriptProperties();
  const id = props.getProperty(property);
  if (!id) throw new Error(property + " mancante.");
  const sheet = SpreadsheetApp.openById(id).getSheetByName(name);
  if (!sheet) throw new Error("Foglio non trovato.");
  const table = EM_trovaTabellaDestinazione(sheet);
  if (!Number.isInteger(Number(row)) || Number(row) <= table.headerRow || Number(row) > sheet.getLastRow()) {
    throw new Error("Riga non valida.");
  }
  const values = sheet.getRange(Number(row), 1, 1, sheet.getLastColumn()).getDisplayValues()[0];
  if (!String(values[table.nameCol - 1] || "").trim()) throw new Error("Nome mancante.");
  return {props: props, reg: EM_leggiRegistrazione_(sheet, table, Number(row), values, true)};
}

function EM_conLock_(work) {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) throw new Error("Email Matcher e gia in esecuzione.");
  try { return work(); } finally { lock.releaseLock(); }
}
