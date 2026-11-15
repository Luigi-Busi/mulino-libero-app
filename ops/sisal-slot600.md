# Sisal Slot 600 — v1.3.26

## Integrazione

Il foglio esistente Sisal Slot 600 in Matched & Arbitrage è stato verificato in
sola lettura il 15 novembre 2026. Intestazioni alla riga 9: Data Apertura A,
Chiusura B, Diffida C, Nome Cognome D, Username E, Password F, E-mail G,
Password E-mail H e Provenienza I. Sisal Sport mantiene le sue intestazioni alla riga 8.
Non sono stati creati o spostati fogli o dati durante la preparazione.

Il parser Banco riconosce SISAL 600 e SISAL SLOT 600 tramite la normalizzazione
esistente (spazi, maiuscole ed emoji ignorati), prima del generico Sisal.
SISAL 🎰 continua a usare Sisal Sport; 6000 e 1600 non sono classificati come 600.
Nuova configurazione standard: rilevamento intestazioni, inserimento e correzione
esistenti, attivazione di EmailMatcher, elenco di controllo accessi e menu privato.
Il menu considera il nuovo foglio come operatore Sisal per il monitor esistente.
La versione della cache menu passa da 1.2.1 a 1.2.2.

EmailMatcher include il foglio tra destinazioni e sorgenti del file principale.
La creazione usa la Coda e la scrittura del Mugnaio già esistenti; non viene
aggiunta una seconda procedura di creazione. Il controllo di coerenza del Mugnaio
include ora anche le righe del nuovo foglio prive di una richiesta.
ID_MULINO e metadati sono gestiti dalla normale procedura di identità stabile,
senza fissare nuove posizioni per le colonne dei dati.

## Omonimi e rischi

Il processo del proprietario inserisce solo conti aperti: anche questo foglio
usa il contratto operativo di validità e la regola dei 20 giorni. L'identità
del sito/foglio rimane distinta da Sisal Sport e dagli archivi Sisal.
Tra fogli diversi resta la ricerca storica ordinaria. Username assenti, errori
o omonimi oltre 20 giorni continuano a richiedere revisione e decisione persistente.

La priorità del riconoscimento specifico evita il falso instradamento a Sisal Sport.
Il match esatto del testo normalizzato evita di riconoscere 6000 come 600.
Le normali intestazioni standard individuano i campi anche alla riga 9;
nessuna colonna viene dedotta dal solo nome del foglio.

## Test e distribuzione

18 nuovi casi Node su parser reale, configurazioni, intestazioni e scrittura,
accodamento idempotente con ID, recupero mail in entrambe le direzioni e omonimi.
Si aggiungono alle 72 regressioni EmailMatcher e 49 dei callback Telegram.
I test possono usare il candidato Banco completo tramite BANCO_TEST_SOURCE;
in CI usano solo funzioni/configurazioni pure estratte dalla versione 40,
senza credenziali o dati clienti. Il patcher rifiuta replay e baseline inattese.

Applicare ops/apps-script/banco-sisal-slot600-patch.cjs a Codice.gs appena letto.
Conservare gli altri file Apps Script byte per byte e pubblicare sul deployment
esistente, dopo verifica di HEAD, versione, endpoint e ambiti Google.
Il sorgente completo privato del Banco resta fuori dal repository.
Il controller ordinario verifica e installa il worker con pausa persistente
e nessuna registrazione attiva. Il ripristino richiede il rollback separato
di Apps Script e del worker; non cancella righe, mail o richieste già inserite.

Stato installazione: completata il 15 novembre 2026.

Apps Script: versione 41 sul deployment esistente (precedente 40); HEAD e versione
pubblicata riletti e coincidenti, endpoint/accessi invariati e altri tre file invariati.
Banco SHA-256: 2536ff75c1a032b45bb8636c7eaaaecde1cb808b1ec7ce6e0079d46157c3e30b.
EmailMatcher SHA-256: 970d9ad6c04be3701ba5cd13f034f7b18ed375611436b79bb80b77e3c8704945.

Mugnaio: v1.3.26, commit 9050dc54fc5605fc65f68841ee7c6aebf4cd972c.
Suite completa 320 test e controlli preliminari superati. Prima della sostituzione
verificate pausa persistente e assenza di registrazioni/attese umane.
Controller senza transazioni pendenti, Git/immagine/mount/configurazione coerenti;
primo ciclo Telegram e coda verificati, pausa mantenuta. Ripristino worker: v1.3.25.
Nessun dato o account di prova inserito, nessuna modifica a data/ o secrets/.
Il primo inserimento reale resta il riscontro operativo del flusso pubblicato.
