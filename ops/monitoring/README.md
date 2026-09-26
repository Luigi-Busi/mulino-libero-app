# Monitoraggio Mulino Libero

Il VPS esegue un controllo ogni due minuti e invia a Healthchecks soltanto codici
tecnici prestabiliti. Telegram privato riceve allarme e rientro. Nessun riavvio o
tentativo di registrazione viene effettuato dal monitor.

## Controlli e soglie

- Assenza del VPS o del monitor: periodo Healthchecks 3 minuti, tolleranza 3 minuti.
- Mugnaio e Risponditore: processo, ciclo asincrono e risposte del polling Telegram.
  Segnale del ciclo massimo 90 secondi, polling massimo 180 secondi; avvio 90 secondi.
- Mugnaio: attività del controllo coda; pausa e attese umane non sono guasti.
- Browser: accesso VNC/noVNC e risposta della pagina quando esiste una sessione.
- Disco: almeno 5 GiB, 15% di spazio e 10% di inode liberi.
- Backup: ultimo backup riuscito entro 30 ore, pianificazione attiva, archivi
  esportati integri e ricevuta del PC relativa a una copia verificata entro 30 ore.
  La data della copia originale determina la freschezza, non quella della ricevuta.

Due verifiche consecutive confermano guasto e rientro. Un solo controllo esterno
evita allarmi duplicati quando manca il VPS. Se sono presenti più guasti, i codici
aggiornati sono nell'ultimo evento Healthchecks e in `/var/lib/mulino-monitor/latest.json`;
un guasto aggiuntivo durante un allarme aperto non genera un secondo avviso.
Un PC spento oltre la soglia di freschezza del backup genera quindi un avviso.
L'accesso locale al browser non verifica il tunnel SSH del PC.

## Installazione e lettura dello stato

Programmi in `/usr/local/lib/mulino-monitor`, configurazione privata 0600 in
`/etc/mulino-monitor/config.json` con il campo `ping_url`. Il collegamento riservato
non va inserito nel repository. Unità in `/etc/systemd/system`; timer inizialmente
disabilitato finché tutti i controlli reali non risultano corretti.

`python3 /usr/local/lib/mulino-monitor/monitor.py --check-only` mostra lo stato senza
inviare segnali e senza modificarlo. La cronologia è in Healthchecks e nel journal
di `mulino-monitor.service`. Il file `latest.json` include solo codici e tre stati
booleani; non contiene indirizzi email, messaggi, password o URL visitati.

Il Risponditore usa `responder-monitor.conf` e `run_responder.py`, che mantengono i
gestori originali. La libreria `runtime_health.py` deve essere installata anche
nella cartella del monitor, così il launcher funziona dopo un rollback dell'app.
I segnali sono temporanei in `/tmp` del container e `/run` del VPS. Dati e secrets
di produzione non sono modificati dall'installazione del monitor.

## Manutenzione, rollback e ripristino

Prima di ogni riavvio: `/pausa`, `/stato`, attesa di nessuna registrazione attiva o
in chiusura, poi procedura di deploy. In manutenzione oltre sei minuti sospendere
il controllo su Healthchecks e fermare il timer; riattivarli dopo verifica. Il primo
ping riattiva un controllo sospeso, quindi la sola pausa web non basta se il timer gira.

`mulino-rollback --idle-confirmed` torna alla versione precedente mantenendo i dati.
Versioni precedenti alla v1.1.0 non producono il segnale del Mugnaio: il relativo
allarme è atteso. Verificare manualmente il bot e risolvere l'aggiornamento prima di
riattivare il monitor; non dichiarare sano un componente privo del suo segnale.

Il backup completo cifrato include programmi, configurazione privata, unità e
drop-in del monitor. Il ripristino su server vuoto mantiene il timer disabilitato:
non attivarlo su macchine di prova né mentre il vecchio VPS è ancora operativo.
La copia PC deve rigenerare una ricevuta dopo la verifica degli archivi.

## Collaudo

Controllo esterno separato COLLAUDO: periodo e tolleranza un minuto, solo Telegram.
Inviare un segnale, attendere l'allarme per assenza e inviare il segnale di rientro.
Sospenderlo alla fine. Non spegnere il bot di produzione per simulare un guasto.
Test isolati verificano segnali obsoleti, polling fallito, attese umane, pagina
bloccata, backup alterati, ricevute obsolete, conferma dei guasti e compatibilità
del deploy con i tag precedenti.
