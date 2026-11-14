# Revisione degli omonimi da Telegram — v1.3.22

## Uso quotidiano

L'avviso privato di Il Banco mostra nome, foglio, riga, username e mail trovate,
con una fonte per ciascun indirizzo. I risultati sono deduplicati e paginati
cinque alla volta. Le mail restano nel testo completo anche se l'etichetta
del pulsante è abbreviata.

1. Premi **Usa indirizzo** oppure **Crea nuova mail**.
2. Controlla il riepilogo e premi **Conferma**. **Indietro** annulla la scelta
   provvisoria e torna ai risultati.

La conferma salva la decisione per quell'account e la applica subito:
scrive l'indirizzo scelto oppure registra la richiesta nel Mugnaio. Il lavoro
di creazione continua con il flusso già esistente del Mugnaio. I pulsanti
vengono rimossi al completamento.

Le richieste già presenti mantengono il proprio identificativo: un clic ripetuto
non produce una seconda richiesta. L'esito distingue richieste aperte, completate
e da riprendere. Se una creazione è ancora aperta, l'assegnazione di un'altra mail
viene bloccata finché la richiesta non è gestita nel Mugnaio.

## Persistenza e controlli

- Le decisioni definitive restano nei metadati dell'account, come nella v1.3.21.
- Le sessioni dei pulsanti sono salvate nelle proprietà dello script con prefisso
  dedicato. Contengono identificativi, firma del contesto, stato e scelta provvisoria;
  nessuna password, credenziale o corpo grezzo di errore viene riportato in chat.
- Solo il proprietario, nella propria chat privata di Il Banco e sul messaggio
  originale, può usare i pulsanti. Il Segretario conserva il proprio percorso.
- L'identità viene risolta tramite ID_MULINO; gli spostamenti di righe intere
  vengono riletti. ID duplicati, righe non elaborabili, dati o candidati cambiati
  impediscono l'applicazione della vecchia scelta.
- Prima di assegnare una mail si rilegge ancora la destinazione. Una mail già
  presente non viene sovrascritta; una correzione intervenuta durante il controllo
  mantiene il caso bloccato.
- Gli avvisi aperti scadono dopo 24 ore. Una scelta definitiva non scade.
  Un clic scaduto, se il caso è ancora ambiguo, propone una revisione aggiornata.
  Le sessioni vecchie di oltre sette giorni vengono eliminate al successivo
  nuovo avviso, senza toccare altre proprietà dello script.
- Un errore dopo il salvataggio lascia **Riprova**: la decisione resta salvata
  e l'applicazione riusa l'account e la richiesta originali. Un errore del solo
  messaggio Telegram non ripete l'effetto sui fogli.

Gli avvisi testuali già inviati dalla v1.3.21 non contenevano un identificativo
del messaggio salvato per questo scopo. Vengono riproposti con i pulsanti alla
successiva verifica della riga; non si associa una tastiera a un messaggio
storico senza poterlo identificare con certezza.

## Integrazione con Il Banco

Il file EmailMatcher contiene il gestore privato dei callback `emh:`.
Il solo inserimento richiesto in Codice.gs è descritto da
`ops/apps-script/banco-omonimi-hook.json`: si colloca dopo la verifica della
chiave webhook e la deduplicazione degli aggiornamenti, prima del gestore
del menu esistente. La diramazione del Segretario resta precedente e separata.

Il sorgente completo di Codice.gs e la configurazione privata del progetto non
sono copiati nel repository. L'installazione applica il piccolo inserimento
alla versione corrente verificata, mantenendo il resto identico.

Non servono nuovi token, bot, ambiti OAuth, webhook o aggiornamenti del VPS.
Si pubblica una nuova versione sul deployment Apps Script già esistente.
Il ripristino richiede sorgenti e versione precedenti del progetto Google;
le proprietà delle sessioni sono aggiuntive e possono restare senza cancellazioni.

## Verifica

- 72 casi di regressione della logica EmailMatcher.
- 49 casi sui pulsanti: scelta/conferma, pagine, autorizzazione, vecchi messaggi,
  correzioni, spostamenti, scadenza, riavvio, errori di persistenza e idempotenza.
- 7 controlli sul doPost effettivo del Banco, eseguiti con servizi simulati:
  chiave webhook, JSON non valido, aggiornamenti duplicati, separazione del
  Segretario e continuità dei comandi e dei menu esistenti.
- Compilazione dell'intero progetto con i due file modificati.

Esecuzione offline integrata nel normale sistema di test:

```text
python -m unittest discover -s tests -p test_emailmatcher.py -v
```

I test non inviano notifiche reali né creano caselle di prova.

Riferimento per tastiere, callback e risposte ai clic:
[Telegram Bot API](https://core.telegram.org/bots/api).
