# Archivio condiviso delle versioni Docker — Mulino Libero

Il sistema conserva tutte le immagini immutabili delle release in un unico
archivio nativo Docker compresso. Gli strati comuni occupano spazio una sola
volta. Non usa differenze binarie da applicare in catena e non richiede un
servizio, un abbonamento o un collegamento a Internet per recuperare le immagini.

## File e copie

- Indice sul VPS: `/var/lib/mulino-deploy/releases/shared-images.json`.
- Archivio sul VPS: `/var/lib/mulino-deploy/images/shared/<sha256>.tar.gz`.
- I vecchi nomi `/var/lib/mulino-deploy/images/<immagine>.tar` sono collegamenti
  fisici allo stesso archivio. Sommare le loro dimensioni apparenti conterebbe
  piu volte lo stesso spazio: usare `du -x` oppure contare gli inode distinti.
- Copia cifrata per il PC: `/srv/mulino-backups-export/history/`.
- Copia cifrata verificata sul PC: `C:\Backup\Mulino-Libero\Archivio-versioni`.
- Copie originali precedenti alla migrazione, conservate sul PC:
  `C:\Backup\Mulino-Libero\Sistema\Recupero\Archivi-pre-condivisione-20261002`.

La cifratura usa la chiave pubblica di recupero gia configurata. La chiave
privata resta separata sul PC. Le immagini contengono programma e dipendenze;
i dati, le credenziali e gli altri file del sistema restano nei backup cifrati
completi esistenti. Questo archivio non sostituisce quei backup.

## Nuove versioni e interruzioni

La preparazione di una nuova release conserva tutte le immagini gia indicizzate,
aggiunge quella nuova, verifica ogni configurazione e strato, produce la copia
cifrata e poi pubblica il nuovo indice. I collegamenti vengono aggiornati
singolarmente in modo atomico. I vecchi file restano validi durante questo
passaggio, perche ogni nuova generazione include tutte le immagini precedenti.
Un'interruzione puo lasciare un archivio provvisorio o collegamenti da completare;
non viene considerata una nuova release attivata. La preparazione successiva
completa i collegamenti. Il controller mantiene i controlli di pausa e salute.

Il salvataggio avviene durante la preparazione di una nuova versione, non ogni
giorno. La sincronizzazione PC esistente scarica l'archivio cifrato aggiornato
quando il PC e acceso e raggiunge il VPS. La vecchia copia PC viene rimossa solo
dopo la verifica della nuova e della presenza di tutte le immagini precedenti.

## Recupero sullo stesso VPS

I comandi di deploy e rollback rimangono gli stessi. Se un'immagine manca da
Docker, il controller verifica l'impronta dell'archivio e la carica, quindi
controlla l'identita immutabile richiesta. La versione precedente e il
last-known-good non cambiano con questa migrazione.

## Recupero su un nuovo server

1. Eseguire prima il recupero completo esistente su un server vuoto, con Docker
   configurato con `overlay2` come indicato nella guida completa. Lasciare i
   servizi reali fermi: non attivare una seconda copia del bot.
2. Sul PC usare `Decifra-Archivi.ps1`, indicando una cartella di destinazione
   nuova. Lo script verifica la copia cifrata, la decifra nella cartella protetta
   e confronta impronta e dimensione con l'archivio originale.
3. Trasferire sul nuovo server solo `<sha256>.tar.gz` e `shared-images.json`
   dalla cartella di recupero. Non trasferire il keyring o la chiave privata.
4. Installare l'archivio in `/var/lib/mulino-deploy/images/shared/` con permesso
   0600 e l'indice in `/var/lib/mulino-deploy/releases/`. Controllare SHA256.
   L'indice deve riferirsi proprio al nome e all'impronta del file trasferito.
5. Caricare l'archivio con `docker image load -i <archivio>` e verificare ciascun
   ID elencato nell'indice. Le versioni si ritrovano nei record delle release
   e nei tag del repository ripristinato dal backup completo.
6. Eseguire i controlli di recupero completi prima della ripresa del servizio.

Un'immagine contiene il programma, non una copia storica dei dati. Per passare
a una versione molto vecchia occorre anche verificarne la compatibilita con i
dati correnti. Non usare le vecchie versioni come prova sulla produzione.

## Tornare alla conservazione precedente

Con il lock del deploy acquisito e nessun deploy in corso, ricaricare dal PC
gli archivi originali e verificarli usando `legacy-index.json`. Ripristinare il
controller originale conservato nel pacchetto di questa migrazione e rimuovere
l'indice condiviso solo dopo aver rimesso al loro posto le copie per versione.
Non cambiare lo stato del deploy, il programma in esecuzione, i dati o i segreti.

Il backup completo notturno conserva automaticamente il controller, il modulo
`image_store.py`, questa documentazione e l'indice dentro la cartella delle
release. Le immagini storiche si recuperano dalla copia cifrata aggiuntiva sul
PC. I backup completi di prima della migrazione continuano a essere utilizzabili
con la loro procedura originale.
