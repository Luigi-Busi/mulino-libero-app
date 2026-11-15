# Betflag — v1.3.27

## Formato reale e scrittura

Verificato in sola lettura il foglio Betflag in Matched & Arbitrage:
intestazioni alla riga 11, Data Registrazione A, Nome e Cognome B, Username C,
Password D, E-mail E, Pass E-mail F, Iban PP G, 16 cifre postepay H,
Tipologia I, Provenienza J. Il parser riconosce Betflag con emoji/spazi/maiuscole
normalizzati, senza attivare Betflag Grandi né le vecchie schede.

Due modelli: SPID/CIEID richiede un valore univoco e scrive // in H e spid/cieid
in I; il modello con Nome cliente e 16 cifre pp scrive il testo ricevuto in H
e Normie in I. Entrambi compilano B:D, G e J con la normale provenienza UTENTI.
La data in A deriva da message.date Telegram, convertita a Europe/Rome,
anche se la gestione dell'update avviene dopo mezzanotte. Nessun ripiego
silenzioso su una data diversa se il timestamp manca.

IBAN e carta sono stringhe, mantenendo zeri iniziali e spazi. Il numero PP
deve contenere 16 cifre (spazi ammessi); nessuna verifica bancaria/Luhn nuova.
Le celle sono formattate come testo prima della scrittura e l'eventuale = iniziale
è trattato come testo. Messaggi incompleti, campi duplicati e modelli misti
sono rifiutati prima della prima scrittura. La posizione delle dieci intestazioni
viene verificata: spostamenti o duplicati bloccano la scrittura.

La correzione usa la riga già salvata, conserva A e aggiorna G:J insieme,
quindi il cambio da Normie a SPID/CIEID elimina il vecchio numero in H.
E:F e le colonne dei bonus restano affidate ai flussi esistenti.
IBAN e carta non entrano nelle conferme Telegram né nei log.

## Mail e archivi

Betflag è destinazione/sorgente EmailMatcher e viene incluso nel menu Banco
e nell'audit del Mugnaio. La Coda e la scrittura mail in E rimangono generiche,
con ID_MULINO e ID_ACCOUNT gestiti dal sistema esistente.
Slotting: Betflag Normie (header 1), Luigi (header 2) e Davide (header 2)
restano solo sorgenti. Nessuna destinazione Banco/EmailMatcher, migrazione
o correzione delle loro righe. La correzione rifiuta un riferimento storico
a un foglio diverso dal nuovo Betflag.

I tre archivi appartengono alla famiglia Betflag per il controllo degli omonimi:
un nome uguale nel vecchio operatore richiede revisione prima di riutilizzare
la mail. Per altri operatori resta la ricerca storica delle mail disponibili.
Non viene estesa a Betflag la regola automatica dei 20 giorni, non confermata
per questo operatore. Rimangono disponibili i pulsanti e le decisioni persistenti.

## Verifica e pubblicazione

43 casi nuovi: modelli, duplicati/mancanti, zeri/spazi, data e fuso,
webhook con chiave errata, inserimento completo e provenienza, cambio tipologia,
conservazione delle altre celle, archivi, accodamento idempotente e ricerca mail.
Baseline di test con sole funzioni/configurazioni della versione 41;
il sorgente completo privato del Banco resta fuori dal repository.
Patcher: ops/apps-script/banco-betflag-patch.cjs; funzioni aggiunte nel file
banco-betflag-helpers.gs, incluse in Codice.gs senza creare un secondo progetto.
Menu cache: 1.2.3; Betflag mostra lo stato non monitorato, senza inventare
un collegamento al monitor email di un altro operatore.

Ripristino: precedente deployment Apps Script e precedente tag worker separati,
senza cancellare inserimenti/mail già completati. Nessuna modifica a data/ o secrets/.
Il primo messaggio reale resta la verifica operativa del flusso pubblicato.

Stato installazione: in preparazione.
