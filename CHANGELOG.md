# Modifiche di Mulino Libero

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
