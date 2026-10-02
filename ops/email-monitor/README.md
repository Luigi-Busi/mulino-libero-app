# Monitor mail documenti

Release indipendente del Mulino, versionata nello stesso repository sul ramo
`ops/email-monitor`, con tag `email-monitor-vX.Y.Z`. Il tag `v1.3.0` continua
a identificare l'applicazione Mugnaio. I due cicli di aggiornamento sono distinti.

La prima release è `email-monitor-v1.0.0`, schema dati 1. Legge soltanto
Sisal Sport e PokerStars; Snai è disattivato nella configurazione privata.
Usa i colori visualizzati delle celle email e password email: bianco, grigio,
viola/fucsia ammessi; azzurro, rosso, rosso scuro e altri colori esclusi.
I controlli avvengono ogni ora dalle 08:00 alle 21:00, Europe/Rome.
Alle 08:00 riprende dal cursore salvato, inclusa la posta arrivata di notte.
La prima connessione di una sottoscrizione registra il cursore senza leggere
o notificare messaggi precedenti.

Il servizio usa IMAP in sola lettura, controlla anche lo spam e invia gli avvisi
alla chat privata dell'amministratore tramite il Mugnaio. Non avvia il polling
Telegram e non scrive nei fogli. Gli invii con esito incerto richiedono verifica
amministrativa e non vengono ripetuti automaticamente.

## Separazione di sorgenti e dati

- Qui sono tracciati programma, launcher, timer, gestione release e test.
- `ops/recovery/backup_system.py` e `restore_system.py` contengono l'integrazione
  per conservare e recuperare il servizio insieme al Mulino.
- Configurazione reale e riferimenti della release: `/etc/mulino-email-monitor`.
- Registro e cursori: `/opt/mulino-libero/data/email-monitor`.
- Credenziali: file già presenti in `/opt/mulino-libero/secrets`.
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

66 test: selezione dei fogli, colori, mittenti e oggetti, IMAP readonly,
inizializzazione senza storico, limiti orari e cambio ora, riavvii,
duplicati, consegna Telegram, backup/ripristino, aggiornamento,
rollback e recupero da interruzione. Esecuzione in Linux, Python 3.12:

```sh
PYTHONPATH=ops/email-monitor:ops/recovery python3 -m unittest discover -s ops/email-monitor
```
