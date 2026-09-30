# Pannello privato Mulino Libero

Aprire /menu, /pannello oppure /start nella chat privata del proprietario.
Solo TELEGRAM_ADMIN_ID nella propria chat privata può aprire e usare il menu.
I comandi preesistenti continuano a funzionare. Il menu non invia registrazioni,
non esegue deploy/rollback e non aggiunge porte o servizi esterni.

- Stato rilegge coda attiva/pausa, richiesta corrente, esiti da sincronizzare e versione.
- Pausa e Riprendi chiamano la stessa procedura persistente dei comandi esistenti.
  La pausa lascia concludere una richiesta già avviata; non la annulla.
- Browser mostra il collegamento privato già configurato e le istruzioni Opera.
- Controlli rilegge l'ultimo riepilogo dei sette controlli del monitor, con orario.
  Nessun controllo forzato: il monitor indipendente aggiorna ogni due minuti.
  Dopo sei minuti il riepilogo è dichiarato vecchio; assenza o formato non valido
  non sono presentati come servizi regolari.
- Backup apre le copie locali del registro, con verifica o creazione manuale.
  Creazione solo dopo una seconda conferma; conservazione preesistente di tre copie.
  Non avvia il backup completo cifrato o il trasferimento PC, verificati da Controlli.

Ogni tastiera è vincolata al messaggio e alla chat, dura 15 minuti e viene
consumata e sostituita dopo una pressione valida. Dopo un riavvio riaprire /menu.
Una pressione duplicata, inoltrata o una conferma inventata non ripete l'azione.
La tastiera è una fotografia: Stato la aggiorna. I messaggi del menu non sono
inseriti fra i messaggi temporanei di una registrazione e non ne sono cancellati.

## Collegamento al monitor

Il solo bind aggiunto è /var/lib/mulino-monitor/panel -> /run/mulino-panel,
in sola lettura, con create_host_path=false. La directory contiene solo
status.json: schema, orario UTC e sette codici statici. Non contiene impostazioni,
URL Healthchecks, ricevute, credenziali, log, identificativi o copie di backup.
La directory è 0700 e il file atomico 0600; il container esistente gira come root.
Nessun socket Docker è montato nel Mugnaio.

Il controller verifica il bind esatto e rifiuta modifiche a dati, segreti, porte
o permessi di scrittura. Il preflight usa dati temporanei e non monta il riepilogo.
L'immagine deve corrispondere agli hash del modulo e di VERSION.

## Installazione e recupero

Prima di attivare v1.2.0 installare il codice host dalla release verificata:
bash ops/panel/install-host.sh. Conserva i due programmi host precedenti e
verifica la produzione prima e dopo; non riavvia il bot. La directory del
riepilogo deve essere creata dal monitor prima dell'attivazione.

Deploy e rollback restano nella procedura già collaudata, con pausa salvata e
nessuna operazione in corso. Il rollback a v1.1.2 rimuove il bind dal container;
il monitor può continuare a esportare il riepilogo senza influenzare il bot.
Con v1.2.0 attiva non ripristinare il vecchio controller, che rifiuta il bind.
Su un VPS ricostruito usare il codice e questa guida conservati nel bundle Git.
Gli archivi delle versioni e i controller fanno parte della protezione esistente;
la directory di riepilogo è ricreabile e non contiene dati da recuperare.

Riferimento callback: https://docs.python-telegram-bot.org/en/v22.8/telegram.callbackquery.html
