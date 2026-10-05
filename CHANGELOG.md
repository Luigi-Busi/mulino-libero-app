## v1.3.5 — ripresa esplicita delle richieste ignorate

- Un /riprova accettato rimuove il vecchio contrassegno Ignora: un successivo errore della stessa richiesta rimane visibile nel recupero.
- Quando cambia la firma della richiesta, il contrassegno vecchio viene eliminato anziche poter ricomparire se lo stato torna uguale.
- Comprende tutte le modifiche di pulizia e recupero della v1.3.4.

## v1.3.4 — pulizia a 12 ore e gestione del recupero

- Le risposte ordinarie della coda si eliminano dopo 12 ore, conservando sempre l'ultima e proteggendo gli avvisi.
- L'avviso d'uso di /recupera si elimina dopo 30 minuti, anche dopo riavvio o ripristino.
- Un nuovo tentativo confermato e accettato chiude solo il relativo elenco e le conferme di riprova; la conferma di casella gia creata conserva l'elenco. Esiti e errori restano visibili.
- Ignora richiesta nasconde in modo reversibile richieste fallite o annullate; /recupera ignorate permette di ripristinarle senza riavvio. Richieste attive e salvataggi di caselle create protetti.
- Solo metadati dei messaggi e hash della richiesta persistono; nuovi registri inclusi nei backup esistenti e leggibili dalla v1.3.3.

## v1.3.3 — cambio tester dopo cinque minuti

- Cambio automatico dopo cinque minuti dal primo SMS se Libero consente di modificare il numero in sicurezza; reinvio e codice rifiutato non estendono il limite.
- Codici tardivi e vecchie assegnazioni respinti; verifica gia iniziata non interrotta e nessun incremento dei conteggi senza completamento.
- Ritorno riconosciuto alla schermata iniziale durante il cambio: esito da verificare, senza ripetere Registrati.

## v1.3.2 — pulizia delle risposte ordinarie sullo stato della coda

- Le risposte ordinarie di /pausa, /stato e /riprendi condividono una categoria: l'ultima resta sempre, le precedenti sono eliminate dopo 24 ore e prima del limite Telegram di 48 ore.
- Pulizia periodica anche senza nuovi comandi e mentre la coda è in pausa; data di invio Telegram e soli identificativi conservati nello stesso database protetto.
- Errori, avvisi di operazioni attive o salvataggi pendenti, pannello, altri comandi, gruppi e tester esclusi. Nessuna lettura o pulizia retroattiva della cronologia.
- Riavvio e ripristino conservano età e ultima risposta; errori di rete non ripetono il comando. La v1.3.1 legge e verifica i nuovi backup ignorando la tabella aggiuntiva.
- Collegamento e apertura del browser restano invariati.

## v1.3.1 — menu in fondo alla chat e pulizia dei comandi

- /menu invia un nuovo pannello, salva il riferimento e solo dopo rimuove il precedente; i pulsanti continuano a modificare il pannello corrente.
- Rimozione dei nuovi comandi gestiti del proprietario solo nella sua chat privata, dopo completamento del relativo handler. Nessuna scansione della cronologia.
- Cancellazioni pendenti conservate con soli ID, retry dopo errori transitori e protezione del pannello corrente dopo riavvio o ripristino.
- Invio fallito conserva pannello e comando precedenti; salvataggio fallito conserva il vecchio pannello. Gruppi, tester, testo normale, SMS/CAPTCHA e avvisi non sono inclusi.
- /pannello e /start mantengono il riuso del messaggio. Registro tester e backup restano compatibili con v1.3.0.

## v1.3.0 — conteggi tester

- Credito unico per richiesta dopo registrazione riuscita con verifica SMS riconosciuta, attribuito al tester finale.
- Esito e credito salvati insieme nel registro SQLite; nessun credito retroattivo per esiti precedenti, recuperi manuali senza prova o registrazioni senza SMS.
- /conteggio ID, /conteggi e /azzera ID riservati al proprietario nella chat privata e integrati nel pannello riutilizzabile.
- Pulsante Tester con elenco paginato, dettaglio e azzeramento con doppio passaggio. Nuovi completamenti invalidano una conferma aperta.
- Reset conservati nello storico; nessuna modifica o cancellazione degli esiti. Backup SQLite e rollback v1.2.1 compatibili; durante il rollback i nuovi completamenti non vengono conteggiati.

# Modifiche di Mulino Libero

## v1.2.1 - 30 settembre 2026

- Un unico messaggio del pannello, riutilizzato da /menu anche dopo riavvio;
  riferimento numerico legato al proprietario e al bot nelle impostazioni esistenti.
- Chiudi riduce il messaggio a una riga con Apri pannello; riapertura e Menu
  aggiornano i pulsanti anche dopo scadenza, senza autorizzare azioni scadute.
- Browser e pausa/ripresa mostrano l'esito nel pannello; backup in corso e
  risultato usano lo stesso messaggio, senza risposte aggiuntive di routine.
- Un risultato backup arrivato dopo una navigazione o chiusura resta consultabile
  da Backup, senza sovrascrivere la pagina corrente. Errori importanti restano avvisi.
- Ricreazione del messaggio solo se Telegram lo dichiara eliminato/non modificabile;
  gli errori di rete conservano il riferimento e non duplicano il pannello.

Schema dati, Compose, monitor e controller invariati. I comandi diretti continuano
a rispondere come prima; nessuna pulizia retroattiva della chat o modifica a SMS/CAPTCHA.

## v1.2.0 - 30 settembre 2026

- Pannello /menu (anche /pannello e /start in privato) per il proprietario:
  stato, pausa/ripresa, browser, controlli e backup del registro.
- Pulsanti vincolati al messaggio, con scadenza di 15 minuti e consumo singolo;
  conferma separata per la copia manuale, senza duplicazioni da doppio clic.
- Il monitor pubblica solo sette codici e l'orario in una directory dedicata,
  montata in sola lettura. Dati mancanti, non validi o vecchi sono segnalati.
- Il deploy ammette solo questo bind aggiuntivo e verifica modulo e VERSION;
  rollback compatibile con le release precedenti.

Nessuna migrazione, nuova porta, dipendenza o modifica ai segreti. Il backup
manuale è la copia locale del registro già esistente; il backup completo cifrato
e il trasferimento PC rimangono nei servizi indipendenti. Guida: ops/panel/README.md.

## v1.1.2 - 30 settembre 2026

- Diagnostica delle fasi e di chiusura/crash pagina, contesto e browser, con
  codici statici e identificativi pseudonimi; nessun contenuto o dato personale.
- La pulizia del browser non maschera l'errore iniziale e ha tempi limitati.
- Il launcher registra il primo componente terminato e preserva il codice di
  uscita; distingue i segnali di arresto richiesti dalle chiusure inattese.
- Osservatore Docker separato in sola lettura, rapporti riservati e rotazione
  limitata; test di crash e arresto su ambienti fittizi.
- Il deploy verifica anche l'hash del nuovo modulo e resta compatibile con i tag precedenti.

Nessuna migrazione, modifica a Compose o ai segreti, né nuovi tentativi automatici.
Procedura, recupero e limiti in ops/diagnostics/README.md.

## v1.1.1 - 30 settembre 2026

- Gli avvisi del Mugnaio usano il browser HTTPS privato tramite Tailscale.
- Il comando /browser restituisce il collegamento solo all'amministratore in privato,
  senza avviare registrazioni; distingue il collegamento dalla navigazione privata di Opera.
- Il deploy ammette esclusivamente il passaggio fra i due indirizzi verificati,
  mantenendo invariato ogni altro byte di Compose. Il rollback ripristina anche il link.
- Il controllo preliminare usa la configurazione della release candidata e il
  controllo di salute verifica il link effettivo nel container.

Nessuna migrazione dei dati, nuova porta o modifica ai segreti e al Risponditore.

## v1.1.0 - 26 settembre 2026

- Monitoraggio indipendente di bot, browser, disco e backup con Healthchecks.
- Segnali temporanei dei cicli dei bot, senza richieste Telegram aggiuntive.
- Ricevuta della copia PC solo dopo verifica degli archivi cifrati.
- Avvisi privati Telegram, conferma di guasto/rientro e guida alla manutenzione.
- Compatibilita del deploy con la nuova libreria e con i tag precedenti.

Nessuna migrazione dei dati. Procedura e limiti in ops/monitoring/README.md.

## v1.0.2 — 26 settembre 2026

- Le schermate non riconosciute durante la registrazione lasciano aperto il
  browser e mantengono la richiesta in attesa di verifica.
- Dopo l'invio finale il bot attende un esito o la verifica telefonica, senza
  premere di nuovo Registrati. Il completamento senza SMS resta supportato.
- Aggiunta conferma manuale in due passaggi nella chat privata amministrativa,
  con l'indirizzo esatto e salvataggio dell'esito prima della pulizia dei messaggi.
- Gli errori invitano a verificare la casella con /recupera prima di riprovare.
- Aggiunti 21 test, inclusa una prova Chromium su pagine simulate senza rete.

Nessuna migrazione dei dati e nessuna modifica a Compose, dipendenze o Risponditore.
Non sono stati aggiunti segnali di successo dedotti da una schermata non osservata:
l'esito sconosciuto richiede ancora una verifica, ma la sessione resta disponibile.

## v1.0.1 — 26 settembre 2026

- Aggiunti gli strumenti di deploy e rollback controllati in `ops/deploy/`.
- Introdotti controlli automatici, immagini conservate, last-known-good e recupero
  delle operazioni interrotte.
- Corretti i test di regressione per caricare tutte le classi attuali del worker,
  con Telegram e Google Sheets simulati.
- Documentata la procedura di aggiornamento, pausa e ripristino.

Questa release non cambia il codice dei bot, Dockerfile, dipendenze o Compose.
Non introduce migrazioni dei dati.

## v1.0.0

Prima versione stabile pubblicata su GitHub.
