# Mulino Libero — deploy e rollback

La procedura aggiorna il Mugnaio in Docker a partire da tag Git pubblicati.
Il repository applicativo e `/opt/mulino-libero/app`. Dati, configurazione e
segreti rimangono nei percorsi attuali. Il Risponditore systemd e gestito separatamente.

## Comandi quotidiani

Stato:

```bash
mulino-deploy status
```

Preparare e verificare un nuovo tag, senza sostituire il container attivo:

```bash
mulino-deploy check v1.0.1
```

`v1.0.1` e la prima release che include questi strumenti. Per release successive
usare il tag corrispondente, che deve essere pubblicato su `origin`.
Preparare le modifiche in una copia di sviluppo separata del repository, quindi
pubblicare commit e tag. Lasciare pulito il checkout in produzione.
Il comando recupera quel tag, verifica che corrisponda al tag locale, costruisce
l'immagine, esegue tutti i test trovati in `tests/` e il controllo `--check`.
Non basta una suite vuota: almeno un test deve essere presente e superato.

Per installare una nuova versione:

1. Verificare che le modifiche ai dati siano compatibili anche con la versione
   precedente. Migrazioni distruttive o incompatibili richiedono un piano distinto:
   questa procedura non ripristina database, fogli Google o dati applicativi.
2. In privato al Mugnaio inviare `/pausa`, poi `/stato`. Attendere che non ci siano
   registrazioni attive o in chiusura e che la pausa risulti salvata.
3. Eseguire sul VPS:

```bash
mulino-deploy v1.0.1 --idle-confirmed --data-compatible
```

4. Dopo il successo verificare il bot con `/stato`, quindi inviare `/riprendi`.

Il controllo della pausa viene effettuato anche dal programma, aprendo il
registro con un mount di sola lettura. `--idle-confirmed` attesta la verifica
dell'assenza di operazioni in corso: la versione attuale del bot non espone un
endpoint locale per controllare automaticamente quello stato in memoria.

Rollback manuale, dopo `/pausa` e `/stato`:

```bash
mulino-rollback --idle-confirmed
```

Dopo il rollback verificare `/stato` e usare `/riprendi` quando opportuno.
Un rollback riuscito conserva a sua volta come precedente la release abbandonata;
un secondo rollback torna quindi a quest'ultima. Controllare sempre `status`.

Se manca una versione precedente, il rollback controlla quella corrente senza
riavviare. Anche il deploy del tag gia attivo effettua soltanto verifiche.

## Guasti e ripristino

Un errore di build, test o controllo preliminare ferma l'operazione prima della
sostituzione del container. In caso di avvio o controllo di salute fallito dopo
la sostituzione, la procedura ripristina automaticamente commit e immagine
precedenti e ne controlla la salute. Il comando termina comunque con errore:
la nuova versione non e stata installata.

Per recuperare un'operazione interrotta bruscamente (per esempio perdita di
alimentazione o SIGKILL):

```bash
mulino-rollback --recover
```

Una transazione pendente blocca nuovi deploy. Se anche il ripristino fallisce,
il registro viene conservato e il programma segnala l'errore. Non cancellare
lo stato per aggirare il blocco. Risolvere la causa segnalata nel log e ripetere
`--recover`. Dopo un riavvio del VPS il recupero richiede questo comando: non
e installato un servizio di recupero automatico al boot.

Rollback e recupero usano l'immagine originale tramite ID; non richiedono GitHub,
build o download. Se l'immagine Docker manca, viene caricata dalla copia locale.
Dipendono comunque da Docker, disco, repository e configurazione locale integri.
Problemi esterni a Telegram/Google non vengono risolti tornando a una vecchia immagine.

## Protezioni e limiti

- Un lock impedisce deploy, verifiche e rollback simultanei.
- Working tree modificato, file non tracciati e tag divergenti vengono rifiutati.
  Nessun `reset --hard`, `git clean` o checkout forzato.
- Il checkout conserva i file ignorati e rifiuta di sovrascriverli. Nessun hook Git
  viene eseguito. Il deploy di una nuova release usa HEAD detached; il ramo `main`
  resta intatto. Un rollback alla baseline ripristina il ramo salvato se ancora coerente.
- L'archivio di build contiene solo file del tag; segreti, database, directory dati,
  ambienti virtuali, symlink e submodule sono rifiutati. Non si costruisce dal
  working tree che contiene `bot_risponditore.env` e `.venv-risponditore`.
- Dopo il build vengono confrontati anche gli hash di worker, avvio e requisiti
  nell'immagine con i file del tag, per rifiutare immagini con codice obsoleto.
- Una release gia verificata riusa il suo esatto ID immagine; non viene ricostruita
  alla seconda verifica. Ogni nuovo commit usa un progetto di build distinto.
- I test di regressione sono senza rete e senza dati o credenziali di produzione.
  Il controllo applicativo `--check` usa i segreti in sola lettura, dati temporanei
  e richieste di verifica a Telegram/Google; nella v1.0.0 non invia messaggi e
  non modifica celle. Questa proprieta deve essere conservata nelle nuove release.
- Il controllo di salute verifica immagine, mount, processo Python, Xvfb, x11vnc,
  websockify, pagina noVNC e stabilita del container per almeno 15 secondi.
  Non equivale a una registrazione completa presso Libero, che richiede l'intervento umano.
- Modifiche a Compose, al Risponditore o al suo installer richiedono una procedura
  separata e vengono bloccate. Dalla v1.1.1 esiste una sola eccezione: il passaggio
  fra il precedente URL loopback e l'URL HTTPS Tailscale verificato del Mulino.
  La riga REMOTE_BROWSER_URL deve essere unica e ogni altro byte di Compose
  deve restare identico. Porte, volumi, segreti e privilegi non possono cambiare.
  Preflight usa Compose del tag candidato; controllo di salute e rollback
  verificano anche il valore del link effettivamente usato dal container.
  Cambiamenti a `.env` o ai metadati dei segreti
  bloccano gli aggiornamenti finche non si verifica e riallinea la baseline.
- Non vengono cancellati volumi, dati, segreti o immagini. La normale applicazione
  continua naturalmente a utilizzare e aggiornare i propri dati.
- Dopo l'adozione usare questi comandi per i deploy. `install.sh` e un `docker
  compose up` manuale senza override possono usare un'altra immagine: il controllo
  successivo rilevera la divergenza e blocchera l'operazione.

## File installati e stato

```text
/usr/local/sbin/mulino-deploy
/usr/local/sbin/mulino-rollback
/usr/local/lib/mulino-deploy/controller.py
/opt/mulino-deploy-tools/                    sorgenti, test e questa guida
/var/lib/mulino-deploy/state.json            stato autorevole e transazione
/var/lib/mulino-deploy/last-known-good       tag di rollback leggibile
/var/lib/mulino-deploy/images/               copie locali delle immagini
/var/lib/mulino-deploy/releases/             sorgenti dei tag verificati
/var/lib/mulino-deploy/logs/                 log locali riservati a root
```

Alla prima adozione, versione confermata e last-known-good sono entrambe v1.0.0.
Dopo un deploy riuscito, last-known-good indica la versione precedentemente
funzionante. Durante una transazione indica la versione da ripristinare.
`state.json` e autorevole: non modificare a mano il file last-known-good.

Le immagini occupano spazio; quella iniziale e circa 2,8 GB non compressi.
Non e prevista cancellazione automatica. Controllare `df -h /var/lib/mulino-deploy`
e conservare sempre immagini e archivi delle versioni corrente, precedente e
coinvolte in eventuali transazioni. La copia locale non sostituisce il backup
esterno del VPS.

## Installazione e verifica della procedura

Richiede Linux, Python 3.12+, Git, Docker e Docker Compose con `config
--no-env-resolution` e `up --wait`. Eseguire da root.

```bash
cd /opt/mulino-deploy-tools
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v test_controller
install -d -m 0755 /usr/local/lib/mulino-deploy
install -m 0644 controller.py /usr/local/lib/mulino-deploy/controller.py
install -m 0755 mulino-deploy /usr/local/sbin/mulino-deploy
install -m 0755 mulino-rollback /usr/local/sbin/mulino-rollback
mulino-deploy init v1.0.0 --baseline-tests /opt/mulino-deploy-tools/baseline-tests/test_regressions.py
mulino-deploy status
```

`init` adotta il container gia attivo, verifica che il suo codice corrisponda al
tag e conserva l'immagine senza riavviare. Rifiuta di sovrascrivere una baseline
esistente. La reinstallazione degli script non richiede un nuovo `init`.

### Correzione dei test storici della v1.0.0

La suite pubblicata con v1.0.0 contiene 9 test. Cinque falliscono gia all'avvio
perche il caricatore AST seleziona soltanto alcune classi e omette `MessageCleanup`
e le altre dipendenze introdotte nel worker. Il programma in esecuzione non ha
questo caricatore: il problema riguarda i test.

`baseline-tests/test_regressions.py` conserva i 9 test e le loro verifiche,
carica il modulo completo senza leggere file `.env` e aggiorna i messaggi simulati
alle interfacce attuali. Usa le dipendenze gia installate nell'immagine; Telegram
e Sheets rimangono simulati. La correzione e stata verificata senza rete e senza
dati o credenziali reali.

Per adottare questa specifica baseline, il comando iniziale effettivamente usato e:

```bash
mulino-deploy init v1.0.0 --baseline-tests /opt/mulino-deploy-tools/baseline-tests/test_regressions.py
```

Il tag v1.0.0 e il codice applicativo rimangono invariati. La suite corretta viene
copiata nello stato della baseline e vincolata al suo hash SHA-256. Soltanto il
record di questa baseline la usa: un nuovo tag deve superare la propria suite
`tests/`. Le nuove release devono quindi includere la correzione in
`tests/test_regressions.py`, fornita anche nel pacchetto. Non viene ignorato o
disabilitato nessun test fallito, e la suite vuota rimane un errore.

`integration_test.py` verifica il motore con un progetto Docker separato,
un repository temporaneo, dati e segreti fittizi. Scarica l'immagine ufficiale
`python:3.12-slim` se assente. Non montare dati reali nel progetto di prova.
Al termine rimuove i container e le reti di quel solo progetto e lascia il report
in `/var/tmp/mulino-deploy-integration-*/report.json`.

Riferimenti: [Compose up](https://docs.docker.com/reference/cli/docker/compose/up/),
[percorsi e progetti Compose](https://docs.docker.com/reference/cli/docker/compose/).
