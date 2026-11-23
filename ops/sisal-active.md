# Sisal Active

Il monitor Libero riconosce il mittente `infoclienti@sisal.it` e l'oggetto
`La tua richiesta di prelievo è stata inoltrata`. Legge l'importo e il nuovo
saldo dalle due frasi del corpo. Il ricevitore del Banco controlla il foglio
e identifica l'account dalla casella. Se la stessa casella corrisponde a più
account, il ricevitore non attribuisce il prelievo a nessuno.

Il foglio `Sisal Active` usa le intestazioni esistenti. A:G contengono data
di apertura, tipo, diffida, nominativo, username, password Sisal ed e-mail.
I contiene il saldo attuale e J l'importo del prelievo. H rimane disponibile
per la gestione esistente. Un nuovo prelievo aggiorna la stessa riga per
tipo e username. Le ripetizioni dello stesso messaggio e gli eventi più
vecchi non sovrascrivono i dati. Il codice copia F direttamente tra celle
di Google Sheets e non legge il valore della password Sisal.

Le caselle @libero.it di Sisal Sport e Sisal Slot 600 sono idonee se la cella
E-mail non è rossa. L'operazione usa il collegamento autenticato esistente
del Banco. Il monitor e il Banco si scambiano e-mail, importi, data e ID
evento. Il mittente, l'oggetto e le frasi sono verificati prima dell'invio
di un evento. Nessun corpo o password Sisal è incluso nel payload.

La pubblicazione Apps Script 47 integra il ricevitore sul deployment esistente
(precedente 46). Le prove locali si eseguono con `node tests/sisal-active.test.cjs`
o con la suite `test_emailmatcher.py`. Il ricevitore pubblicato è stato anche
verificato respingendo un evento incompleto senza scrivere righe.
Il monitor ha una sua release indipendente sul ramo del monitor.
