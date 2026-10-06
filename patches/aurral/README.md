# Aurral 2.10.0: validation, version fallback, and download queue

`postDownloadValidator-2.10.0.js` is the upstream v2.10.0 file with three changes:
use the embedded title unchanged for the identity comparison; apply
`claimedTitle()` only when falling back to a filename. In 2.10.0 that helper
keeps only the last segment of a string separated by ` - `, so a correctly
tagged `MONTAGEM URANIUM - Slowed` becomes just `Slowed` and fails validation.
The Beets comparison also uses `getCoreTitle()` on the candidate, as it
already does on the request and on search candidates. Version differences
are checked by the semantic policy before this comparison; a regular
recording still fails a request for Slowed or Super Slowed.
Finally, the file's actual title takes precedence over a search candidate's
version flags. A result advertised as Super Slowed must not make a file
tagged Slowed pass the requested-version checks.

The other 2.10.0 modules add the explicitly configured behavior for playlist
requests: every enabled source gets a chance to find the requested version;
after all fail, a second pass searches for the normal version. After that
pass fails the job is Missing. A normal request has only one pass, and library
requests and quality upgrades never substitute a different recording.
`versionFallback.js` resets candidate and source state between passes.
`playlistDownloadUtils` clears the special version's recording/release MBIDs
and duration only in the normal pass; the special version's length cannot
validate a normal recording. Tags and final filenames use the actual normal
title, while the playlist retains its requested track. `semanticPolicy`
also distinguishes Slowed, Super Slowed, and Ultra Slowed, so the requested
speed level is preferred across sources before trying a normal recording.

`config/aurral/yt-dlp.conf` also embeds the video's own metadata and parses
`Artist - Title` before downloading. This preserves source evidence before
Aurral validates it. It does not write the requested title or artist into an
unverified download, and it leaves flat search JSON unchanged.

The compose mounts these files read-only. The backports are specific
to `ghcr.io/lklynet/aurral:2.10.0`. Before upgrading Aurral, review every
patched module and its mount, then remove or rebase it as appropriate.
Never carry the 2.10.0 modules into a different version without checking
their imports, API, and database compatibility. The yt-dlp configuration
can remain if compatible, but does not implement the normal-version pass
by itself. See the upgrade procedure below.

Upstream source: <https://github.com/lklynet/aurral/tree/v2.10.0>
(commit `832ae3dfdfe7cec124e392a60df7356736c6737a`), MIT license in `LICENSE`.

Run the offline integration checks inside the Aurral container:

```sh
docker cp tests/test_aurral_ytdlp.py raspberry-server-aurral-1:/tmp/test_aurral_ytdlp.py
docker exec raspberry-server-aurral-1 python3 /tmp/test_aurral_ytdlp.py /etc/yt-dlp.conf
docker cp tests/aurral_version_fallback.test.mjs raspberry-server-aurral-1:/tmp/aurral_version_fallback.test.mjs
docker exec raspberry-server-aurral-1 node --test /tmp/aurral_version_fallback.test.mjs
docker cp tests/aurral_pipeline_performance.test.mjs raspberry-server-aurral-1:/tmp/aurral_pipeline_performance.test.mjs
docker exec raspberry-server-aurral-1 node --test /tmp/aurral_pipeline_performance.test.mjs
```

The tests download synthetic audio from a temporary loopback HTTP server,
check the tags with ffprobe, and use the actual Aurral validator with a
temporary database. Matching Slowed/Super Slowed tracks must pass; a wrong
version, karaoke, or a different track must fail.

## File installati

I sette moduli con suffisso `-2.10.0.js` derivano dalla release upstream;
`versionFallback.js` e `pipelinePerformance.js` sono helper locali nuovi. Il compose monta tutti i file
in sola lettura nei percorsi seguenti.

| File nel repository | Percorso nel container | Scopo |
| --- | --- | --- |
| `config/aurral/yt-dlp.conf` | `/etc/yt-dlp.conf` | Incorpora i metadati originali prima della validazione, senza alterare i risultati delle ricerche. |
| `patches/aurral/postDownloadValidator-2.10.0.js` | `/app/backend/services/trackMatching/postDownloadValidator.js` | Conserva il titolo nei tag, confronta simmetricamente i titoli principali e dà precedenza alla versione dichiarata nel file. |
| `patches/aurral/semanticPolicy-2.10.0.js` | `/app/backend/services/trackMatching/semanticPolicy.js` | Distingue Slowed, Super Slowed e Ultra Slowed. |
| `patches/aurral/slskdOrchestrator-2.10.0.js` | `/app/backend/services/slskdOrchestrator.js` | Prova tutte le sorgenti per la versione richiesta, poi la normale; cede il worker dopo ogni query e controlla gli stalli dei peer. |
| `patches/aurral/playlistDownloadUtils-2.10.0.js` | `/app/backend/services/playlistDownloadUtils.js` | Costruisce il contesto della versione normale senza riutilizzare durata e identificativi della versione speciale. |
| `patches/aurral/ytdlpOrchestrator-2.10.0.js` | `/app/backend/services/ytdlpOrchestrator.js` | Usa il titolo effettivamente risolto nel nome del file importato. |
| `patches/aurral/versionFallback.js` | `/app/backend/services/versionFallback.js` | Gestisce i due passaggi, azzera candidati e stato tra sorgenti e impedisce ulteriori cicli dopo il tentativo normale. |
| `patches/aurral/honkerDb-2.10.0.js` | `/app/backend/services/honkerDb.js` | Assegna priorità ai fallback senza scavalcare poll, download e importazione. |
| `patches/aurral/weeklyFlowDownloadTracker-2.10.0.js` | `/app/backend/services/weeklyFlow/weeklyFlowDownloadTracker.js` | Consulta la coda persistente prima di reinviare un job o azzerare un download al riavvio. |
| `patches/aurral/pipelinePerformance.js` | `/app/backend/services/pipelinePerformance.js` | Definisce priorità, attesa della ricerca e progresso dei trasferimenti in base al tempo reale. |

Gli errori dei tentativi del secondo passaggio sono identificati da
`Normal version:`. Dopo una correzione usare **Re-search missing tracks**
sulla singola playlist per riprovare i job falliti senza riscaricare quelli
completati. Missing può indicare anche un rifiuto della validazione o un
errore YouTube `403`: il fix non garantisce che ogni brano sia reperibile.

Nella verifica del 6 ottobre 2026 sono passati i test e un download YouTube
reale di `ZAYLO - MONTAGEM URANIUM (Slowed)` è stato validato contro la
richiesta della playlist. Sono stati rimessi in coda i 36 job falliti di
PhonkForAurral mantenendo i 9 completati; questo documenta l'avvio del
recupero, non certifica il completamento dei 36 download.

## Coda e prestazioni

La verifica successiva del 6 ottobre ha individuato 96 elementi di pipeline
per i 30 brani ancora attivi, con fallback YouTube in attesa da ore e peer
Soulseek fermi a zero byte. I riavvii del worker ricreavano le ricerche pur
avendo già tentativi persistenti. Il conteggio di 600 poll, nominalmente
ogni 3 secondi, non limitava a mezz'ora l'attesa reale quando ogni ricerca
occupava l'unico worker per molti minuti.

La patch preserva la coda ai riavvii, salva i risultati di ogni query e
cede il worker prima della successiva. Le query attendono fino a 20 secondi
con risultati, o i 10 secondi upstream senza risultati, e vengono chiuse
dopo aver raccolto le risposte, senza l'ulteriore attesa di assestamento.
API lente, rate limit e ranking possono aggiungere tempo: non è una scadenza
assoluta di 20 secondi per l'intero turno. Le priorità sono ricerca iniziale
0, ricerca di fallback 5, poll 10, download 20, importazione 30; gli upgrade
mantengono la penalità upstream di 100 punti.

Per i trasferimenti Soulseek con ID, 180 secondi senza incremento dei byte
fanno passare al candidato successivo, senza ritentare lo stesso peer
bloccato. Il contatore di poll upstream resta come limite aggiuntivo.
All'avvio di ogni candidato si azzerano tempo e byte; al cambio di sorgente
o versione si azzerano anche i risultati delle ricerche. La validazione del
file e l'ordine versione richiesta → versione normale restano obbligatori.

`aurral_pipeline_performance.test.mjs` verifica priorità e tempo reale, poi
usa i moduli montati con un database temporaneo e un client Soulseek simulato
per controllare riavvio, assenza di reinvii, una query per turno e passaggio
al candidato successivo. Non usa i download o le credenziali di produzione.

La riparazione effettuata ha mantenuto un solo tentativo utile per brano:
96 → 30 elementi, eliminando 66 duplicati e 4 trasferimenti a zero byte
appartenenti ai tentativi superati. Il database precedente è stato salvato
in `/srv/raspberry-server/data/aurral-fallback-backup-20261006/performance/`.
I moduli e il compose precedenti sono in `patches-before.tgz` nella stessa
directory. La riparazione non certifica il completamento dei download.

Per ripetere il recupero su una playlist, usare lo script incluso: per
default mostra soltanto cosa manterrebbe. `--apply` richiede Aurral fermo,
il gruppo worker `maintenance` e un mount scrivibile `/repair-backup`;
crea prima un backup SQLite coerente, poi riaccoda un solo tentativo utile
per brano mediante l'API Honker. Mantiene completamenti e trasferimenti con
byte già ricevuti; elimina solo trasferimenti a zero byte con ID espliciti
dei tentativi scartati della playlist. Non eseguire durante un worker attivo.

```sh
cd /opt/raspberry-server
docker compose -f compose.yaml -f compose.media.yaml run --rm --no-deps -T \
  -v /opt/raspberry-server/scripts:/tmp/aurral-tools:ro \
  -e AURRAL_BACKGROUND_WORKER_GROUP=maintenance --entrypoint node aurral \
  /tmp/aurral-tools/aurral-repair-pipeline.mjs PLAYLIST_ID
# Per applicare: fermare aurral, aggiungere il mount del backup e --apply,
# quindi ricreare/avviare solo aurral con il compose aggiornato.
```

## Aggiornare Aurral

**Il fix è specifico per Aurral `2.10.0`: va rivisto prima di aggiornare.**
I mount sostituiscono i moduli dell'immagine anche dopo un cambio di tag:
aggiornare Docker non aggiorna questi file.

1. Creare e verificare un backup di database e configurazioni. Conservare
   anche il compose e i file delle patch utilizzati prima dell'aggiornamento.
2. Confrontare la versione di destinazione con tutti e sette i moduli
   derivati e con i due helper. Verificare import, API, schema del database e
   comportamento delle code; il nome del file non prova la compatibilità.
3. Rimuovere i mount delle correzioni già presenti upstream. Adattare e
   versionare le patch ancora necessarie sulla nuova base e aggiornare i
   mount associati. Rimuovere il solo validatore non rimuove gli altri
   moduli del fallback.
4. Conservare `yt-dlp.conf` soltanto se compatibile con il downloader della
   nuova immagine. Questa configurazione preserva i metadati, ma non
   implementa da sola il secondo passaggio alla versione normale.
5. Dopo la revisione, cambiare `AURRAL_IMAGE` in `.env`, validare il compose,
   scaricare l'immagine e ricreare il solo servizio Aurral. Eseguire i test
   sopra, adattandoli se cambia l'API upstream, e verificare un caso reale
   della versione richiesta e un caso di ripiego alla normale.
6. Confermare che Aurral sia healthy e che i file della normale non ricevano
   titolo o identificativi della versione speciale. Solo allora riprendere
   la ricerca dei missing.

`scripts/update-images.sh media` scarica le immagini selezionate in `.env`:
**non verifica, aggiorna o rimuove questi backport**. Non usare il nuovo tag
con i moduli 2.10.0 ancora montati senza aver completato la revisione.

Per tornare indietro ripristinare il tag, il compose e le patch precedenti.
Se la nuova versione ha migrato il database, ripristinare anche il backup
coerente precedente: il cambio del solo tag non annulla la migrazione.
