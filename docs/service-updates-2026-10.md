# Aggiornamenti dei servizi del 13 ottobre 2026

Le immagini selezionate in `.env.example` e `rack-pi/.env.example` sono
fissate a tag e digest. Il `.env` di ogni host contiene le versioni effettive:
un aggiornamento della repository da solo non ricrea i container.

| Servizio | Versione selezionata | Host |
| --- | --- | --- |
| Homepage | 2.5.0 | mini-PC e rack-pi |
| qBittorrent / libtorrent | 5.2.4 / 2.0.15, build ls480 | mini-PC |
| Caddy | 2.11.7-alpine | mini-PC |
| Navidrome | 0.64.2 | mini-PC |
| Cloudflare Tunnel | cloudflared 2026.10.0 | mini-PC |
| Pi-hole | 2026.09.0 | mini-PC e rack-pi |
| Runtime monitoring-api | Python 3.14.5-alpine3.22 | mini-PC e rack-pi |
| Immich | 3.3.1 | mini-PC |
| Cache Immich | Valkey 9, digest `418652c…` | mini-PC |
| Uptime Kuma | 2.5.6 | mini-PC e rack-pi |

## Compatibilità e database

Immich era alla 3.1.0 sul mini-PC. La 3.3.1 esegue le proprie migrazioni
del database all'avvio. Il database conserva PostgreSQL 14, pgvector 0.8.1
e VectorChord 0.4.3, compatibili con la nuova applicazione. L'immagine
PostgreSQL resta quella del
[Compose ufficiale della 3.3.1](https://raw.githubusercontent.com/immich-app/immich/v3.3.1/docker/docker-compose.yml).
Valkey conserva la major 9 e aggiorna il digest alla build corrente.

La proposta Renovate di PostgreSQL 16 non è un prerequisito di questo
aggiornamento. Non applicarla a una directory dati PostgreSQL 14: un cambio
di major richiede una procedura separata di dump/restore o `pg_upgrade`.
Anche PostgreSQL e Redis di Nextcloud/n8n restano fuori da questo aggiornamento.

Navidrome, Pi-hole e Uptime Kuma gestiscono le proprie migrazioni interne.
Prima della ricreazione occorre un backup coerente con i relativi servizi
fermi. Dopo una migrazione, ripristinare soltanto la vecchia immagine può
non bastare: per il rollback ripristinare anche il database preaggiornamento.
Immich non supporta il downgrade, neppure all'interno della stessa minor:
vedere la [procedura ufficiale](https://docs.immich.app/install/upgrading/).

Homepage 2 introduce l'autenticazione opzionale. Il codice della 2.5.0 la
abilita solo con `HOMEPAGE_AUTH_ENABLED=true`; l'accesso esistente sulla
Tailnet continua a funzionare con la configurazione attuale. Conservare
`HOMEPAGE_ALLOWED_HOSTS`, i widget e i file CSS/JS locali. Le configurazioni
Homepage, Caddy e i mount dei servizi restano quelli già presenti.

Le dipendenze applicative sono incluse nelle immagini selezionate.
Gli script monitoring-api usano la libreria standard Python; il cambio
riguarda il runtime del container, senza cambiare Python del sistema operativo.
La libreria libtorrent viene aggiornata insieme all'immagine qBittorrent.

## Applicazione su un altro host

1. Verificare un backup Restic riuscito di mini-PC e rack-pi, con dump Immich
   e copia coerente di Navidrome, Pi-hole e Uptime Kuma. Conservare le immagini
   precedenti e una copia protetta dei `.env` per il ripristino.
2. Aggiornare il checkout pulito di `master` con `git pull --ff-only` e riportare
   nei `.env` soltanto le variabili immagine della tabella. Non sostituire il
   `.env` con il file di esempio: contiene password e percorsi dell'host.
3. Validare i Compose e il mount media, poi scaricare le sole immagini selezionate.
4. Ricreare i servizi di un host alla volta, così il Pi-hole dell'altro host
   rimane disponibile. Per Immich fermare il server prima di ricreare Valkey,
   attendere la cache sana e riavviare il server per applicare le migrazioni.
5. Verificare gli healthcheck, le pagine e le API, DNS su entrambi gli host,
   il tunnel Cloudflare e le condivisioni pubbliche. Confrontare i conteggi
   delle principali tabelle Immich prima e dopo la migrazione.

Comandi mirati sul mini-PC, dopo avere selezionato le immagini nel `.env`:

```bash
cd /opt/raspberry-server
bash scripts/check-media-mount.sh
docker compose -f compose.yaml -f compose.media.yaml config --quiet
docker compose -f compose.yaml -f compose.media.yaml pull \
  caddy cloudflared pihole homepage monitoring-api uptime-kuma \
  qbittorrent navidrome immich-redis immich-server

docker compose up -d --no-deps --pull never \
  caddy cloudflared pihole homepage monitoring-api uptime-kuma
docker compose -f compose.yaml -f compose.media.yaml up -d --no-deps --pull never \
  qbittorrent navidrome
docker compose -f compose.yaml -f compose.media.yaml stop immich-server
docker compose -f compose.yaml -f compose.media.yaml up -d --no-deps --pull never immich-redis
# Attendere l'healthcheck di immich-redis prima del comando seguente.
docker compose -f compose.yaml -f compose.media.yaml up -d --no-deps --pull never immich-server
```

Sul Raspberry, dopo aver verificato il Pi-hole del mini-PC:

```bash
cd /opt/raspberry-server/rack-pi
docker compose config --quiet
docker compose pull pihole homepage monitoring-api uptime-kuma
docker compose up -d --no-deps --pull never pihole homepage monitoring-api uptime-kuma
```

Le altre immagini, i servizi e le patch Aurral non fanno parte di questa
selezione. Gli aggiornamenti futuri di Immich devono continuare a verificare
insieme release notes, Compose ufficiale e compatibilità delle estensioni.
