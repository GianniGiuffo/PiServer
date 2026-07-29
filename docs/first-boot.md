# Prima installazione su Debian 13

Eseguire i passaggi sul Dell OptiPlex, non sul PC Windows che contiene la copia
della repo. Non collegare ancora il tunnel Cloudflare al mini PC finché
Vaultwarden non è stato ripristinato e verificato.

## 1. BIOS, Debian e rete

Nel BIOS abilitare `Restore on AC Power Loss: Power On` e la GPU integrata anche
in modalità headless. Installare Debian 13 amd64 senza desktop, creare un utente
amministratore non root e usare una chiave SSH.

Assegnare al mini PC una prenotazione DHCP stabile nel router. Non configurare
ancora Pi-hole come DNS del router.

```bash
sudo apt update
sudo apt full-upgrade -y
sudo reboot
```

## 2. Repository e bootstrap

```bash
sudo git clone https://github.com/GianniGiuffo/PiServer.git /opt/raspberry-server
sudo chown -R "$USER:$USER" /opt/raspberry-server
cd /opt/raspberry-server
sudo bash scripts/bootstrap.sh
```

Il bootstrap installa Docker Engine/Compose, Tailscale, Restic, client NFS/SMB e
le unità systemd. Uscire e rientrare nella sessione per ricevere il gruppo
`docker`.

## 3. Tailscale

```bash
sudo tailscale up --ssh --hostname=mini-pc
sudo tailscale set --accept-dns=false
tailscale ip -4
tailscale status --json | jq -r '.Self.DNSName'
```

`accept-dns=false` vale soltanto per il server DNS e previene un loop nel quale
il mini PC tenta di usare il proprio Pi-hole. Conservare l'IPv4 `100.x.y.z` e
il nome MagicDNS senza il punto finale.

## 4. `.env`

```bash
cd /opt/raspberry-server
cp .env.example .env
chmod 600 .env
nano .env
```

Impostare:

- `TAILSCALE_FQDN` con il nome appena ottenuto;
- `N8N_WEBHOOK_DOMAIN` con lo stesso identico nome MagicDNS; il percorso
  `N8N_CHAT_PATH` verrà sostituito dopo aver attivato il Chat Trigger;
- `PUID`, `PGID` e `RENDER_GID`:

  ```bash
  id -u
  id -g
  getent group render | cut -d: -f3
  ```

- token Cloudflare già esistente;
- password uniche generate con `openssl rand -base64 48`;
- `IMMICH_DB_PASSWORD` usando soltanto lettere e numeri;
- la chiave n8n una sola volta con `openssl rand -hex 32`.

Per Vaultwarden creare una password amministrativa distinta dalla master
password e salvarne l'hash:

```bash
docker run --rm -it vaultwarden/server:1.36.0 /vaultwarden hash
```

Inserire l'intera riga `$argon2id$...` tra apici singoli in
`VAULTWARDEN_ADMIN_TOKEN`. Conservare password, `.env`, password Restic, codici
di recupero 2FA e accessi Cloudflare/Tailscale anche fuori da Vaultwarden.

## 5. Controlli

```bash
cd /opt/raspberry-server
bash scripts/preflight.sh
ls -l /dev/dri/renderD128
sudo ss -lntup
```

Se la porta 53 è occupata, identificare il resolver in conflitto prima di
avviare Pi-hole. Non disabilitare alla cieca il resolver del sistema.

## 6. Ripristinare Vaultwarden e Pi-hole

Seguire [backup-and-restore.md](backup-and-restore.md) per ripristinare l'ultimo
snapshot in una directory temporanea. Servono sia la password conservata sul
PC sia `RESTIC_REPOSITORY` e le eventuali credenziali del vecchio
`/etc/raspberry-server/backup.env`; la procedura esatta per trasferirli è in
[minipc-migration.md](minipc-migration.md). Copiare sul mini PC almeno:

```text
/srv/raspberry-server/data/vaultwarden
/srv/raspberry-server/data/pihole
/srv/raspberry-server/data/caddy
```

Confrontare il vecchio `.env` in staging con quello nuovo creato al passo 4 e
trasferire soltanto domini, token e password. Non sovrascrivere il nuovo file:
il formato precedente non contiene `MEDIA_DIR`, `PUID`, `PGID`, `RENDER_GID` e
le immagini dei nuovi servizi. Nextcloud non contiene dati e viene reinstallato.

Non usare ancora l'esportazione JSON Vaultwarden: serve soltanto come seconda
via di recupero se il ripristino completo fallisce.

## 7. Avviare i servizi core senza traffico pubblico

Fermare temporaneamente Cloudflared nel Compose:

```bash
cd /opt/raspberry-server
docker compose up -d caddy pihole vaultwarden docker-socket-proxy monitoring-api homepage uptime-kuma
docker compose ps
sudo bash scripts/configure-tailscale-serve.sh
tailscale serve status
```

Verificare:

- Homepage: `https://TAILSCALE_FQDN/`;
- Pi-hole: `https://TAILSCALE_FQDN:8444/admin/`;
- Uptime Kuma: `https://TAILSCALE_FQDN:8448/`;
- Vaultwarden localmente:

  ```bash
  curl -fsS http://127.0.0.1:8080/alive
  docker compose exec vaultwarden test -f /data/db.sqlite3
  docker compose logs --tail=100 vaultwarden
  ```

## 8. Cutover Cloudflare

Sul Raspberry:

```bash
cd /opt/raspberry-server
docker compose stop cloudflared vaultwarden
```

Eseguire un ultimo backup prima dello stop se sono state fatte modifiche dopo
il restore. Se il backup è più recente di quello ripristinato sul mini PC,
ripristinare di nuovo Vaultwarden prima di proseguire.

Sul mini PC:

```bash
cd /opt/raspberry-server
docker compose up -d cloudflared
sudo systemctl enable --now core-stack.service
docker compose logs --tail=100 cloudflared
```

Provare `https://tommasofrancescon.it` e
`https://vault.tommasofrancescon.it` da rete mobile. Accedere a Vaultwarden,
confrontare alcuni elementi con l'esportazione JSON, sincronizzare un client,
creare e cancellare un elemento di prova e controllare il secondo fattore.

Se la verifica fallisce, fermare immediatamente Cloudflared sul mini PC e
riavviare Vaultwarden e Cloudflared sul Raspberry. Non importare il JSON sopra
un database parzialmente ripristinato.

## 9. Pi-hole come DNS LAN e Tailnet

Soltanto dopo che Pi-hole risolve correttamente:

1. nel router, impostare l'IP LAN del mini PC come DNS distribuito dal DHCP;
2. nella console Tailscale, aprire **DNS > Nameservers**;
3. aggiungere l'IPv4 Tailscale `100.x.y.z` del mini PC come nameserver globale;
4. mantenere MagicDNS attivo;
5. abilitare **Override local DNS** per filtrare tramite Pi-hole anche i client
   remoti connessi a Tailscale.

Non inoltrare mai la porta 53 sul router. Il mini PC mantiene
`tailscale set --accept-dns=false`; gli altri dispositivi ricevono Pi-hole
dalla configurazione Tailnet.

## 10. Sito automatico

```bash
cd /opt/raspberry-server
docker build --tag raspberry-server/hugo-builder:0.163.3 \
  --file docker/hugo-builder.Dockerfile docker
sudo install -m 0640 -o root -g "$USER" \
  config/sites/site-1.env.example \
  /etc/raspberry-server/sites/site-1.env
sudo systemctl enable --now site-deploy.timer
sudo systemctl start site-deploy.service
sudo journalctl -u site-deploy.service -n 100 --no-pager
```

Il timer controlla la repo ogni minuto ma costruisce solo un commit nuovo.

## 11. Restic

Configurare, eseguire e verificare Restic seguendo
[backup-and-restore.md](backup-and-restore.md), poi:

```bash
sudo systemctl enable --now backup.timer
sudo systemctl start backup.service
```

## 12. Disco da 4 TB e servizi media

Quando il disco è disponibile, seguire [storage.md](storage.md) e preparare lo
stack musicale con [music-stack.md](music-stack.md). Soltanto dopo:

```bash
sudo bash scripts/check-media-mount.sh
sudo systemctl enable --now media-stack.service
sudo systemctl status media-stack.service --no-pager
```

In Immich aprire **Administration > Settings > Machine Learning**, disabilitare
tutte le funzioni ML e lasciare assente il relativo container. In
**Video transcoding** selezionare Quick Sync, concorrenza 1 e pochi thread.

In Jellyfin selezionare Intel Quick Sync o VA-API con
`/dev/dri/renderD128`, quindi eseguire una transcodifica di prova.

Per la configurazione dettagliata di Homepage, Uptime Kuma, Nextcloud,
Jellyfin, Immich, StreamingCommunity downloader e Vaultwarden seguire
[service-setup.md](service-setup.md).

## 13. n8n e Ollama

```bash
sudo systemctl enable --now automation-stack.service
```

Proseguire con [n8n-ollama.md](n8n-ollama.md). L'editor è disponibile solo su
`https://TAILSCALE_FQDN:8449/`.
