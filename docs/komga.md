# Komga: fumetti e manga da browser e Android

Komga legge i file già gestiti da Kapowarr in `/srv/media/Comics` e serve le
singole pagine al lettore. Non serve scaricare l'intero CBZ sul dispositivo
prima di iniziare. L'immagine `gotson/komga:1.29.2` è fissata per digest.

## Storage e sola lettura

- `/srv/media/Comics` è montata come `/comics` **in sola lettura**.
- `/srv/raspberry-server/data/komga` sull'SSD è montata come `/config` ed è
  scrivibile da `PUID:PGID`. Contiene database, account, progressi di lettura,
  metadati e miniature. Il salvataggio dei progressi non modifica i fumetti.
- La libreria **Fumetti** usa `/comics`. Conversione degli archivi e
  correzione delle estensioni sono disabilitate, perché scriverebbero nei
  media. Non usare le funzioni di importazione o cancellazione dei file di
  Komga: Kapowarr rimane il gestore dei file.
- Lo stack media gestisce avvio/arresto solo dopo la verifica del mount.
  Il backup arresta brevemente Komga per acquisire entrambi i database
  SQLite coerenti, poi lo riavvia se il mount è valido. I fumetti rimangono
  esclusi dal backup delle configurazioni.

## Accesso privato e primo account

URL: `https://TAILSCALE_FQDN:8467/`. Tailscale Serve inoltra le richieste a
`127.0.0.1:25600`; la porta Docker è pubblicata soltanto su loopback. Non
configurare Cloudflare Tunnel o Tailscale Funnel per Komga.

Il login di Komga è separato da Jellyfin. Le credenziali iniziali generate
durante il setup rimangono fuori da Git in
`/etc/raspberry-server/komga-admin.json`, leggibile soltanto da root.
Cambiare la password dall'account Komga dopo il primo accesso; il file
iniziale non viene aggiornato automaticamente dopo il cambio password.

## Android

Con Tailscale connesso, aprire lo stesso URL in Chrome/Firefox e accedere:
il lettore web serve le singole pagine e salva il punto di lettura. Si può
aggiungere il collegamento alla schermata Home dal browser Android.

Per un'app nativa si può usare Mihon con l'estensione ufficiale Komga dal
repository Keiyoushi. Configurare l'indirizzo
`https://TAILSCALE_FQDN:8467` senza slash finale, email e password Komga.
Attivare il tracciamento Komga in Mihon per sincronizzare i progressi.
La modalità download rimane facoltativa per la lettura offline.

## Verifiche del deploy

Il 29 ottobre 2026 sono stati verificati:

- accesso HTTPS Tailscale, pagina web mobile e API autenticate;
- porta `25600` irraggiungibile sull'indirizzo LAN e assenza di Funnel;
- mount `/comics` in sola lettura e rifiuto effettivo di una scrittura con
  errore `Read-only file system`;
- indicizzazione del CBZ esistente: 329 pagine, prima pagina JPEG servita
  separatamente (circa 1,2 MB contro circa 654 MB dell'archivio);
- salvataggio e rilettura del progresso a pagina 2, poi azzeramento del
  solo progresso di prova;
- contenuto, dimensione e data di modifica degli originali invariati,
  verificati anche tramite SHA-256.

La verifica mobile è stata eseguita sull'endpoint web con un user agent
Android; la prova su un telefono fisico rimane a carico dell'utente.

## Ripristino di Jellyfin

L'impostazione `EnableLegacyAuthorization`, abilitata soltanto per provare
JellyBook, è stata riportata a `false`. La libreria Jellyfin **Fumetti** e
il suo mount in sola lettura, richiesti nell'installazione iniziale di
Kapowarr, rimangono disponibili.

## Aggiornamento

Eseguire un backup, aggiornare `KOMGA_IMAGE` alla versione e al digest
verificati, poi:

```bash
cd /opt/raspberry-server
sudo bash scripts/check-media-mount.sh
docker compose -f compose.yaml -f compose.media.yaml config --quiet
docker compose -f compose.yaml -f compose.media.yaml pull komga
docker compose -f compose.yaml -f compose.media.yaml up -d --no-deps komga
```

Fonti: [Docker](https://komga.org/docs/installation/docker/),
[database e configurazione](https://komga.org/docs/installation/configuration/),
[progressi di lettura](https://komga.org/docs/guides/read-progress/),
[Android con Mihon](https://komga.org/docs/guides/mihon/).
