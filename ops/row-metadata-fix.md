# Metadati di riga e accodamento — v1.3.29

Durante un allineamento mirato, l'API reale ha rifiutato il salvataggio iniziale
di EM_REGISTRAZIONE_V1. Il rettangolo getRange(row,1,1,getMaxColumns()) ha
estremi di colonna espliciti e non può ricevere metadati con posizione ROW.
I test precedenti verificavano soltanto la larghezza, quindi non riproducevano
questo vincolo e non avevano individuato il blocco prima della prova reale.

Si usa ora getRange(row + ':' + row), lasciando entrambe le colonne non
delimitate. Il simulatore richiede questa rappresentazione e rifiuta il vecchio
rettangolo, anche se largo quanto la griglia. Aggiunta una regressione dedicata.
Riferimento: [Range e limiti delle colonne](https://developers.google.com/apps-script/reference/spreadsheet/range#isStartColumnBounded()).

## Verifica

- Superate le cinque suite Python che eseguono i sorgenti Apps Script sotto Node,
  comprese le regressioni degli omonimi, dei callback e dei nuovi fogli.
- Verifica reale su due righe esplicitamente richieste dal proprietario: normale
  accodamento EmailMatcher riuscito per entrambe, ID account/richiesta distinti.
- La scelta NUOVA_MAIL per l'omonimo è persistente; nessuna copia della mail
  dell'altro account. La riga inserita manualmente usa il normale percorso di ricerca.
- Coda riletta: una sola nuova richiesta per account. Il Mugnaio attivo ha
  preso in carico la prima; la seconda rimane nel flusso seriale normale.
- Nessuna delle precedenti richieste in errore è stata riavviata o modificata.

Per eseguire le funzioni originali senza compilare la Coda a mano è stata usata
una manutenzione temporanea autenticata, con nonce e due destinazioni fisse,
precondizioni su file/foglio/riga/nome/username e controllo dell'email vuota.
Le prove offline hanno verificato chiave errata, nonce errato e separazione del
Segretario. La prima esecuzione ha evidenziato il difetto; dopo la correzione
la seconda ha accodato correttamente. Nessuna richiesta Telegram è stata simulata
come proveniente da una persona reale.

## Pubblicazione e rischio

Versione Apps Script definitiva: 46. Il Codice.gs operativo originale è stato
ripristinato e coincide con il precedente SHA-256
a35e639516a3ff0bfcf90fb183c0a64971ac7518e4510c5760548d22fc68d325;
il percorso temporaneo non è più pubblicato. EmailMatcher corretto SHA-256:
47be49e4e587809a6320796fb59d5f057d419146f7cb5552d496090d501bb5eb.
Altri tre file, endpoint e accessi invariati. Le versioni temporanee non sono
deployment attivi. Ricevute private di pubblicazione/ripristino fuori dal repository.

Nessuna modifica alle regole di associazione delle mail, ai vecchi metadati,
alla struttura della Coda o al worker: il Mugnaio rimane v1.3.28 senza riavvio.
La modifica riguarda solo la creazione di nuovi metadati di riga. Ripristinare
la versione 43 ripristinerebbe anche il difetto: non è un rimedio operativo.
Nessuna modifica manuale a data/ o secrets/; le scritture ai fogli sono state
eseguite dalle funzioni di produzione con i normali ID e controlli.
