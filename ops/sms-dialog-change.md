# Cambio tester dalla finestra di verifica SMS — v1.3.24

Preparata, non installata. Alla verifica iniziale il Mugnaio aveva una registrazione attiva.

## Problema e comportamento

Dopo la scadenza del tester l'assegnazione viene revocata, ma il sito rimane
sulla finestra del codice. Le schermate fornite dal proprietario mostrano il
percorso X → Cellulare, con il vecchio numero ancora presente oppure il campo vuoto.
Il codice precedente ammetteva solo pulsanti espliciti come «Modifica numero».

Il nuovo percorso considera la chiusura soltanto nel contenitore del campo OTP
riconosciuto: titolo esatto, istruzione del codice inviato al numero, reinvio e
Avanti. Esclude contenitori con Registrati, consensi o credenziali iniziali.
Serve un unico controllo di chiusura visibile e abilitato, riconosciuto dal testo
X/× o da un'etichetta Chiudi/Close. Non viene cercata una X generica nella pagina.

Dopo un solo clic, osserva il ritorno al campo Cellulare raggiungibile e la
scomparsa dell'OTP. Soltanto dopo richiede il nuovo tester. La compilazione
esistente sostituisce l'intero valore del vecchio numero. Restano le protezioni
contro codici tardivi e reinvii della precedente assegnazione.

## Verifica e rischi

Le immagini non contengono il DOM reale: le nuove prove usano HTML locale
che riproduce i testi e le transizioni osservabili, senza numeri reali o account.
Dieci nuove prove coprono numero conservato/vuoto, link di chiusura, ambiguità,
controlli esterni o disabilitati, mancata transizione, reset e ordine della revoca.
Superati anche i 19 test esistenti di timeout/cambio tester e i 16 di reset sessione.

Falsi positivi: una chiusura estranea potrebbe portare a un'altra schermata.
Il riconoscimento combinato e la verifica successiva impediscono di assegnare
il tester senza un campo raggiungibile. Non si cliccano Avanti o Registrati.
Una sessione tornata all'inizio interrompe il tentativo.

Falsi negativi: icone prive di testo/etichetta, DOM o testi diversi, due chiusure
riconosciute richiedono ancora intervento manuale. Non si indovinano selettori
da coordinate fotografiche. Il primo cambio reale resta da osservare dopo il rilascio.

## Rilascio

Usare il controller descritto in ops/deploy/README.md. Il controllo del tag può
essere eseguito durante il lavoro attivo; la sostituzione del container richiede
pausa persistente e assenza di registrazioni attive o attese umane.
Compatibile con i dati della v1.3.23: nessuna migrazione, modifica di Whitelist,
segreti, Apps Script, durata del timeout o ruoli Telegram permanenti.
