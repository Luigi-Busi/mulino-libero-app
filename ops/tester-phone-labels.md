# Tester per numero di telefono — v1.3.23

**INSTALLATA il 14 novembre 2026**, dopo il via libera esplicito del proprietario.
Il controller ha confermato v1.3.23 (commit cd63187) e conserva v1.3.20 come ripristino.
La pausa già presente è stata mantenuta; nessuna registrazione era in corso.

## Comportamento preparato

Nel menu privato Tester il numero della Whitelist diventa l'etichetta principale
del pulsante, del dettaglio e della conferma di azzeramento. Accanto al pulsante
rimane il conteggio delle operazioni completate.

- Numero valido disponibile: numero internazionale completo.
- Numero assente, non utilizzabile o tester presente soltanto nello storico:
  `ID … · numero non disponibile`.
- Stesso numero associato a più tester: numero seguito dall'ID, per distinguere
  le persone e indirizzare l'azzeramento al tester selezionato.
- Whitelist temporaneamente non raggiungibile: storico accessibile con ID e
  avviso già esistente; nessun testo grezzo dell'errore viene mostrato.

Gli ID Telegram continuano a identificare sessioni, conteggi e azzeramenti.
La lettura non modifica la Whitelist e i numeri non vengono copiati nel registro
dei conteggi. I comandi manuali `/conteggio ID` e `/azzera ID` conservano il loro
formato. Ordinamento e paginazione rimangono stabili.

I numeri completi compaiono soltanto nel pannello privato già riservato al
proprietario. La modifica non interessa messaggi dei gruppi, SMS, assegnazioni,
registrazioni o schermate degli altri utenti.

## Verifica locale

- 11 test del pannello Tester superati: etichette, dettaglio e conferma,
  numeri duplicati/assenti/non validi, aggiornamento del numero, autorizzazioni,
  pagine, azzeramenti e pulsanti scaduti.
- 14 test del pannello generale superati: accesso privato, callback, stato,
  pausa/ripresa e protezioni dei messaggi.
- Tutti i numeri nei test sono sintetici. Nessuna lettura della Whitelist reale,
  nessun comando al bot attivo, nessun accesso a dati o segreti di produzione.

```text
python -m unittest discover -s tests -p test_tester_stats.py -k TesterPanelTests -v
python -m unittest discover -s tests -p test_telegram_panel.py -k PanelTests -v
```

## Installazione verificata

Il proprietario ha autorizzato l'installazione dopo la preparazione separata.
Pubblicato il tag v1.3.23 e usati mulino-deploy check e il normale deploy con
pausa persistente, assenza di operazioni in corso e compatibilità dei dati.
Il controller ha confermato Git, immagine, mount e configurazione coerenti,
senza transazioni pendenti. Le verifiche del rilascio Linux sono superate.

Il nuovo container mantiene la pausa trovata prima dell'intervento.
L'installazione non ha richiesto migrazioni, cancellazioni o modifiche alla Whitelist.
Per visualizzare le nuove etichette aprire /menu e poi Tester.
La ripresa della coda resta un'azione esplicita del proprietario.
