# Diagnostica delle chiusure del browser

Il worker registra codici di fase statici, chiusura/crash della pagina,
chiusura del contesto, disconnessione del browser e pulizia prevista.
L'identificativo della richiesta è trasformato in un hash; sessione, sequenza e
timestamp Docker permettono di ricostruire l'ordine. Non raccoglie testo degli errori, URL,
contenuti della pagina, screenshot, tracce Playwright, credenziali o input.
Un errore della diagnostica non deve cambiare il risultato della registrazione.
La pulizia è limitata nel tempo e non sostituisce l'errore iniziale con un
eventuale secondo errore di chiusura.

Il launcher mantiene il comportamento di arresto dell'intero servizio quando
termina un componente, registrando il primo componente osservato e il codice di uscita.
Rileva anche componenti terminati durante l'avvio, prima di entrare nell'attesa.
TERM/INT richiesti e pulizia conseguente sono distinti dai guasti.
Non sono introdotti nuovi retry, restart del browser o invii di registrazione.

Il servizio host osserva solo il progetto Docker del Mugnaio. Raccoglie eventi
Docker filtrati e solo le righe diagnostiche con schema e valori ammessi;
i normali log e messaggi arbitrari vengono scartati. Ogni minuto campiona i
contatori cgroup di memoria/OOM e lo stato del container, senza eseguire comandi
al suo interno. Non modifica il bot, i dati o i segreti e non legge i loro file.

Rapporti: /var/log/mulino-browser-diagnostics/events.jsonl, proprietario root,
directory 0700 e file 0600. Rotazione per dimensione: file corrente e quattro
copie da massimo circa 2 MiB ciascuna; non è una conservazione garantita in giorni.
Il servizio non apre porte, non invia messaggi Telegram e non esporta rapporti.
Può essere fermato senza arrestare il Mugnaio.

## Installazione e recupero

Dopo i test eseguire da root bash ops/diagnostics/install.sh nella release.
L'installer rifiuta di sovrascrivere un servizio esistente. Su ricostruzione
del VPS reinstallarlo dal repository recuperato dopo avere ripristinato Docker.
Codice e unità sono nel bundle Git dei backup; i rapporti tecnici rotanti non
sono inclusi nel backup completo esistente. Il ripristino del bot non dipende
dal collettore. Il rollback applicativo conserva l'osservatore, compatibile anche
con versioni precedenti che non emettono eventi del browser.

Per interrompere soltanto l'osservatore: systemctl disable --now
mulino-browser-diagnostics.service. Non rimuovere dati o segreti.

## Interpretazione e limiti

Un page_close inatteso precede la normale pulizia: può essere una chiusura manuale
o un arresto, non prova da solo quale causa. Un page_crash identifica il crash
del renderer; browser_disconnected distingue la perdita del browser. Confrontare
component_exit e gli eventi Docker kill/die/oom nello stesso container e intervallo.
OOMKilled falso non esclude la terminazione di un solo processo Chromium: servono
anche i contatori oom_kill e gli eventi al momento dell'errore.

Gli eventi Docker storici sono limitati e la rilettura del collettore copre gli
ultimi cinque minuti; dopo interruzioni lunghe alcuni eventi possono mancare.
Riconnessioni possono produrre duplicati identificabili da sessione/seq e container.
Il campionamento ogni minuto non rileva tutti i picchi di memoria. Non promette
di ricostruire retroattivamente i vecchi TargetClosedError.

Test unitari, crash Chromium simulato e prove Docker usano solo dati fittizi,
senza rete e senza mount di produzione. Non esaurire la memoria del VPS per
collaudare OOM: il parser viene provato con un evento sintetico.

Riferimenti: https://playwright.dev/python/docs/api/class-page#page-event-crash
e https://docs.docker.com/reference/cli/docker/system/events/.
