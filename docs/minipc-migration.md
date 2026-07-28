# Migrazione controllata dal Raspberry Pi

Il Raspberry può essere spento durante la migrazione, ma non deve essere
cancellato finché Vaultwarden non è stato verificato e il mini PC non ha
prodotto un nuovo snapshot Restic valido.

## Dati da migrare

- directory completa di Vaultwarden;
- configurazione Pi-hole;
- `.env` come fonte dei vecchi segreti, da unire al nuovo `.env.example`;
- stato Caddy, facoltativo con Cloudflare Tunnel;
- configurazione del sito in `/etc/raspberry-server/sites`.

Nextcloud non contiene file e viene reinstallato. I modelli Ollama, cache e
build del sito non devono essere copiati.

## 1. Congelare le modifiche

Sul Raspberry:

> Non eseguire `git pull` della nuova configurazione sul Raspberry: i nomi dei
> servizi Nextcloud sono cambiati. Usare lo script di backup già installato e
> testato sul Raspberry; la nuova revisione è destinata al mini PC.

```bash
cd /opt/raspberry-server
sudo systemctl stop site-deploy.timer
docker compose stop cloudflared
sudo systemctl start backup.service
sudo journalctl -u backup.service -n 100 --no-pager
```

Da questo momento non modificare Vaultwarden sul Raspberry.

## 2. Ripristinare in staging

Prima di spegnere definitivamente il Raspberry, conservare anche il contenuto
di `/etc/raspberry-server/backup.env`: la password Restic da sola non identifica
il repository e non contiene le eventuali credenziali SFTP/S3.

Sul mini PC:

1. ricreare `/etc/restic/password` usando **esattamente** la password già
   conservata sul PC, senza generarne una nuova;
2. copiare o ricreare `/etc/raspberry-server/backup.env` dal Raspberry;
3. correggere soltanto `RESTIC_MOUNTPOINT` se il supporto è montato in un
   percorso diverso;
4. impostare entrambi i file con proprietario `root` e mode `0600`.

```bash
sudo install -d -m 0700 /etc/restic /etc/raspberry-server
sudo chmod 600 /etc/restic/password /etc/raspberry-server/backup.env
sudo chown root:root /etc/restic/password /etc/raspberry-server/backup.env
```

Ripristinare quindi l'ultimo snapshot storico in una directory vuota, mai
direttamente sopra i percorsi live:

```bash
sudo install -d -m 0700 /srv/restore
sudo bash -c '
  set -a
  source /etc/raspberry-server/backup.env
  set +a
  restic snapshots --tag raspberry-server --latest 5
  restic restore latest --tag raspberry-server --target /srv/restore
'
sudo find /srv/restore -maxdepth 6 -type f | head -50
```

Seguire [backup-and-restore.md](backup-and-restore.md) per copiare Vaultwarden,
Pi-hole e Caddy con i container fermi.

Non sostituire il nuovo `.env` con quello vecchio: confrontarli e trasferire
soltanto domini e segreti. Conservare i nuovi valori `TAILSCALE_FQDN`, `PUID`,
`PGID`, `RENDER_GID`, `MEDIA_DIR` e le nuove immagini.

## 3. Verifica privata

Avviare i servizi core tranne Cloudflared:

```bash
cd /opt/raspberry-server
docker compose up -d caddy pihole vaultwarden docker-socket-proxy monitoring-api homepage uptime-kuma
sudo bash scripts/configure-tailscale-serve.sh
docker compose ps
docker compose logs --tail=100 vaultwarden
docker compose exec vaultwarden test -f /data/db.sqlite3
curl -fsS http://127.0.0.1:8080/alive
```

## 4. Cutover senza perdita di delta

Se tra il backup ripristinato e questo momento non è stato modificato il vault,
avviare Cloudflared sul mini PC:

```bash
docker compose up -d cloudflared
```

Se invece il Raspberry ha ricevuto modifiche, ripetere rigorosamente:

1. fermare Cloudflared sul Raspberry;
2. eseguire l'ultimo backup;
3. fermare Vaultwarden sul mini PC;
4. ripristinare nuovamente la directory Vaultwarden dall'ultimo snapshot;
5. avviare Vaultwarden e poi Cloudflared sul mini PC.

Cloudflare Tunnel può distribuire richieste fra più connettori con lo stesso
token: non tenere contemporaneamente attivi il Raspberry e il mini PC durante
il passaggio.

## 5. Collaudo

Da rete mobile:

- aprire il sito;
- accedere a Vaultwarden;
- confrontare più elementi con l'esportazione JSON;
- sincronizzare telefono e browser;
- creare e cancellare una voce di prova;
- verificare il secondo fattore.

Poi:

```bash
sudo systemctl enable --now core-stack.service
sudo systemctl enable --now backup.timer
sudo systemctl start backup.service
systemctl list-timers
docker compose ps
tailscale status
```

Aggiornare il nameserver globale Tailscale e il DNS DHCP del router dal vecchio
IP del Raspberry al nuovo mini PC. Spegnere il Raspberry, ma conservarne il
disco intatto finché un restore test del nuovo backup non è riuscito.
