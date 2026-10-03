# Monitor mail documenti

Release indipendente del Mulino, versionata nello stesso repository sul ramo
`ops/email-monitor`, con tag `email-monitor-vX.Y.Z`. L'applicazione Mugnaio
mantiene il proprio ciclo di aggiornamento distinto (attualmente v1.3.2).

La release corrente è `email-monitor-v1.2.1`, schema dati 1. Legge soltanto
Sisal Sport e PokerStars; Snai è disattivato nella configurazione privata.
Usa i colori visualizzati delle celle email e password email: bianco, grigio,
viola/fucsia ammessi; azzurro, rosso, rosso scuro e altri colori esclusi.
I controlli avvengono ogni ora dalle 08:00 alle 21:00, Europe/Rome.
Alle 08:00 riprende dal cursore salvato, inclusa la posta arrivata di notte.
La prima connessione di una sottoscrizione registra il cursore senza leggere
o notificare messaggi precedenti.

Il servizio usa IMAP in sola lettura, controlla anche lo spam e invia gli avvisi
alla chat privata dell'amministratore tramite Il Banco. Non avvia il polling
Telegram. Aggiorna esclusivamente la scheda dedicata agli stati, senza cambiare
gli account nei fogli. Gli invii con esito incerto richiedono verifica
amministrativa e non vengono ripetuti automaticamente.

## Menu e dashboard del Banco

Il codice Apps Script del progetto esistente Auto-Ricezione Dati integra il
menu Banco 1.0.1. `/menu` apre i comandi; `/account` o `/stato` apre i file e i
fogli Sisal Sport e PokerStars nell'ordine effettivo, con account ordinati per riga
e otto per pagina. GoldBet, MyLotteries e Bet365 sono esclusi dalla dashboard;
i loro comandi di acquisizione esistenti restano disponibili.
Sono disponibili Attivo, Richiesta documenti, Riattivato, Non monitorato e
In attesa di controllo. Attivo indica assenza di una richiesta rilevata dal
monitor, non una verifica diretta dello stato presso l'operatore.

Username, password dell'account ed email si copiano con i pulsanti Telegram.
La password è nascosta nel testo; la password email non ha un pulsante.
Apri riga nel foglio apre la riga precisa. I dettagli vengono letti dal foglio
attuale e i pulsanti non rivelano credenziali di una riga spostata nel frattempo.
Il menu è riservato all'amministratore nella propria chat privata. Inserimento,
correzione entro 60 minuti, annullamento, test e ID conservano i controlli originali.

Gli stati vengono sincronizzati dopo ogni ciclo attraverso la webapp Banco
esistente, protetta dalla chiave già configurata. La scheda `Stato Account Banco`
nel file Log Ricerca Mail contiene email, operatore, stato, data e consegna;
non contiene password. La risposta include un digest dei dati ricevuti.
Un errore di sincronizzazione viene registrato e segnalato, mantenendo le
notifiche e il registro locale. La dashboard conserva la data dell'ultimo
controllo completato e si aggiorna con il pulsante Aggiorna.

Il file `banco/Codice.template.gs` è il codice completo senza gli identificativi
privati degli utenti; `BancoMenu.gs` è l'estensione e `test_banco.cjs` il collaudo.
Il codice effettivo precedente e aggiornato, le proprietà e i metadati del
deployment sono conservati sotto `/etc/mulino-email-monitor/banco`, nelle copie
cifrate. Non sostituire un progetto reale con il template senza configurare
l'amministratore e gli utenti autorizzati.

## Notifica della riattivazione

Dopo la consegna confermata della richiesta documento viene aperta un'attesa
per quella casella e quell'operatore. Dalle 08:00 del giorno successivo alla
notifica, Europe/Rome, viene cercato anche l'oggetto "Il tuo account e' stato
riattivato", dallo stesso mittente dell'operatore. Sono riconosciuti "è",
apostrofi tipografici, maiuscole e spazi ripetuti. La ricerca include inbox e
spam e le mail arrivate tra la richiesta documento e l'avvio del mattino.
Il confronto usa la data interna IMAP, escludendo mail antecedenti alla richiesta.

La notifica "Account riattivato" chiude l'attesa. Richieste documento ripetute
durante la stessa attesa non spostano la data di avvio. Una nuova richiesta
dopo la chiusura apre una nuova attesa. Se l'account viene escluso dai colori
o dagli altri controlli di validità, l'attesa è annullata; il suo rientro non
recupera mail del periodo di esclusione. Invii incerti richiedono verifica.

Le tabelle aggiuntive conservano attese, cursori e notifiche separatamente dal
registro originale: il rollback alla v1.0.0 conserva questi dati e sospende
la funzione di riattivazione. Non vengono aperte attese retroattive per
richieste documento già notificate prima dell'introduzione della funzione.

## Separazione di sorgenti e dati

- Qui sono tracciati programma, launcher, timer, gestione release e test.
- `ops/recovery/backup_system.py` e `restore_system.py` contengono l'integrazione
  per conservare e recuperare il servizio insieme al Mulino.
- Configurazione reale e riferimenti della release: `/etc/mulino-email-monitor`.
- Registro e cursori: `/opt/mulino-libero/data/email-monitor`.
- Credenziali IMAP e Google: file presenti in `/opt/mulino-libero/secrets`.
- Token Banco e collegamento privato: `/etc/mulino-email-monitor/banco-token`
  e `banco-webhook.json`. Non modificano i segreti dell'applicazione Mugnaio.
- Codice installato e copie delle release: `/usr/local/lib/mulino-email-monitor`.

Credenziali, configurazione reale, registro e dati dei fogli non entrano in Git.
Sono compresi nelle copie cifrate del sistema. `config.example.json` è soltanto
un riferimento per ricostruzione; aggiornamento e rollback conservano il file
di configurazione reale.

## Verifica e stato

```sh
/usr/local/sbin/mulino-email-monitor status
python3 /usr/local/lib/mulino-email-monitor/release_tool.py verify
```

Il primo comando consulta il registro. Il secondo confronta tutti i file
gestiti con gli hash della release registrata. Il servizio è oneshot: tra due
cicli è normale che il servizio risulti inattivo, con il timer attivo.

## Aggiornamento

Creare e pubblicare una nuova release sul ramo `ops/email-monitor`. Aggiornare
la costante VERSION del programma e `release-spec.json`; mantenere lo schema
dati 1 soltanto se la nuova versione è compatibile con cursori, eventi e
notifiche esistenti. Uno schema differente richiede una migrazione separata
e viene bloccato dallo strumento di gestione.

```sh
python3 /usr/local/lib/mulino-email-monitor/release_tool.py check email-monitor-v1.0.1
python3 /usr/local/lib/mulino-email-monitor/release_tool.py deploy email-monitor-v1.0.1
python3 /usr/local/lib/mulino-email-monitor/release_tool.py verify
systemctl start mulino-system-backup.service
```

La v1.0.1 qui è un esempio e non una release esistente. Usare solo un tag
effettivamente pubblicato. `check` recupera il tag e collauda il codice nel
runtime fissato del monitor, su dati fittizi e senza credenziali. `deploy`
ricontrolla i test, ferma il solo monitor, archivia le release, installa i file,
convalida le unità e riattiva il timer se prima era attivo. Preserva
configurazione privata, runtime e database, e non riavvia il Mugnaio.

Aggiornamento, rollback e backup sono serializzati tramite i lock esistenti.
Un errore durante l'installazione ripristina la release precedente. Una
interruzione brutale lascia una transazione da recuperare:

```sh
python3 /usr/local/lib/mulino-email-monitor/release_tool.py recover
```

## Rollback

```sh
python3 /usr/local/lib/mulino-email-monitor/release_tool.py rollback
python3 /usr/local/lib/mulino-email-monitor/release_tool.py verify
systemctl start mulino-system-backup.service
```

Ripristina i file della release precedente mantenendo registro e configurazione.
Il rollback dalla 1.2.1 alla 1.1.0 usa automaticamente il token Mugnaio originale:
il vecchio launcher conserva il suo percorso e ignora le nuove opzioni Banco.
La dashboard Banco resta consultabile con la data dell'ultima sincronizzazione.
Per annullare anche il menu, selezionare la versione 28 dello stesso deployment
Apps Script; il suo indirizzo e il webhook Telegram restano invariati. Per
riattivare la 1.2.1 dopo il rollback, usare deploy con il tag 1.2.1.
Nella prima installazione non esiste una release precedente del monitor.
Per disattivare questa prima release:

```sh
systemctl disable --now mulino-email-monitor.timer
systemctl stop mulino-email-monitor.service
```

Conservare sorgenti e registro per il recupero. Per riattivare:
`systemctl enable --now mulino-email-monitor.timer`.

## Backup e ripristino

Il backup verifica che il tag, il commit e i file installati coincidano,
salva i riferimenti Git nel bundle completo del progetto, le copie delle
release, la configurazione privata, il runtime e una snapshot SQLite coerente.
La procedura di ripristino riconosce tutti questi file e lascia il timer
disattivato fino alla riattivazione esplicita sul server ripristinato.

Una copia antecedente ad avvisi già consegnati può richiedere riconciliazione
del registro prima di riprendere le notifiche. La conservazione dei cursori
evita il controllo a ritroso durante i normali aggiornamenti e rollback.

## Collaudo

104 test Python: selezione dei fogli, colori, mittenti e oggetti, IMAP readonly,
inizializzazione senza storico, limiti orari e cambio ora, riavvii,
duplicati, consegna Telegram, backup/ripristino, aggiornamento,
rollback e recupero da interruzione. Esecuzione in Linux, Python 3.12:

```sh
PYTHONPATH=ops/email-monitor:ops/recovery python3 -m unittest discover -s ops/email-monitor
```

30 test del menu e dell'integrazione con i comandi esistenti, con dati fittizi:
`node ops/email-monitor/banco/test_banco.cjs`.
