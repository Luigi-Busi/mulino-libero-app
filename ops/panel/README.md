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

## Conteggi tester dalla v1.3.0

Tester mostra gli ID della whitelist e dei tester nello storico, dieci per pagina.
I numeri di telefono non sono esposti né copiati nel registro dei conteggi.
/conteggi apre l'elenco, /conteggio ID apre il dettaglio, /azzera ID chiede
conferma; tutti riusano lo stesso messaggio e sono riservati al proprietario
nella propria chat privata. /id permette al tester di conoscere il proprio ID.

Il credito richiede la pagina finale riconosciuta dopo l'OTP del tester corrente.
Invio del numero/codice, codici errati, reinvii, caselle senza verifica telefonica
e recuperi manuali senza prova SMS non assegnano crediti. Esito e credito sono
salvati nella stessa transazione prima della chiusura del browser, senza attendere
la sincronizzazione Google. La richiesta è univoca anche dopo un azzeramento.
Non sono importate automaticamente le operazioni precedenti all'attivazione.

Il reset registra un nuovo confine di conteggio, senza eliminare completamenti
o modificare la coda. Conferma con scadenza di 15 minuti e uso singolo, vincolata
al tester e al messaggio; un completamento nel frattempo richiede nuova conferma.
Il dettaglio mostra periodo attuale e totale storico. Se la whitelist non è
raggiungibile, l'elenco dichiara la limitazione e mostra solo i tester nello storico.

Due tabelle aggiuntive nello stesso created-outcomes.sqlite3 conservano crediti
(request ID, tester ID, date UTC) e reset (tester ID, confine, amministratore, data).
Il backup locale e quello completo conservano tutto il file, senza nuove credenziali
né servizi. Le colonne delle tabelle precedenti restano invariate. La v1.2.1 ignora
le nuove tabelle e può verificare un backup nuovo; eventuali completamenti durante
un rollback non vengono conteggiati automaticamente al ritorno alla v1.3.0.

## Menu in fondo e comandi puliti dalla v1.3.1

/menu invia un nuovo pannello in fondo alla chat. Solo dopo l'invio riuscito e
il salvataggio del nuovo riferimento, il vecchio pannello viene accodato per
la cancellazione. I suoi pulsanti vengono invalidati. I pulsanti del nuovo
pannello continuano ad aggiornare lo stesso messaggio. /pannello e /start
mantengono invece il riuso del messaggio esistente.

Dopo il buon esito del relativo gestore sono eliminati i nuovi comandi registrati
(start, menu, pannello, conteggio, conteggi, azzera, id, idgruppo, stato, recupera,
controlla, backup, pausa, browser, riprendi, annulla, riprova, conferma_creata)
solo se il messaggio osservato proviene dal proprietario nella sua chat privata.
Non vengono cancellate le risposte del bot ai comandi diretti, gli avvisi,
i messaggi ordinari, i dati per la registrazione o i comandi dei tester/gruppi.
Non viene letta la cronologia e non sono ricostruiti ID di messaggi sconosciuti.

La nuova tabella admin_chat_cleanup nello stesso database degli esiti conserva
solo proprietario, bot, messaggio e tipo. Riferimento nuovo e cancellazione del
pannello precedente sono salvati insieme. Gli errori di rete conservano il job;
la pulizia riparte anche dopo riavvio. Il pannello corrente è sempre protetto,
compreso dopo un ripristino. Un errore nella pulizia non ripete un comando già
eseguito. Il salvataggio del riferimento fallito lascia il vecchio pannello.

Telegram consente le cancellazioni entro 48 ore: se il pannello precedente
è troppo vecchio o non eliminabile resta visibile ma inattivo, senza bloccare
il nuovo. Errori definitivi non sono ritentati senza fine; altri errori e limiti
di frequenza conservano il job e rispettano l'attesa. Un invio del nuovo
pannello fallito non elimina quello precedente né il comando /menu.

La v1.3.0 ignora la tabella aggiuntiva e verifica i backup SQLite nuovi; non
esegue questa pulizia. Backup, conteggi tester, coda, versioni e configurazione
non cambiano. Nessun nuovo permesso o servizio esterno.
Riferimento: https://core.telegram.org/bots/api#deletemessage

## Risposte ordinarie della coda dalla v1.3.2

Solo le risposte nuove, realmente inviate al proprietario nella sua chat privata,
di /pausa, /stato e /riprendi sono registrate in admin_response_history. Un'unica
categoria queue conserva owner, bot, message e sent_at (secondi UTC dalla data
Telegram), senza testo, argomenti, credenziali o identificativi delle richieste.
La risposta con ID Telegram maggiore resta sempre. Le precedenti vengono
eliminate quando hanno almeno 24 ore e meno di 48 ore; oltre il limite Telegram
è eliminato soltanto il riferimento obsoleto, non un messaggio della cronologia.

Il ciclo esistente della coda esegue la pulizia anche mentre è in pausa e senza
nuovi comandi. Otto risposte per passaggio; nessun nuovo servizio o timer.
Errori transitori e limiti di frequenza conservano i riferimenti per ritentare.
Un salvataggio fallito dopo invio non ripete il comando né l'azione sulla coda.
Duplicati e registrazione fuori ordine non cambiano data o risposta più recente.
Il pannello corrente è protetto anche dopo ripristino.

Le risposte con registrazione attiva/in chiusura, errori di pausa/ripresa,
pausa non persistente o esiti pendenti verso Sheets restano escluse. Il pannello
non è una risposta eliminabile. Restano esclusi altri comandi, risposte a tester,
gruppi, inoltri, testo ordinario e avvisi. Nessuna ricostruzione della cronologia
precedente all'attivazione; i suoi messaggi non sono cancellati.

La tabella aggiuntiva è conservata da tutti i backup del registro e ignorata
dalla v1.3.1 in rollback. Conteggi, pausa e struttura delle altre tabelle non
cambiano. Il browser e il suo collegamento restano quelli già configurati.
