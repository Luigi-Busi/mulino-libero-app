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


    const indice =
      EM_costruisciIndiceEmail(
        props
      );


    const risultato =
      EM_cercaNomeInIndice(
        indice,
        nome
      );


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


        const risultato =
          EM_cercaNomeInIndice(
            indice,
            nome
          );


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

  const indice = {};

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

function EM_aggiungiFoglioAllIndice(
  indice,
  foglio,
  nomeFile
) {

  const ultimaRiga =
    foglio.getLastRow();


  const ultimaColonna =
    foglio.getLastColumn();


  if (
    ultimaRiga < 1 ||
    ultimaColonna < 1
  ) {

    return;
  }


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


  for (
    const tabella of tabelle
  ) {

    for (
      let r =
        tabella.headerRow + 1;
      r <= valori.length;
      r++
    ) {

      const nomeRaw =
        String(
          valori[r - 1][
            tabella.nameCol - 1
          ] || ""
        ).trim();


      const emailRaw =
        String(
          valori[r - 1][
            tabella.emailCol - 1
          ] || ""
        ).trim();


      if (
        EM_eIntestazioneNome(
          nomeRaw
        ) ||
        EM_eIntestazioneEmail(
          emailRaw
        )
      ) {

        break;
      }


      if (!nomeRaw) {

        continue;
      }


      if (
        !EM_emailValida(
          emailRaw
        )
      ) {

        continue;
      }


      const nomeNormalizzato =
        EM_normalizzaNome(
          nomeRaw
        );


      const emailNormalizzata =
        EM_normalizzaEmail(
          emailRaw
        );


      if (
        !nomeNormalizzato ||
        !emailNormalizzata
      ) {

        continue;
      }


      if (
        !indice[
          nomeNormalizzato
        ]
      ) {

        indice[
          nomeNormalizzato
        ] = {
          emails: {}
        };
      }


      if (
        !indice[
          nomeNormalizzato
        ].emails[
          emailNormalizzata
        ]
      ) {

        indice[
          nomeNormalizzato
        ].emails[
          emailNormalizzata
        ] = {

          email:
            emailRaw,

          fonti: {}
        };
      }


      const fonte =
        nomeFile +
        " → " +
        foglio.getName();


      indice[
        nomeNormalizzato
      ].emails[
        emailNormalizzata
      ].fonti[
        fonte
      ] = true;
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

          emailCol:
            miglioreEmail
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

function EM_cercaNomeInIndice(
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
