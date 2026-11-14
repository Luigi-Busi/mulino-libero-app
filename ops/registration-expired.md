# Scadenza esplicita della registrazione — v1.3.25

Installata il 14 novembre 2026 dopo autorizzazione del proprietario.
Verificate pausa, assenza di registrazioni attive e assenza di attese umane.
La pausa è stata mantenuta. La ripartenza riguarda la stessa persona.

## Comportamento

La schermata fornita mostra il messaggio esatto «Tempo di registrazione scaduto.
Inizia una nuova registrazione.» sul modulo con username e password.
Il riconoscimento richiede HTTPS sul dominio registrazione.libero.it,
messaggio visibile completo, campi iniziali visibili e assenza di OTP visibile.
Il controllo si applica alle attese periodiche e prima delle azioni, incluso
il controllo del CAPTCHA senza cambio di URL. Un timeout del browser viene
ricontrollato prima di classificarlo come errore generico.

Il browser scaduto viene chiuso dalla pulizia esistente. Si avvia una nuova
istanza di RegistrationBrowser e un nuovo contesto, con gli stessi dati reali
già forniti e lo stesso ID richiesta/account: nessuna nuova riga in Coda.
Si invalidano claim, codice, reinvio e tester precedenti prima delle attese
di rete; un claim in corso viene atteso prima di svuotare i campi della coda.
Si eliminano i vecchi avvisi tramite il registro esistente e si avvisano tester
e amministratore. Il numero viene richiesto nuovamente nella nuova sessione.

Massimo due ripartenze automatiche nella stessa esecuzione; alla terza scadenza
si passa a ERRORE con le normali istruzioni di revisione. Il recupero dopo
riavvio rimane quello esistente, senza una nuova ripartenza automatica.
Pausa, annullamento, destinazione modificata o SMS già verificato impediscono
di iniziare un altro browser. Un esito locale già creato protegge dalla duplicazione.

## Verifica e rischi

Test con HTML locale, identità fittizie e Telegram/Sheets simulati. La fotografia
non fornisce il DOM reale; si usano i campi iniziali già conosciuti dal bot.
Le nuove regressioni coprono banner nascosto, altro dominio, OTP sovrapposto,
reset generico, attesa CAPTCHA, stessa persona, limite dei tentativi,
annullamento e invalidazione dell'assegnazione precedente.

Falso positivo: evitato richiedendo tutti i segnali insieme; un reset generico
non autorizza il riavvio. Dopo SMS già verificato o esito salvato si conserva
la revisione per non rischiare la creazione duplicata.
Falso negativo: testi o struttura diversi mantengono la gestione d'errore
esistente. Il primo episodio reale resta da osservare dopo l'installazione.

## Rilascio

Installazione confermata: v1.3.25, commit d881521692fd7518b545e0ca191cb761c8e52776.
319 test e controlli preliminari superati. Controller senza transazioni pendenti,
Git/immagine/mount/configurazione coerenti. v1.3.24 conservata per ripristino.

Seguire ops/deploy/README.md; installare soltanto con pausa persistente e senza
registrazioni attive. Compatibile con v1.3.24: nessuna modifica a data/, secrets/,
Whitelist, Apps Script, colonne o durata del timeout del tester.
