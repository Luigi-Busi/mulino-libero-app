# Betsson — v1.3.28

## Formato reale e integrazione

Il 15 novembre 2026 è stato verificato in sola lettura il foglio Betsson in
Matched & Arbitrage. Intestazioni alla riga 9: Data Apertura A, Diffida B,
Nome Cognome C, Username D, Password E, E-mail F, Password E-mail G,
Provenienza H, bonus da I in poi. Nessuna nuova posizione viene dedotta dal nome.

Betsson🎰 (maiuscole, spazi e decorazioni ignorati dalla normalizzazione già
esistente) viene riconosciuto prima delle corrispondenze generiche. Si usa il
flusso standard: Nome e Cognome, Username e Password obbligatori e univoci,
inserimento C:E e H, Data Apertura A secondo la normale regola di inserimento.
La provenienza resta il valore UTENTI del mittente autorizzato. Correzioni sulla
riga salvata, senza cambiare A, B, F:G o bonus. Duplicati gestiti dal codice esistente.

EmailMatcher include Betsson tra destinazioni e sorgenti del file principale.
La mail viene cercata negli archivi esistenti e scritta in F; se assente,
si usa la normale Coda con ID stabile e la creazione del Mugnaio.
Le mail inserite in Betsson diventano disponibili per altri nuovi inserimenti.
Il controllo di coerenza del Mugnaio include anche Betsson.

Menu Banco aggiornato con cache 1.2.4. Lo stato email rimane non monitorato:
non viene inventata una relazione con il monitor di un altro operatore.
Non si estende la regola dei 20 giorni, non confermata per Betsson: gli omonimi
nello stesso foglio restano casi manuali con decisione persistente.
Nessuna modifica a Betflag, ai suoi archivi o alle altre nuove schede.

## Test e distribuzione

23 nuovi casi Node su parser/configurazioni reali, intestazioni, scrittura,
conservazione delle altre celle, duplicati/correzioni e provenienza,
accodamento idempotente, mail in entrambe le direzioni e omonimi.
Il riferimento puro della versione 42 è ottenuto applicando il patch Betflag
alla baseline 41 già verificata; il candidato completo è collaudabile tramite
BETSSON_BANCO_TEST_SOURCE. Nessun account o messaggio reale viene creato dai test.

Patcher ops/apps-script/banco-betsson-patch.cjs: applicare solo a Codice.gs
appena letto; rifiuta replay/baseline inattese. Il sorgente completo privato
resta fuori dal repository. Pubblicare sul deployment esistente mantenendo
gli altri file byte per byte, endpoint e permessi. Installare il worker tramite
il controller ordinario soltanto in pausa e senza registrazioni attive.
Rollback Apps Script e worker separati, senza cancellare mail o dati inseriti.
Nessuna modifica a data/ o secrets/. Il primo inserimento reale resta il
riscontro operativo del flusso pubblicato.

Stato installazione: completata il 15 novembre 2026.

Apps Script versione 43 (precedente 42): HEAD e versione pubblicata riletti e
coincidenti, altri tre file byte per byte invariati, endpoint/accessi invariati.
Banco SHA-256: a35e639516a3ff0bfcf90fb183c0a64971ac7518e4510c5760548d22fc68d325.
EmailMatcher SHA-256: 2b8bcf73eba87e1b9a255ca7203e4ef36c544458559abf272280dd9247d88968.
Anche RecuperoEmailMancanti usa EM_TARGET_SHEETS, quindi include il nuovo foglio.

Mugnaio v1.3.28, commit 409faa8b83c975759903ac773eb921219316f4a9.
322 test e controlli preliminari superati. Prima della sostituzione verificati
pausa persistente, assenza di registrazioni e assenza di attese umane.
Installazione confermata, nessuna transazione pendente, Git/immagine/mount/
configurazione coerenti. Primo ciclo Telegram/coda verificato e pausa mantenuta.
Ripristino worker disponibile: v1.3.27. Nessun account di prova inserito.
