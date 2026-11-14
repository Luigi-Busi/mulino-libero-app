# Tester per numero di telefono — v1.3.23 candidata

**PREPARATA, NON INSTALLATA.** L'installazione resta sospesa fino al via libera
esplicito del proprietario, che ha segnalato richieste in coda.

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

## Installazione rinviata

Non sono stati pubblicati tag di rilascio né eseguiti comandi di deploy, pausa,
riavvio o modifica del container. La proposta resta in un ramo dedicato e in PR
bozza; il codice attivo continua a usare la versione precedente.

Dopo l'autorizzazione del proprietario, usare la normale procedura Git e
`ops/deploy/README.md`: verifica del tag, pausa salvata e attesa della conclusione
delle operazioni attive prima della sostituzione. Le richieste pendenti non
richiedono migrazioni né cancellazioni. Nessuna modifica ad Apps Script.
