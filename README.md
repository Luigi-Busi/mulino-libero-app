# Creazione assistita Libero Mail

Sistema separato da **Il Banco** che parte quando EmailMatcher non trova alcuna
e-mail per il Nome e Cognome appena inserito.

Aggiornamento del 16/09/2026 per il VPS `mulino-libero-01`. Il pacchetto usa
la configurazione e i segreti già presenti in `/opt/mulino-libero`; il codice
si installa nella sottocartella `app`. Non sostituire il tuo `.env` con
`.env.example`: quest'ultimo è soltanto un riferimento.

## Cosa fa

### Creazione su richiesta privata: v1.3.8

In privato al Mugnaio, solo l'amministratore può usare `/creamail Nome | Cognome`.
Per nomi semplici funziona anche `/creamail Mario Rossi`; il separatore `|`
preserva i nomi e cognomi composti. Il comando accoda una richiesta nella coda
ordinaria e non supera la pausa né interrompe altre registrazioni. I dati
anagrafici vengono richiesti nel gruppo configurato all'Apprendista, con lo
stesso flusso e gli stessi controlli delle richieste automatiche.
Browser, password configurata, CAPTCHA, conferma finale, verifica SMS con
whitelist e conteggi dei tester restano quelli del normale processo.

Lo storico `Richieste Manuali` risiede nello stesso libro Google della Coda:
nessun account viene inserito nei fogli operativi del Banco. Usa identificativi
stabili e salva la mail completata; il risultato viene comunicato in privato.
Il comando ricontrolla le richieste esistenti anche del Banco per lo stesso
nominativo e non ne avvia una seconda. Omonimi e richieste multiple richiedono
una verifica esplicita. In caso di errore o annullamento usare `/recupera`
dopo aver verificato se la casella esiste; `/creamail` non ripete automaticamente
un tentativo fallito. Un accodamento dall'esito incerto viene prima riservato
in stato non eseguibile e ricontrollato tramite lo stesso comando.

La v1.3.6 controlla il ritorno al modulo iniziale di Libero durante l'attesa
del tester, della conferma finale del passaggio telefonico e del codice SMS.
La presenza visibile dei campi iniziali nome utente e password, senza una
finestra OTP attiva, interrompe il tentativo e invalida i pulsanti del tester.
Il controllo viene ripetuto circa ogni due secondi durante le attese Telegram
e prima di inserire il numero, inviare o reinviare un SMS e verificare il codice.
Una pagina sconosciuta o in caricamento non è sufficiente per dichiarare una
sessione scaduta. Non viene ripetuta automaticamente la registrazione: l'esito
va verificato con /recupera. Restano incluse le modifiche di pulizia v1.3.5.

1. EmailMatcher cerca il nominativo negli archivi esistenti.
2. Se l'e-mail non esiste, crea una richiesta nel foglio `Coda`.
3. Il nuovo bot chiede i dati nel gruppo configurato con l'Apprendista:
   `GG/MM/AAAA | M/F | Città (PR)`.
4. Il worker apre Libero in un contesto browser nuovo.
5. Quando serve il telefono, il bot pubblica nel gruppo un messaggio generico.
6. Il primo whitelistato che preme `Usa il mio numero` prende la richiesta.
7. Il codice viene accettato soltanto dalla chat privata di quell'ID Telegram.
8. Prima dell'invio finale, l'amministratore deve premere `Conferma creazione`.
9. L'e-mail viene scritta nella riga Google Sheets originaria.
10. Il contesto del browser viene chiuso: cookie, cache, local storage e
    cronologia non passano alla registrazione successiva.

Il programma non risolve, ricarica in ciclo o aggira CAPTCHA. Se Libero mostra
una verifica interattiva, il browser resta aperto e l'amministratore riceve una
richiesta di intervento manuale.

## File

- `EmailMatcher_aggiornato.gs`: sostituisce integralmente l'attuale file
  EmailMatcher nello stesso progetto Apps Script di Il Banco.
- `libero_mail_bot.py`: bot Telegram separato e worker Playwright.
- `Dockerfile`, `docker-compose.yml`, `start.sh`: esecuzione continua su VPS.
- `install.sh`: controllo della configurazione e installazione sul VPS.
- `.env.example`: configurazione senza segreti.

## 1. Aggiornare Apps Script

Se hai già inizializzato `Coda` e `Whitelist` con questo EmailMatcher, questa
parte è già completata. Il file Apps Script incluso non è stato modificato.

1. Apri il progetto Apps Script nel quale sono presenti Il Banco ed
   EmailMatcher.
2. Sostituisci **l'intero contenuto del solo file EmailMatcher** con
   `EmailMatcher_aggiornato.gs`.
3. Salva.
4. Dall'elenco funzioni esegui una volta:
   `inizializzaSistemaCreazioneMail`.
5. Accetta le autorizzazioni Google.
6. Apri il log di esecuzione: troverai URL e ID del nuovo file
   `Creazione Mail Libero`.
7. Esegui `testSistemaCreazioneMail`.

Il nuovo file contiene:

- `Coda`: richieste e stati del worker;
- `Whitelist`: soltanto le colonne `TELEGRAM_ID` e `NUMERO_TELEFONO`.

Non modificare i titoli delle colonne. Inserisci i numeri preferibilmente nel
formato internazionale, per esempio `+393331234567`.

Il Banco non richiede modifiche: continua a chiamare `completaEmailRiga`, che
ora accoda automaticamente la richiesta quando EmailMatcher non trova una mail.

## 2. Creare il bot Telegram separato

1. Crea un nuovo bot tramite BotFather; non riutilizzare il token di Il Banco.
2. Crea un gruppo Telegram privato dedicato.
3. Aggiungi `@Il_Mugnaio_Bot` al gruppo dedicato come amministratore.
   Non servono poteri per bannare utenti, aggiungere amministratori o modificare
   le informazioni del gruppo. La chat del gruppo può restare in sola lettura
   per i membri: prendono la richiesta con il pulsante e rispondono in privato.
4. L'amministratore e ogni whitelistato devono aprire la chat privata del bot e
   inviare `/start`; Telegram non permette a un bot di iniziare autonomamente
   una chat mai aperta dall'utente.
5. Per conoscere il proprio ID si può usare `/id`.

Il messaggio nel gruppo non mostra nome, cognome o indirizzo e-mail.

## 3. Service account Google

1. Crea un progetto in Google Cloud e abilita **Google Sheets API**.
   Questa versione apre i documenti per ID e non richiede Google Drive API.
2. Crea un service account e scarica la chiave JSON.
3. Nel file Google `Creazione Mail Libero`, condividi il documento con
   l'indirizzo e-mail del service account come **Editor**.
4. Condividi con lo stesso indirizzo, sempre come Editor, anche il Google Sheet
   nel quale EmailMatcher dovrà scrivere l'e-mail finale.
5. Sul VPS la chiave è già salvata in:
   `/opt/mulino-libero/secrets/google-service-account.json`.

Non caricare mai questo JSON su GitHub o in chat.

## 4. Configurare il server

I file già configurati sul VPS sono:

| Percorso relativo a `/opt/mulino-libero` | Contenuto |
| --- | --- |
| `.env` | ID del foglio, ID Telegram e nomi delle schede |
| `secrets/google-service-account.json` | Chiave Google |
| `secrets/telegram-bot-token` | Token di `@Il_Mugnaio_Bot` |
| `secrets/libero-password` | Password scelta per le nuove caselle |

Permessi: `600` per questi file e `700` per la cartella `secrets`.
La configurazione `.env` usa questi nomi:

```dotenv
GOOGLE_SPREADSHEET_ID=ID_DEL_TUO_FOGLIO
TELEGRAM_GROUP_ID=-1004493733217
TELEGRAM_ADMIN_ID=7279460507
GOOGLE_QUEUE_SHEET=Coda
GOOGLE_WHITELIST_SHEET=Whitelist
TZ=Europe/Rome
```

Il token e le password vengono letti dai rispettivi file; non occorre copiarli
in `.env`. Sono ancora riconosciuti i vecchi nomi `ADMIN_TELEGRAM_ID` e
`TELEGRAM_GROUP_CHAT_ID`, se presenti.

La password Libero deve avere 8-20 caratteri, almeno una maiuscola, un numero
e un simbolo tra `@ . + $ - _ !`, secondo la
[pagina di registrazione Libero](https://registrazione.libero.it/) consultata
il 16/09/2026. L'eventuale a capo aggiunto da nano a fine file viene ignorato.
Se il controllo segnala una password non conforme, modifica solo il file
`secrets/libero-password` con nano, salva e ripeti l'installazione.

## 5. Installazione sul VPS

Apri prima la chat privata di `@Il_Mugnaio_Bot` e invia `/start`. Fallo anche
dall'account del primo whitelistato. Se il programma non è ancora avviato,
in questo momento è normale non ricevere risposta.

Scarica lo ZIP sul Desktop Windows. In **PowerShell Windows** (`PS C:\...>`),
sostituendo soltanto `IP_DEL_SERVER` con l'indirizzo del VPS:

```powershell
scp "C:\Users\Utente\Desktop\creazione-libero-mail-v1.zip" root@IP_DEL_SERVER:/opt/mulino-libero/
```

Nella sessione **SSH del VPS** (`root@mulino-libero-01:...#`):

```bash
python3 -m zipfile -e /opt/mulino-libero/creazione-libero-mail-v1.zip /opt/mulino-libero/app
cd /opt/mulino-libero/app
bash install.sh
```

Lo script costruisce l'immagine e controlla configurazione, intestazioni del
foglio, whitelist, bot, gruppo e chat privata dell'amministratore. Questi
controlli non inviano messaggi e non modificano celle. L'accesso in scrittura
verrà verificato durante il primo collaudo; la condivisione deve essere Editor.

Se il controllo fallisce, lo script si ferma senza avviare una nuova istanza.
Se riesce, avvia il servizio, che controlla la coda e si riavvia automaticamente
dopo un riavvio del VPS. Il PC può essere spento; eventuali richieste di dati,
codici, CAPTCHA e conferma finale attendono la risposta dell'utente.

Viene creata anche una password VNC casuale di 8 caratteri nel file
`/opt/mulino-libero/secrets/vnc-password`, conservata alle installazioni
successive. È separata dalla password delle caselle.

Comandi utili **nel VPS**:

```bash
cd /opt/mulino-libero/app
docker compose --env-file ../.env ps
docker compose --env-file ../.env logs --tail=60
```

Per fermare il servizio: `docker compose --env-file ../.env stop`.
Per riavviarlo: `docker compose --env-file ../.env up -d`.
Mantieni una sola istanza attiva per questo token Telegram.

## Browser remoto e CAPTCHA

Il browser grafico viene esposto da noVNC soltanto su `127.0.0.1:6080` del VPS.
Da **PowerShell Windows**, apri un tunnel SSH e lascia aperta quella finestra:

```powershell
ssh -L 6080:127.0.0.1:6080 root@IP_DEL_SERVER
```

Sul PC Windows apri:

```text
http://127.0.0.1:6080/vnc.html
```

Nel terminale del VPS puoi leggere la sola password VNC con:

```bash
cat /opt/mulino-libero/secrets/vnc-password
```

Copiala nella schermata noVNC, senza inviarla in chat o in screenshot. Il link
locale funziona dal PC con il tunnel aperto; dal telefono occorre configurare
separatamente un tunnel o accesso privato. Non aprire la porta 6080 nel firewall.
Quando compare un CAPTCHA, risolvilo nel browser e premi il pulsante di
conferma inviato dal bot. Non vengono usati servizi di risoluzione automatica.

### Se la registrazione termina senza SMS o mostra una schermata sconosciuta

La verifica telefonica non e obbligatoria per il bot: una pagina di successo
riconosciuta conclude la richiesta anche senza SMS. Dopo l'invio finale, il bot
attende anche le risposte lente senza premere di nuovo Registrati.

Se la schermata non viene riconosciuta, il browser resta aperto e la richiesta
rimane in attesa. Il bot riprende quando riconosce l'esito o il passaggio seguente.
Dopo l'invio finale, nella chat privata amministrativa compare anche **Casella gia
creata**: usarlo solo dopo aver verificato personalmente l'accesso all'indirizzo
esatto. Una seconda conferma salva l'esito senza ripetere la registrazione.

Per interrompere volontariamente usare `/annulla`. Per una richiesta gia terminata
in errore usare `/recupera` e **Casella gia creata** dopo la verifica dell'accesso.
Non usare Riprova registrazione per una casella che esiste gia.


## Uso del bot

- `/start`: registra l'apertura della chat e verifica whitelist.
- `/id`: mostra il Telegram ID.
- `/stato`: stato della richiesta attiva, solo amministratore.
- `/annulla`: annulla la richiesta attiva, solo amministratore.
- `/riprova ID_RICHIESTA`: rimette in coda una richiesta in errore.

Quando il bot chiede i dati anagrafici, rispondi in privato:

```text
15/04/1992 | M | Salerno (SA)
```

Se il Nome e Cognome del foglio è stato separato male:

```text
Mario | De Angelis | 15/04/1992 | M | Salerno (SA)
```

Dopo averli letti e validati, il bot prova a eliminare dalla chat il messaggio
che conteneva questi dati. Non li scrive nel foglio di coda né nei log.

La procedura automatica gestisce soltanto maggiorenni. Libero prevede per i
minori un flusso distinto con consenso del responsabile, che resta manuale.

## Primo collaudo

1. Dopo l'avvio invia `/start` e `/stato` al bot in privato.
2. Inserisci tramite Il Banco una singola richiesta autorizzata per un nominativo
   senza email già presente. Verifica la nuova riga in `Coda` e la richiesta
   privata dei dati anagrafici.
3. Apri il browser remoto prima di fornire i dati e segui la prima registrazione.
4. Verifica il pulsante nel gruppo, la ricezione privata del codice e la conferma
   finale. Controlla poi la scrittura della mail nel foglio di destinazione.

Il collaudo completo sul VPS, compresa una registrazione reale, resta da fare.
Il sito può cambiare: i passaggi dopo i dati personali richiedono questa verifica
assistita. Se una schermata non è riconosciuta, il worker segnala l'errore senza
inviare il testo della pagina, che potrebbe contenere dati personali. Dopo un
errore, controlla se l'account è già stato creato prima di usare `/riprova`.

Le richieste interrotte da un riavvio sono marcate `ERRORE` e non vengono
ritentate automaticamente, per evitare doppie registrazioni.

## Verifiche del pacchetto

I test di regressione estraggono le definizioni originali del worker, usano dati
fittizi e simulano Telegram e Google. Richiedono solo Python 3.12; non effettuano
registrazioni né inviano messaggi:

```bash
python -m unittest discover -s tests -v
```

Non verificano le librerie esterne o i selettori del sito. La sintassi degli
script e la struttura Compose sono controllate separatamente. La costruzione
Docker e il collegamento ai tuoi account si verificano sul VPS con `install.sh`.

### Cambio automatico del tester dopo 5 minuti (v1.3.3)

Dopo il primo invio SMS di ogni assegnazione, il Mugnaio attende al massimo
5 minuti per il codice. Il reinvio SMS e un codice rifiutato dal sito non
prolungano questo limite. Un codice gia ricevuto in tempo viene verificato;
il timer non interrompe la verifica in corso. I codici arrivati dopo la
scadenza e i pulsanti della precedente assegnazione vengono respinti.

Alla scadenza il bot avvisa l'amministratore, scollega il tester e invalida
la sua assegnazione. Richiede un numero diverso soltanto dopo aver ritrovato
il campo Cellulare della verifica, senza finestra OTP sovrapposta. Usa solo
un comando esplicito del sito per modificare il numero; se non lo trova,
conserva la sessione e chiede un intervento tramite browser remoto.
Non ripete Registrati. Se riconosce i campi iniziali nome utente/password
visibili durante il cambio, segnala la sessione scaduta o reimpostata e
l'esito da verificare tramite /recupera prima di un eventuale nuovo tentativo.

Un reinvio gia in corso termina prima del cambio, senza azioni sovrapposte.
Ogni nuovo tester riceve una nuova finestra di 5 minuti. Il conteggio tester
continua ad aumentare soltanto per registrazioni completate con SMS verificato.
La modifica non altera formato dei dati, segreti o archivio delle immagini.
