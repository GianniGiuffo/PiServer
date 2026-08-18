# PiServer sul Dell OptiPlex 7050 Tiny

Configurazione riproducibile per un home server Debian 13 con Docker Compose.
La repo contiene configurazione, script di bootstrap, unità systemd, backup
Restic e procedura di disaster recovery. Password, database e dati utente non
vengono salvati in Git.

Hardware di riferimento:

- Dell OptiPlex 7050 Tiny;
- Intel i5-7500 con Intel HD 630 e `/dev/dri/renderD128`;
- 16 GB di RAM;
- SSD interno da 240 GB per sistema, configurazioni e database;
- disco da circa 4 TB condiviso in LAN e montato in `/srv/media`.

## Servizi

| Servizio | Accesso | Dati |
| --- | --- | --- |
| Sito statico | pubblico, Cloudflare Tunnel | build riproducibile dalla repo del sito |
| Vaultwarden | pubblico, Cloudflare Tunnel | SSD locale + Restic |
| Pi-hole DNS | LAN e Tailnet | SSD locale + Restic |
| Homepage | Tailnet, porta 443 | configurazione in Git |
| Uptime Kuma | Tailnet, porta 8448 | SSD locale + Restic |
| Nextcloud | Tailnet, porta 8445 | DB/config su SSD, file su `/srv/media` |
| Jellyfin | Tailnet, porta 8446 | config su SSD, media su `/srv/media` |
| Immich senza ML | Tailnet, porta 8447 | DB su SSD, foto/video su `/srv/media` |
| StreamingCommunity downloader | Tailnet, porta 8450 | config su SSD, download su `/srv/media` |
| Aurral | Tailnet, porta 8451 | config su SSD, musica su `/srv/media/music` |
| Navidrome | Tailnet, porta 8452 | DB su SSD, musica in sola lettura |
| Lidarr | Tailnet, porta 8453 | config su SSD, libreria su `/srv/media/music` |
| slskd | Tailnet, porta 8454 | config su SSD, transito su `/srv/media/music` |
| n8n | Tailnet, porta 8449 | SSD locale + Restic |
| Ollama | solo rete Docker | modelli riproducibili, non salvati |
| SearXNG | solo rete Docker per n8n | cache eliminabile, non salvata |
| Nextcloud read-only connector | solo rete Docker per n8n | nessun dato proprio |
| Area privata del sito | Tailnet, porta 8443 | build del sito |

Tailscale è installato sull'host, non in Docker. Cloudflare espone soltanto il
sito e Vaultwarden; editor, webhook e chat n8n restano nella Tailnet. Nessuna
porta del router deve essere inoltrata.

## Tre stack indipendenti

- `compose.yaml`: servizi core, sempre disponibili e senza dati utente sul NAS;
- `compose.media.yaml`: Nextcloud, Jellyfin, Immich, downloader e stack
  musicale; parte solo dopo la verifica del mount `/srv/media`;
- `compose.automation.yaml`: n8n, PostgreSQL, Ollama e SearXNG.

Le unità `core-stack.service`, `media-stack.service` e
`automation-stack.service` li avviano automaticamente e in ordine. I servizi
media usano `restart: on-failure` anziché avviarsi direttamente con Docker:
questo impedisce loro di precedere il mount di rete durante il boot.

## Installazione sintetica

La procedura completa è in [docs/first-boot.md](docs/first-boot.md).

```bash
sudo git clone https://github.com/GianniGiuffo/PiServer.git /opt/raspberry-server
sudo chown -R "$USER:$USER" /opt/raspberry-server
cd /opt/raspberry-server
sudo bash scripts/bootstrap.sh

sudo tailscale up --ssh --hostname=mini-pc
sudo tailscale set --accept-dns=false

cp .env.example .env
chmod 600 .env
nano .env
bash scripts/preflight.sh

docker compose up -d caddy pihole vaultwarden docker-socket-proxy monitoring-api homepage uptime-kuma
sudo bash scripts/configure-tailscale-serve.sh
```

Durante la migrazione non avviare ancora `cloudflared`: prima ripristinare e
verificare Vaultwarden, poi seguire il cutover in
[docs/first-boot.md](docs/first-boot.md).

Non abilitare `media-stack.service` finché il disco di rete non è montato,
contiene il marker `.piserver-media` e supera
`scripts/check-media-mount.sh`. Vedi [docs/storage.md](docs/storage.md).

## Aggiornamenti

Il sito viene controllato ogni minuto e ricostruito soltanto quando cambia il
commit remoto. Le immagini dei servizi non vengono aggiornate automaticamente.

```bash
sudo systemctl start backup.service
bash scripts/update-images.sh core
sudo systemctl restart core-stack.service
```

Ripetere con `media` o `automation` dopo avere letto le note di rilascio.
`update-images.sh` scarica esclusivamente le versioni selezionate in `.env`.

## Backup

Restic salva `.env`, configurazioni, database SQLite coerenti e dump PostgreSQL.
Non salva foto, video, file Nextcloud, media Jellyfin, musica, download, cache,
thumbnail o modelli Ollama. Il disco media richiede quindi una politica di
backup separata se in futuro quei file dovranno essere recuperabili dopo la
sua rottura.

La procedura completa e i comandi di restore sono in
[docs/backup-and-restore.md](docs/backup-and-restore.md).

## Documentazione

- [Prima installazione](docs/first-boot.md)
- [Storage di rete e struttura delle directory](docs/storage.md)
- [Migrazione dal Raspberry Pi](docs/minipc-migration.md)
- [Backup e ripristino](docs/backup-and-restore.md)
- [Accesso remoto e sicurezza](docs/security.md)
- [Configurazione iniziale dei servizi](docs/service-setup.md)
- [Stack musicale](docs/music-stack.md)
- [Cloudflare Tunnel](docs/cloudflare-tunnel.md)
- [n8n e Ollama](docs/n8n-ollama.md)
- [Connettori AI: SearXNG e Nextcloud in sola lettura](docs/ai-connectors.md)
- [Connettori AI: GitHub in sola lettura e DeepL](docs/n8n-github-deepl.md)
