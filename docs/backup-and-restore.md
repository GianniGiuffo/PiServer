# Backup e ripristino

## Cosa viene salvato

Ogni notte `scripts/backup.sh` crea uno snapshot Restic cifrato contenente:

- `.env`;
- configurazioni reali dei siti e `backup.env`;
- directory completa di Vaultwarden;
- Pi-hole e Caddy;
- database e impostazioni Uptime Kuma;
- database/configurazione Jellyfin, esclusi log, cache, metadata generati e
  transcodifiche;
- configurazione, utenti, sessioni e richieste del downloader;
- database e configurazioni di Aurral, Lidarr, slskd e Navidrome;
- configurazione Nextcloud e dump PostgreSQL;
- dump PostgreSQL Immich;
- configurazione e dump PostgreSQL n8n, inclusa la tabella
  `ai_chat_memory` con la cronologia delle chat;

Vaultwarden, Pi-hole, Uptime Kuma, Jellyfin, il downloader e i quattro servizi
musicali vengono fermati brevemente per rendere coerenti i rispettivi database.
Nextcloud entra in maintenance mode. n8n e Immich vengono fermati mentre viene
creato il loro dump PostgreSQL.

## Cosa non viene salvato

- `/srv/media`, quindi file Nextcloud, foto/video Immich, media Jellyfin,
  musica e download;
- database PostgreSQL live;
- Redis/Valkey;
- cache e thumbnail ricostruibili;
- modelli Ollama;
- checkout e release del sito.

Restic protegge la configurazione del server, non il futuro disco dati da 4 TB.
Se quei dati diventeranno importanti servirà un secondo supporto o repository
con capacità adeguata.

## Configurazione Restic

Esempio con disco USB montato in `/mnt/piserver-backup`:

```bash
sudo install -d -m 0700 /etc/restic /etc/raspberry-server
sudo sh -c 'umask 077; openssl rand -base64 48 > /etc/restic/password'
sudo tee /etc/raspberry-server/backup.env >/dev/null <<'EOF'
RESTIC_REPOSITORY=/mnt/piserver-backup/restic-piserver
RESTIC_PASSWORD_FILE=/etc/restic/password
RESTIC_MOUNTPOINT=/mnt/piserver-backup
EOF
sudo chmod 600 /etc/raspberry-server/backup.env /etc/restic/password

sudo bash -c '
  set -a
  source /etc/raspberry-server/backup.env
  set +a
  restic init
'
```

Per SFTP/S3 usare il relativo `RESTIC_REPOSITORY` e omettere
`RESTIC_MOUNTPOINT`. Eventuali credenziali restano in `backup.env`, mode `0600`.

La password Restic deve avere almeno due copie indipendenti fuori dal server e
non deve esistere soltanto dentro Vaultwarden.

## Primo backup e verifica

```bash
cd /opt/raspberry-server
sudo bash scripts/backup.sh

sudo bash -c '
  set -a
  source /etc/raspberry-server/backup.env
  set +a
  restic snapshots --latest 5
  restic check --read-data-subset=5%
  restic ls latest --tag pi-server |
    grep -E "vaultwarden|pihole|uptime-kuma|streamingcommunity|aurral|lidarr|slskd|navidrome|nextcloud.sql|immich.sql|n8n.sql"
'

sudo systemctl enable --now backup.timer
systemctl list-timers backup.timer
sudo bash scripts/refresh-backup-status.sh auto
```

L'ultimo comando inizializza la banda **Backup Restic** di Homepage usando lo
snapshot più recente disponibile e il prossimo avvio effettivo del timer.
Dopo ogni esecuzione `backup.sh` aggiorna automaticamente stato, ultimo
successo e prossimo avvio; un errore conserva la data dell'ultimo backup
riuscito e imposta lo stato su **Fallito**. `backup-status.timer`, installato
insieme alle altre unità, riallinea il prossimo orario ogni cinque minuti.

La retention è di 7 snapshot giornalieri, 4 settimanali e 12 mensili. I vecchi
snapshot con tag storico `raspberry-server` non vengono eliminati
automaticamente dal nuovo tag `pi-server`.

## Restore test non distruttivo

```bash
restore_dir=$(mktemp -d)
sudo bash -c "
  set -a
  source /etc/raspberry-server/backup.env
  set +a
  restic restore latest --tag pi-server \
    --include '/srv/raspberry-server/data/vaultwarden/**' \
    --target '${restore_dir}'
"
sudo find "${restore_dir}" -type f | head
echo "Test conservato in ${restore_dir}; ispezionarlo prima di eliminarlo."
```

Non importare il JSON Vaultwarden sopra un vault già ripristinato: l'import non
deduplica e creerebbe copie.

## Disaster recovery completo

1. Installare Debian 13, clonare la repo ed eseguire `bootstrap.sh`.
2. Ricreare `/etc/restic/password` e `backup.env`.
3. Preparare un nuovo `.env` partendo dalla versione corrente di
   `.env.example`.
4. Non avviare ancora gli stack.
5. Ripristinare in staging:

```bash
sudo install -d -m 0700 /srv/restore
sudo bash -c '
  set -a
  source /etc/raspberry-server/backup.env
  set +a
  restic restore latest --tag pi-server --target /srv/restore
'
```

Restic mantiene i percorsi assoluti sotto il target. La vecchia `.env` si trova
quindi normalmente in:

```text
/srv/restore/opt/raspberry-server/.env
```

Confrontarla con il nuovo `.env.example` e copiare domini e segreti. Non
sostituire i nuovi valori dipendenti dall'host.

## Ripristino dei servizi core

Con Docker fermo:

```bash
sudo systemctl stop docker
sudo rsync -aHAX \
  /srv/restore/srv/raspberry-server/data/vaultwarden/ \
  /srv/raspberry-server/data/vaultwarden/
sudo rsync -aHAX \
  /srv/restore/srv/raspberry-server/data/pihole/ \
  /srv/raspberry-server/data/pihole/
sudo rsync -aHAX \
  /srv/restore/srv/raspberry-server/data/caddy/ \
  /srv/raspberry-server/data/caddy/
sudo rsync -aHAX \
  /srv/restore/srv/raspberry-server/data/uptime-kuma/ \
  /srv/raspberry-server/data/uptime-kuma/
sudo systemctl start docker
sudo systemctl start core-stack.service
```

Per Vaultwarden il restore della directory completa è la via primaria. Il JSON
sul PC è una seconda via se il database non fosse recuperabile.

La configurazione del downloader può essere ripristinata, sempre con il
container fermo, tramite:

```bash
sudo rsync -aHAX \
  /srv/restore/srv/raspberry-server/data/streamingcommunity/ \
  /srv/raspberry-server/data/streamingcommunity/
```

Questo recupera utenti, sessioni, richieste, pianificazioni e API key Jellyfin;
i file scaricati sotto `/srv/media/downloads` devono invece provenire dal
backup separato del disco media.

Lo stato dello stack musicale si ripristina con i container fermi:

```bash
sudo systemctl stop media-stack.service
for service in aurral lidarr slskd navidrome; do
  sudo rsync -aHAX \
    "/srv/restore/srv/raspberry-server/data/${service}/" \
    "/srv/raspberry-server/data/${service}/"
done
```

Questo recupera utenti, configurazioni, preferiti, playlist e cronologia. La
cache Navidrome e ogni file sotto `/srv/media/music` restano esclusi e devono
provenire dall'eventuale backup separato del disco media.

## Ripristino PostgreSQL

Usare dump e configurazioni appartenenti allo stesso snapshot. Eseguire questi
comandi soltanto su database locali nuovi e vuoti.

Nextcloud:

```bash
docker compose -f compose.yaml -f compose.media.yaml \
  up -d nextcloud-postgres
docker compose -f compose.yaml -f compose.media.yaml \
  exec -T nextcloud-postgres psql -U nextcloud -d nextcloud \
  < /srv/restore/srv/raspberry-server/staging/nextcloud.sql
```

Immich:

```bash
docker compose -f compose.yaml -f compose.media.yaml \
  up -d immich-postgres
docker compose -f compose.yaml -f compose.media.yaml \
  exec -T immich-postgres psql -U immich -d immich \
  < /srv/restore/srv/raspberry-server/staging/immich.sql
```

n8n:

```bash
sudo rsync -aHAX \
  /srv/restore/srv/raspberry-server/data/n8n/n8n/ \
  /srv/raspberry-server/data/n8n/n8n/
docker compose -f compose.yaml -f compose.automation.yaml \
  up -d n8n-postgres
docker compose -f compose.yaml -f compose.automation.yaml \
  exec -T n8n-postgres psql -U n8n -d n8n \
  < /srv/restore/srv/raspberry-server/staging/n8n.sql
```

Il valore `N8N_ENCRYPTION_KEY` deve essere quello dello stesso snapshot.

## Ripristino media

Il restore delle configurazioni non ricrea i file esclusi. Prima di avviare lo
stack media:

```bash
mountpoint /srv/media
test -f /srv/media/.piserver-media
sudo bash scripts/check-media-mount.sh
```

Se il disco da 4 TB è nuovo o vuoto, Nextcloud e Immich partiranno senza i
vecchi file. Un database ripristinato che fa riferimento a file non più
presenti non costituisce un recupero completo.

## Verifica finale

```bash
bash scripts/preflight.sh
sudo bash scripts/configure-tailscale-serve.sh
sudo systemctl restart core-stack.service
sudo systemctl restart media-stack.service
sudo systemctl restart automation-stack.service
sudo systemctl start backup.service
```

Verificare login e sincronizzazione Vaultwarden, query DNS, dashboard,
monitoraggi, file Nextcloud, una transcodifica Jellyfin, un upload Immich e un
workflow n8n. Verificare inoltre login Aurral/Navidrome, stato Soulseek e una
scansione musicale prima di cancellare `/srv/restore` o il vecchio disco.
