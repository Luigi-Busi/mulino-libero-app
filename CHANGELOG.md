# Modifiche di Mulino Libero

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
