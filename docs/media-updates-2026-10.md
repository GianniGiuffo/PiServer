# Pulizia e aggiornamenti media del 13 ottobre 2026

La configurazione attuale comprende Vaultwarden 1.37.4, Prowlarr
2.6.5.5623, Jellyfin 12.2 e Seerr 3.5.0, fissati a digest in `.env.example`.
Le note originali sono disponibili per
[Vaultwarden](https://github.com/dani-garcia/vaultwarden/releases/tag/1.37.4),
[Prowlarr](https://github.com/Prowlarr/Prowlarr/releases/tag/v2.6.5.5623),
[Jellyfin](https://github.com/jellyfin/jellyfin/releases/tag/v12.2) e
[Seerr](https://github.com/seerr-team/seerr/releases/tag/v3.5.0).

Il controllo pre-deploy usa copie dei database e della configurazione su
una rete Docker isolata, senza connessione ai servizi di produzione o a
Internet. Le quattro applicazioni si avviano con le nuove immagini.
La copia Seerr migrata conserva i campi e le API richieste dal bridge:
`media_request.id`, `status`, `requestedById`, `type`, `updatedAt` e
`GET /api/v1/request/{id}`. Il controllo esercita la presa in carico SQL
e la sua idempotenza sul database migrato senza avviare download.

Seerr 3.5 cambia le API usate per sincronizzare o attivare le librerie:
la sincronizzazione usa ora `POST /settings/jellyfin/library/sync`, e
l'attivazione `PUT /settings/jellyfin/library/{libraryId}`. Il bridge locale
non usa questi endpoint. Radarr e Sonarr devono continuare a essere assenti
dalle impostazioni Seerr: il fallback rimane responsabilità del bridge.

Jellyfin 12.2 carica correttamente Jellyfin Helper 3.0.0.2 con le patch locali
e File Transformation 3.0.1.0. Questi plugin restano alle versioni verificate:
un loro aggiornamento separato richiede la revisione delle patch e della
discovery. Le migrazioni dei database applicativi avvengono all'avvio;
un rollback richiede anche la copia dei database precedente all'aggiornamento.

La pulizia elimina i due servizi ritirati, i relativi container, immagini
inutilizzate, directory di stato/cache, variabili immagine e segreti dedicati.
Rimuove la porta Tailscale 8462, le card Homepage, i riferimenti nei Compose,
negli script di bootstrap, avvio, stop, aggiornamento, backup e in Renovate.
Il workflow n8n conserva gli altri nodi e viene ripubblicato dopo la rimozione
del solo strumento di ricerca e della sua credenziale dedicata.
I database n8n e gli altri servizi condivisi rimangono necessari.

Prima del deploy eseguire e verificare un backup Restic coerente, quindi:

1. fermare frontend e bridge prima di aggiornare Seerr e Jellyfin;
2. conservare una copia protetta del `.env` e dei database;
3. applicare ai `.env` le sole immagini approvate;
4. ricreare singolarmente Vaultwarden, Prowlarr, Jellyfin e Seerr;
5. attendere gli healthcheck e verificare plugin, librerie e API;
6. riavviare bridge e frontend, confrontare utenti, richieste e stato durevole;
7. rigenerare Homepage dopo la rimozione della card con
   `curl -fsS -X POST http://127.0.0.1:3000/api/revalidate`.

Le vecchie copie nei backup cifrati restano disponibili per il ripristino.
Non eseguire pulizie globali dei volumi Docker o dei database condivisi.
