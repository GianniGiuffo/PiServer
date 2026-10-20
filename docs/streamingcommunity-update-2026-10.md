# StreamingCommunity 2.6.0, 20 ottobre 2026

Downloader e bridge Seerr usano entrambi la release stabile
[`2.6.0`](https://github.com/EdoardoFiore/StreamingCommunity-downloader/releases/tag/v2.6.0),
pubblicata il 20 ottobre, con riferimento riproducibile:

```text
ghcr.io/edoardofiore/streamingcommunity-downloader:2.6.0@sha256:196ad5c6915cae31d0f2e72ca9c4756e5744dd90cb64700e81e0832d83324eae
```

La versione sostituisce la build `latest` del 27 settembre, che dichiarava
`2.3.3`. Il commit upstream della nuova immagine è
`3049d778d0bc7aa1a91c07343e75709da188a9a2`. La PR Renovate
[#18](https://github.com/GianniGiuffo/PiServer/pull/18) proponeva un digest
precedente insieme ai pin di altri dodici servizi: è superata per
StreamingCommunity e viene chiusa senza applicare quei cambiamenti estranei
all'intervento.

## Deploy e ripristino

Prima del deploy non risultavano download attivi. Il backup giornaliero
riportava un ultimo successo il 20 ottobre alle 05:15 Europe/Rome. Sono state
inoltre create copie SQLite coerenti di downloader, bridge e Seerr, con
verifica di integrità, e copie protette di `.env` e della configurazione del
bridge. Queste copie rimangono sul mini-PC in:

```text
/home/tommaso/service-backups/streamingcommunity-20261020T200508Z
```

La directory è accessibile soltanto all'amministratore; contiene credenziali
e non deve essere aggiunta a Git. Le sottodirectory `stage-sc` e
`stage-bridge` sono copie di prova, non le copie originali di ripristino.

La nuova immagine avvia correttamente una copia della configurazione su rete
Docker isolata. La migrazione del database a schema 10 conserva le 34
richieste e supera `PRAGMA integrity_check`. Anche i nove test di
`tests/test_seerr_priority.py` passano nella nuova immagine senza rete.

Il deploy ha fermato prima il bridge e poi il downloader, modificato la sola
variabile `STREAMINGCOMMUNITY_IMAGE` del `.env` di produzione e ricreato i due
servizi con `--no-deps`, attendendone gli healthcheck. Il mount media è stato
verificato prima dell'avvio. Seerr, il frontend e gli altri servizi non
richiedono aggiornamenti per questa release.

Per un rollback fermare bridge e downloader, ripristinare la precedente
variabile immagine da `stack.env` e il database/configurazione da `sc`.
Ripristinare anche `bridge` se occorre tornare al suo stato precedente;
`seerr` contiene la copia coerente del suo database. Non sovrascrivere dati
con nuove richieste senza averli prima salvati. Ricreare poi downloader e
bridge con il riferimento precedente. Non avviare la vecchia immagine sul
database migrato senza averne verificato la compatibilità.

## Dominio della fonte e verifiche

La ricerca inizialmente rispondeva 502: il dominio salvato
`streamingcommunityz.vin` risultava NXDOMAIN anche dal DNS pubblico. La pagina
usata dall'applicazione per il recupero del dominio indica un indirizzo che
reindirizza a `streamingcommunityz.build`. Il dominio canonico è stato
convalidato con i controlli dell'applicazione, una pagina Inertia valida e una
ricerca riuscita, quindi salvato nella configurazione del downloader.

La pagina di recupero `telegra.ph` non risolve dal DNS LAN del mini-PC, pur
avendo un record pubblico. Questo limite preesistente del recupero automatico
rimane: le impostazioni DNS e `domain_auto_apply=false` non sono state
modificate. In caso di una futura rotazione, verificare il dominio proposto
prima di salvarlo.

Verifiche sul servizio aggiornato:

- downloader e bridge `healthy`, entrambi sulla stessa immagine fissata;
- login Jellyfin del bridge e lettura autenticata delle richieste riusciti;
- 34 richieste del downloader invariate: 27 completate, 6 fallite e 1 negata,
  con gli stessi stati già presenti prima dell'intervento;
- 7 richieste Seerr leggibili; 8 lavorazioni storiche del bridge invariate
  (`done=3`, `fallback_done=5`);
- ricerca film e serie riuscita, con 45 e 8 risultati rispettivamente per le
  due query di prova, e API metadati film funzionante;
- webhook di prova autenticato: 202; webhook senza token: 401;
- API di stato Radarr e Sonarr raggiungibili dal bridge; entrambi restano
  assenti dalle impostazioni Seerr, come richiesto dalla priorità del bridge;
- login del downloader e API di stato attraverso il frontend Seerr: 200;
- lookup TVDB attraverso il frontend senza sessione: 401, come previsto.

Le prove non creano nuove richieste né avviano download. Verificano la
connettività e le API reali; i test isolati verificano la logica di instradamento
e fallback.
