# Omnibus: scoperta e gestione di fumetti e manga

Omnibus affianca Kapowarr e Komga con scoperta, richieste e gestione completa
della raccolta. Su questo server è autorizzato a scrivere nella stessa
`/srv/media/Comics`. Komga continua a leggerla in sola lettura. Omnibus
gestisce direttamente le richieste: non le inoltra a Kapowarr.

## Servizi e accesso

- UI: `https://TAILSCALE_FQDN:8468/`, solo tramite Tailscale Serve verso
  `127.0.0.1:3003`. Nessuna esposizione LAN, Cloudflare Tunnel o Funnel.
- `omnibus`: interfaccia Next.js e API, versione `v1.4.9` fissata per digest.
- `omnibus-engine`: motore Rust della stessa versione, senza porte host,
  su una rete dedicata raggiungibile dall'app.
- `omnibus-redis`: coda BullMQ persistente, senza porte host, su una rete
  Docker interna. Redis usa AOF e `noeviction` per conservare i lavori.
- Avvio, arresto e aggiornamenti fanno parte dello stack media e dipendono
  dalla verifica del disco e del marker `.piserver-media`.

## Dati e permessi

Entrambi i processi Omnibus usano `PUID:PGID`, `UMASK=002` e gli stessi mount:

| Percorso host | Percorso container | Uso |
| --- | --- | --- |
| `/srv/raspberry-server/data/omnibus/config` | `/config` | SQLite, credenziali cifrate, metadati, cache e log |
| `/srv/media/Comics` | `/data/comics` | raccolta condivisa, in lettura e scrittura |
| `/srv/media/downloads/.omnibus` | `/data` | download, watched e unmatched; il mount annidato `/data/comics` vede la raccolta |

Il database SQLite condiviso tra web ed engine rimane sull'SSD locale.
La coda Redis è in `/srv/raspberry-server/data/omnibus/redis`.
I percorsi media devono esistere sul disco montato prima dell'avvio;
`check-media-mount.sh` verifica anche l'area Omnibus.

## Configurazione iniziale

- Libreria **Fumetti e manga**, percorso `/data/comics`.
- ComicVine configurato riutilizzando la chiave già presente in Kapowarr;
  nessuna chiave API è salvata in Git.
- Scoperta di fumetti e manga abilitata; richieste manga abilitate.
- Prowlarr e qBittorrent collegati ai servizi esistenti. qBittorrent usa
  una categoria dedicata `omnibus`, con percorso remoto
  `/data/.omnibus/downloads`, mappato da Omnibus a `/data/downloads`.
  L'indexer esistente è abilitato per la categoria provider `100045`
  (**Fumetti**); rivedere questa scelta quando si aggiungono altri indexer.
- Download diretti GetComics disponibili; le fonti e i file effettivamente
  reperibili dipendono dai provider. Non vengono avviati download di prova.
- Conversioni CBR/WebP e scrittura automatica dei metadati nei file
  disabilitate inizialmente. I controlli rimangono disponibili all'admin.
- Per evitare acquisizioni doppie, affidare il monitoraggio di ciascuna
  serie a un solo gestore tra Omnibus e Kapowarr.

Il layout Kapowarr contiene cartelle annidate, ad esempio
`Ultimate Spider-Man/Volume 01 (2000)`. Omnibus ha rilevato il CBZ esistente,
ma non ne è stata forzata l'associazione: il file è una raccolta Epic
Collection del 2025 e non contiene `ComicInfo.xml`, mentre Kapowarr lo
gestisce sotto il volume originale del 2000. Associare l'edizione corretta
da **Admin > Smart Matcher**. Finché non viene fatto, il file è leggibile,
ma i suggerimenti basati su autori/personaggi della raccolta possono essere
incompleti. Il catalogo esterno Novità/Popolari è già disponibile.

L'account amministrativo iniziale è `admin`, email `admin@piserver.local`.
La password casuale è conservata fuori da Git in
`/etc/raspberry-server/omnibus-admin.json` con permessi `0600`.
Cambiarla dalle impostazioni dell'account dopo il primo accesso; il file
iniziale non viene aggiornato dopo il cambio. La registrazione libera è
disabilitata: gli altri account si creano dall'amministrazione.

## Android

Con Tailscale attivo, aprire lo stesso URL in Chrome o Firefox. L'interfaccia
è utilizzabile da telefono e comprende scoperta, richieste e lettore.
Komga e gli eventuali client Android collegati continuano a leggere i file
dalla cartella condivisa; i progressi di lettura dei due server sono separati.

## Verifiche del deploy

Il 29 ottobre 2026 sono stati verificati:

- login amministrativo e cataloghi Novità/Popolari tramite HTTPS Tailscale;
- test di connessione dell'app a ComicVine, Prowlarr e qBittorrent;
- web ed engine sulla stessa release `1.4.9`, senza riavvii inattesi;
- lettura delle 329 pagine del CBZ esistente; una pagina WebP servita
  separatamente da circa 270 KB, senza trasferire l'intero archivio;
- interfaccia web mobile raggiungibile con user agent Android;
- porta `3003` chiusa sull'IP LAN, engine e Redis senza porte pubblicate,
  e nessuna configurazione Funnel;
- originale CBZ invariato per SHA-256, dimensione e data di modifica.
  Omnibus ha aggiunto una `cover.jpg` nella cartella della serie;
- mount Komga rimasto in sola lettura, senza modifiche a Jellyfin.

Non sono stati richiesti o scaricati nuovi fumetti come prova. La prova
su un telefono Android fisico rimane da eseguire sul dispositivo.

## Backup e aggiornamenti

Restic arresta prima il web, poi l'engine e Redis per salvare SQLite e AOF
in uno stato coerente. Il ripristino dell'app richiede anche
`OMNIBUS_AUTH_SECRET` in `.env`: web ed engine condividono questo segreto,
usato per autenticazione e protezione delle credenziali/backup.
Cache, log e backup interni duplicati di Omnibus sono esclusi da Restic;
i fumetti e i download seguono la politica separata dei dati media.

Per aggiornare, leggere le note della release, fare un backup e aggiornare
insieme `OMNIBUS_IMAGE` e `OMNIBUS_ENGINE_IMAGE`, mantenendo versioni
corrispondenti e digest verificati. L'entrypoint web applica lo schema al
primo avvio: conservare sempre un backup precedente all'aggiornamento.

```bash
cd /opt/raspberry-server
sudo bash scripts/check-media-mount.sh
docker compose -f compose.yaml -f compose.media.yaml config --quiet
docker compose -f compose.yaml -f compose.media.yaml pull omnibus omnibus-engine omnibus-redis
docker compose -f compose.yaml -f compose.media.yaml up -d omnibus-redis omnibus-engine omnibus
```

Fonti: [progetto e funzioni](https://github.com/hankscafe/omnibus),
[release v1.4.9](https://github.com/hankscafe/omnibus/releases/tag/v1.4.9),
[Compose ufficiale](https://github.com/hankscafe/omnibus/blob/v1.4.9/docker-compose.yml).
