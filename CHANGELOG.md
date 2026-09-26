# Modifiche di Mulino Libero

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
