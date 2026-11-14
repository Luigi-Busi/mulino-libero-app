# EmailMatcher: omonimi e attivazione della v1.3.21

## Analisi dei campi disponibili

Baseline del repository: main, commit 94201da (v1.3.20). Il matcher precedente
riconosceva solo Nome/Cognome ed E-mail, cercava globalmente per nome e usava
automaticamente l'unico indirizzo trovato. Non conservava identità delle registrazioni.

Il repository non include il codice di Il Banco né un export dei fogli reali.
È stato confrontato anche il riferimento locale disponibile del suo Codice.gs:
trovaIntestazioniStandard riconosce Data apertura / Data di apertura,
Nome e Cognome / Nome Cognome, Username / User / Nome utente, Password e Provenienza.
scriviRiga inserisce Data apertura come dd/MM/yyyy solo per i nuovi inserimenti;
correggiUltimo riscrive la stessa riga senza introdurre una nuova data di apertura.

Non è stato trovato un campo che certifichi il completamento del conto sul sito.
Il proprietario ha confermato in questa sessione che inserisce solo conti già aperti.
Per PokerStars, Sisal Sport e Snai Sport questa conferma è quindi il contratto operativo
di validità (EM_FOGLI_SOLO_REGISTRAZIONI_VALIDE), non una verifica presso l'operatore.
Se il processo cambia, svuotare la configurazione: la regola automatica si fermerà.
Non vengono inventate colonne Stato, Completato o Data registrazione.
Password e provenienza non partecipano alle decisioni e non vengono conservate nei metadati.

## Comportamento

1. Nome normalizzato uguale e foglio/sito normalizzato uguale: si confrontano
   tutte le altre registrazioni, anche senza email e negli archivi configurati.
2. Nei tre siti configurati, username affidabili e diversi, entrambe le righe valide
   e differenza assoluta tra Data apertura di massimo 20 giorni: persone distinte,
   nessun riuso di email, una richiesta nella normale Coda.
3. Qualsiasi confronto oltre 20 giorni, username uguale su righe diverse,
   username/data non affidabili, validità revocata o correzione osservata:
   AMBIGUA, nessuna nuova assegnazione o accodamento.
4. Con più candidati, basta un confronto incerto per richiedere la revisione.
   Una mail del candidato distinto non può rientrare da un'altra fonte con lo stesso nome.
5. Tra fogli diversi resta la ricerca storica: una sola email viene usata;
   più email richiedono revisione. La finestra temporale non deduce identità tra siti.
6. Nome: normalizzazione storica, inclusi accenti/punteggiatura/spazi.
   Sito: minuscole e spazi/punteggiatura normalizzati; Sisal Old e Sisal Sport,
   Snai e Snai Sport restano distinti. Username: solo trim/minuscole;
   punteggiatura e accenti si conservano, spazi interni e segnaposto noti sono incerti.
7. Si accettano date italiane complete, controllando calendario e anni bisestili.
   Si contano giorni civili, senza effetti dell'ora legale. Mai la data della scansione.
   Due intestazioni equivalenti o blocchi affiancati senza confini espliciti
   non forniscono campi affidabili per la regola dei 20 giorni.

## Correzioni e memoria

La prima elaborazione reale di una destinazione assegna un UUID nei metadati
dell'intera riga, distinto per colonna Nome quando ci sono più blocchi.
Non viene aggiunta alcuna colonna al foglio. La stessa riga non è un nuovo candidato.
Una firma di nome, username e data consente di riconoscere successive correzioni;
l'identità non dipende dalla password. Spostamenti di righe intere che conservano
i metadati conservano l'identità; copie/incolla dei soli valori o spostamenti di colonne
possono richiedere una nuova revisione.

Le scelte manuali sono per registrazione, non per semplice nominativo.
La firma del contesto comprende anche candidati, siti, validità e indirizzi:
una variazione osservata invalida la scelta e mantiene il blocco fino a nuova decisione.
Una scelta già invalidata non si riattiva se i vecchi valori ricompaiono.

La prima installazione non può ricostruire modifiche storiche mai osservate.
Rinomine dei fogli e trasferimenti tra file richiedono verifica.
La rimozione dei metadati elimina la memoria; includere i fogli e i metadati nelle
procedure di copia/ripristino. Il backup del solo worker Docker non li contiene.

## Revisione manuale e notifiche

Il nuovo foglio RevisioniOmonimi viene creato nel file SPREADSHEET_ID_LOG_MAIL
solo al primo caso ambiguo. È un registro di sistema separato dai fogli account:
ID_REGISTRAZIONE, AGGIORNATA_IL, STATO, FOGLIO, RIGA, NOME, MOTIVO, CONTESTO.
Una riga per destinazione, aggiornata anziché duplicata; il normale foglio Log resta attivo.

Un avviso privato usa inviaTelegram e ADMIN_TELEGRAM_ID del progetto Il Banco:
non sono introdotti destinatari o token. È deduplicato per contesto.
Un errore Telegram mantiene il blocco e viene ritentato alla prossima scansione.
Se queste funzioni non sono disponibili, il registro resta la fonte di revisione
e viene scritto un avvertimento nella console Apps Script.
L'anteprima non invia notifiche, non crea metadati, revisioni, mail o richieste;
scrive soltanto il normale log di anteprima già previsto.

Dopo aver verificato i dati, eseguire una funzione temporanea nell'editor Apps Script,
sostituendo gli esempi con foglio, riga e indirizzo effettivamente verificati:

```javascript
function risolviOmonimoVerificato_() {
  decidiOmonimo_("Sisal Sport", 123, "USA_EMAIL", "indirizzo-verificato@example.com");
  // Oppure, per una persona distinta:
  // decidiOmonimo_("Sisal Sport", 123, "NUOVA_MAIL");
}
```

Le API di decisione e i nuovi helper terminano con underscore: non sono richiamabili
da google.script.run. Anche gli esempi sono privati. Eseguire soltanto dall’editor autorizzato; rimuovere la funzione
temporanea dopo l’uso.

La funzione salva la scelta senza scrivere mail o avviare il worker.
Eseguire poi completaEmailRiga per quella destinazione oppure la normale scansione.
Una modifica diretta delle colonne del registro non autorizza una decisione.

Per segnalare un conto non valido/incompleto, oppure verificarlo successivamente:

```javascript
function verificaRegistrazione_() {
  impostaValiditaRegistrazione_("SPREADSHEET_ID", "Sisal Sport", 123, false);
  // true solo dopo verifica dell'apertura effettiva del conto.
}
```

Una conferma esplicita è legata alla firma della registrazione; cambiando i dati
deve essere riconfermata. Le API manuali usano lo stesso lock del matcher.

## Review dei rischi

| Caso | Rischio residuo / comportamento |
| --- | --- |
| Tentativo fallito inserito come conto aperto | Può produrre una falsa distinzione entro 20 giorni: il contratto confermato dall'operatore umano è essenziale; revocare la validità quando necessario. |
| Data apertura coincide con l'inserimento tardivo e non con l'apertura reale | Possibile falsa distinzione; correggere la data prima dell'elaborazione. Il codice di Il Banco scrive la data del giorno d'inserimento. |
| Vincolo di riapertura del sito cambia o ha eccezioni | La finestra di 20 giorni è una regola operativa dell'utente, non una garanzia verificata presso l'operatore; rimuovere il sito dalla configurazione se non vale. |
| Username digitato male ma sintatticamente plausibile | Non verificabile dal solo foglio; i segnaposto noti sono bloccati, le correzioni osservate richiedono revisione. |
| Omonimi realmente distinti oltre 20 giorni | Revisione prevista: maggiore lavoro manuale, nessun riuso automatico della vecchia mail. |
| Stessa persona con dati mancanti o stesso username in due righe | Revisione conservativa; possibile duplicato/correzione. |
| Nomi normalizzati coincidono accidentalmente | Revisione o separazione prudente nello stesso sito; la ricerca storica tra siti conserva il limite del solo nome. |
| Più persone, alcune recenti e altre lontane nel tempo | L'incertezza prevale: revisione dell'intero caso. |
| Indirizzi già assegnati o richieste già presenti prima dell'aggiornamento | Non corretti/cancellati retroattivamente; fermare e verificare la coda prima dell'attivazione. |
| Errori o duplicazioni dei metadati / schema del registro errato | Errore bloccante: nessun fallback che assegni email o accodi la destinazione interessata. |
| Timeout fra invio Telegram e salvataggio del contrassegno | Possibile avviso duplicato al retry; nessuna assegnazione automatica causata dall'errore. |

## Verifica e rilascio

- VERSION: 1.3.21; nessuna modifica a worker, immagini, Compose, data/ o secrets/.
- node tests/emailmatcher.test.cjs esercita lo script effettivo con Google Sheets,
  proprietà, metadati, lock e notifiche simulati, senza rete o credenziali.
- python -m unittest discover -s tests -v include il nuovo test Python, che
  esegue la suite JavaScript. In Docker usa anche il Node incluso nel driver
  Playwright se node non è nel PATH: nessun nuovo pacchetto di produzione.
- Le API di metadati sono documentate da Google:
  [Range](https://developers.google.com/apps-script/reference/spreadsheet/range),
  [DeveloperMetadataFinder](https://developers.google.com/apps-script/reference/spreadsheet/developer-metadata-finder),
  [funzioni private](https://developers.google.com/apps-script/guides/html/communication#private_functions).

### Esito locale — 14 novembre 2026

- 64 casi JavaScript di regressione sul matcher: tutti superati.
- Integrazione tramite unittest (test_emailmatcher.py): superata.
- Suite applicativa completa: 289 test, 287 superati e 2 errori di ambiente Windows.
  I due test esistenti non sono stati modificati:
  - test_telegram_panel.ControlsTests.test_missing_malformed_oversized_or_symlink_report_is_not_healthy:
    WinError 1314, creazione di link simbolici non autorizzata dal sistema.
  - test_tester_stats.LedgerTests.test_restart_preserves_count_reset_and_counting_start:
    WinError 32, il database temporaneo è ancora aperto quando il test elimina la directory.
- Ambiente locale: Python 3.14, dipendenze esatte di requirements.txt; tzdata aggiunto
  solo nell'ambiente di test Windows. Il sistema Linux di produzione fornisce i fusi orari.
- Sintassi Apps Script verificata con Node e git diff --check senza errori.
- Nessun accesso ai fogli live, nessuna notifica reale e nessun deploy eseguito.
- Prima del rilascio finale occorre eseguire il controllo nel normale ambiente Linux
  di deploy e il collaudo Apps Script: i test simulati non certificano autorizzazioni
  Google, conservazione dei metadati durante operazioni manuali o configurazione del Banco.

Preparare e pubblicare commit/tag con la procedura Git già presente; non spostare tag
esistenti. Il normale mulino-deploy check verifica il tag e i test offline.
L'installazione del file Apps Script è separata: mulino-deploy aggiorna il worker
Docker e NON pubblica EmailMatcher nel progetto Google.

Per attivare: mettere in pausa il worker e attendere le operazioni in corso come
descritto in ops/deploy/README.md; controllare le richieste già accodate e le mail
già associate; sostituire il solo file EmailMatcher nel progetto Apps Script,
fare anteprima e verificare il Log; provare una destinazione verificata.
Se la web app usa una versione fissa del progetto, pubblicarne una nuova versione
seguendo il processo esistente di Il Banco. Riprendere il worker solo dopo verifica.

Il rollback del solo container non ripristina Apps Script né i fogli Google.
Per ripristinare il comportamento precedente occorre rimettere il precedente
EmailMatcher nel progetto e ripubblicare la versione web app se necessario;
metadati e registro sono aggiuntivi e possono restare, senza cancellazioni.
