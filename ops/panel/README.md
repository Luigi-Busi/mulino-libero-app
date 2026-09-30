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
consumata e sostituita dopo una pressione valida. Menu/Apri/Chiudi sono sola
navigazione e possono aggiornare la tastiera del pannello corrente anche dopo
scadenza o riavvio; le azioni scadute di pausa/ripresa/creazione restano bloccate.
Una pressione duplicata, inoltrata o una conferma inventata non ripete l'azione.
La tastiera è una fotografia: Stato la aggiorna. I messaggi del menu non sono
inseriti fra i messaggi temporanei di una registrazione e non ne sono cancellati.

## Pannello riutilizzabile dalla v1.2.1

/menu, /pannello e /start aggiornano lo stesso messaggio del bot. Chiudi lo
riduce a una riga con Apri pannello; Apri ripristina la pagina principale.
È possibile fissare manualmente questo messaggio in Telegram. Nessun pin o
cancellazione automatica della cronologia viene eseguito.

Browser, pausa/ripresa e copie del registro mostrano i risultati nel pannello.
Un backup aggiorna «in corso» con l'esito. Se si naviga o si chiude durante
l'operazione, l'esito resta leggibile premendo Backup e non sovrascrive la pagina
corrente. Errori di backup o rotazione producono un avviso privato separato.
Gli altri avvisi urgenti, la gestione SMS/CAPTCHA e i comandi diretti conservano
il comportamento precedente.

Il riferimento del pannello è una sola voce admin_panel nella tabella
runtime_settings già esistente: contiene soltanto tre numeri (proprietario,
bot, messaggio), senza testo o credenziali. Nessun cambio di schema. Il rollback
alla v1.2.0 ignora la voce e continua a leggere pausa ed esiti; i backup del
registro restano compatibili. Solo il programma scrive questa preferenza.

Se il messaggio noto è stato eliminato/non è modificabile viene ricreato;
un errore di rete durante la modifica non avvia un nuovo invio. Il riuso dopo
riavvio richiede che il riferimento sia stato salvato: eventuali errori di
salvataggio sono mostrati nel pannello. Un risultato non recapitato è conservato
in memoria per la sessione corrente e non causa un secondo backup.

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
