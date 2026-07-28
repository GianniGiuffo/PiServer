# Configurazione iniziale dei servizi

## Homepage

Homepage è già configurato dai file in `config/homepage`. Si apre su:

```text
https://TAILSCALE_FQDN/
```

Le statistiche Docker passano attraverso `docker-socket-proxy`, che consente
soltanto letture. Per aggiungere collegamenti modificare `services.yaml` e
committare la modifica: il dashboard rimane così riproducibile da Git.

La prima riga di Homepage, prima di ogni altro servizio e senza barra di
ricerca o intestazione richiudibile, contiene quattro card sempre visibili e
della stessa larghezza:

- **Server**: CPU, memoria, temperatura e uptime dell'host;
- **NAS**: stato del mount, spazio libero, capacità e percentuale usata;
- **Rete**: traffico istantaneo in entrata e uscita sull'interfaccia fisica;
- **Backup**: esito Restic, ultimo snapshot riuscito e prossimo avvio del timer.

`monitoring-api` legge soltanto i file necessari sotto `/proc` e `/sys`, il
mount media e il JSON di stato del backup. Non riceve socket Docker o systemd,
non pubblica porte e risponde soltanto sulla rete Docker interna `monitoring`.
Se `/srv/media` non è un mount reale, la banda NAS mostra **Non montato**.

L'interfaccia di rete è rilevata automaticamente ignorando loopback, Docker e
Tailscale. Per fissarla esplicitamente, trovare quella della route predefinita:

```bash
ip route show default
```

e impostare, per esempio, `SERVER_NETWORK_INTERFACE=enp1s0` in `.env`. Non
eseguire `source .env`: i segreti contenuti nel file possono includere caratteri
interpretati dalla shell.

La temperatura dipende dai sensori esposti dal kernel: se non appare,
installare/verificare `lm-sensors` prima di cambiare Homepage:

```bash
sudo apt install lm-sensors
sensors
```

Lo script Restic aggiorna
`/srv/raspberry-server/data/monitoring/backup.json` dopo ogni esito, riuscito o
fallito. Il file contiene soltanto stato e orari, non credenziali. Per
inizializzarlo da uno snapshot Restic già esistente e leggere il prossimo
orario calcolato da systemd:

```bash
sudo bash scripts/refresh-backup-status.sh auto
```

La banda mostra orari relativi aggiornati da Homepage. `backup-status.timer`
ricalcola ogni cinque minuti il prossimo avvio effettivo; il backup resta
programmato alle 03:15 con un ritardo casuale massimo di 30 minuti.

Homepage mostra due controlli distinti per i servizi configurati:

- il controllo Docker indica se il processo è avviato e, quando presente, usa
  anche l'`healthcheck` definito nel Compose;
- `siteMonitor` esegue una richiesta HTTP interna e verifica che
  l'applicazione risponda davvero.

Per questo Aurral può risultare `running` ma `unhealthy`: il processo Node è
ancora vivo, mentre `/api/health/live` non risponde. L'healthcheck di Aurral
parte dopo 30 secondi, viene eseguito ogni 30 secondi e richiede tre errori
consecutivi prima di dichiarare il container non sano. Lidarr controlla
`/ping`; slskd include già nell'immagine upstream un controllo su `/health`,
ma il Compose riduce a 45 secondi il periodo iniziale upstream di un'ora.

Un container `unhealthy` non viene riavviato automaticamente dalle policy
`restart`: queste reagiscono all'uscita del processo, non allo stato di salute.
Questa scelta evita cicli di riavvio e conserva i log per la diagnosi. Uptime
Kuma resta responsabile di storico e notifiche.

Verificare gli stati con:

```bash
docker compose -f compose.yaml -f compose.media.yaml ps
docker inspect --format '{{json .State.Health}}' \
  raspberry-server-aurral-1 | jq
```

## Uptime Kuma

Aprire `https://TAILSCALE_FQDN:8448/` e creare il primo amministratore. Aggiungere
almeno questi monitor HTTP:

| Nome | URL visto dal container |
| --- | --- |
| Sito | `https://tommasofrancescon.it/` |
| Vaultwarden | `http://vaultwarden/` |
| Pi-hole | `http://pihole/admin/` |
| Nextcloud | `http://nextcloud/status.php` |
| Jellyfin | `http://jellyfin:8096/health` |
| Immich | `http://immich-server:2283/api/server/ping` |
| StreamingCommunity | `http://streamingcommunity:8000/login` |
| Aurral | `http://aurral:3001/api/health/live` |
| Navidrome | `http://navidrome:4533/` |
| Lidarr | `http://lidarr:8686/ping` |
| slskd | `http://slskd:5030/health` |
| n8n | `http://n8n:5678/` |

Configurare una notifica esterna, ad esempio email o Telegram, altrimenti un
monitor sullo stesso server non può avvisare quando l'intero host è spento.
Selezionare **Embedded MariaDB** alla prima configurazione. Uptime Kuma resta
sull'SSD locale perché il database non deve risiedere su NFS/SMB.
Impostare una retention moderata, per esempio 30 giorni, per evitare che la
cronologia aumenti inutilmente la dimensione del backup Restic.

## Pi-hole

Aprire `https://TAILSCALE_FQDN:8444/admin/`. Verificare:

```bash
dig @127.0.0.1 example.com
dig @TAILSCALE_IP example.com
```

Il secondo test va eseguito da un altro dispositivo Tailnet. Impostare Pi-hole
come DNS DHCP del router e come nameserver globale Tailscale soltanto dopo il
test. Il mini PC mantiene `accept-dns=false`.

## Nextcloud

Aprire `https://TAILSCALE_FQDN:8445/`. L'account iniziale usa
`NEXTCLOUD_ADMIN_USER` e `NEXTCLOUD_ADMIN_PASSWORD`; creare poi un utente
quotidiano non amministratore.

In **Administration settings > Basic settings**, scegliere `Cron` come sistema
per i job in background. Il container `nextcloud-cron` esegue `/cron.sh`.

I file risiedono in `/srv/media/nextcloud`; configurazione, app e PostgreSQL
restano sull'SSD. Non installare componenti Office o riconoscimento AI finché
non ne è stata valutata la RAM.

## Jellyfin

Aprire `https://TAILSCALE_FQDN:8446/`, creare l'amministratore e aggiungere le
librerie sotto `/media`.

In **Dashboard > Playback > Transcoding**:

1. scegliere Intel Quick Sync, oppure VA-API se QSV non funziona;
2. usare `/dev/dri/renderD128`;
3. abilitare solo codec mostrati dal test `vainfo`;
4. non abilitare AV1 sull'Intel HD 630;
5. impostare `/cache` come percorso transcodifica.

Verificare forzando temporaneamente una qualità più bassa e controllando:

```bash
docker compose -f compose.yaml -f compose.media.yaml exec jellyfin \
  /usr/lib/jellyfin-ffmpeg/vainfo
sudo intel_gpu_top
```

La directory `/media` è montata in sola lettura: Jellyfin non può cancellare i
file originali. Aggiungere inoltre una libreria dedicata con percorso
`/app/videos`: è la directory dei file creati dal downloader, montata in sola
lettura anche dentro Jellyfin.

## StreamingCommunity downloader

Aprire `https://TAILSCALE_FQDN:8450/`. Il servizio è Tailnet-only e
l'autenticazione Jellyfin è obbligatoria.

Al primo accesso:

1. indicare `http://jellyfin:8096` come URL server Jellyfin;
2. accedere con un amministratore Jellyfin per inizializzare il pannello;
3. importare da **Utenti** solo gli account che devono usare il downloader;
4. concedere i permessi minimi necessari;
5. nelle impostazioni usare `/app/videos` come percorso libreria;
6. impostare manualmente il dominio sorgente corrente richiesto
   dall'applicazione;
7. limitare download paralleli e transcodifiche per non saturare CPU e RAM.

Configurazione, utenti, sessioni, richieste e API key Jellyfin risiedono in
`/srv/raspberry-server/data/streamingcommunity` e sono inclusi nel backup
Restic. I video e i segmenti temporanei risiedono in `/srv/media/downloads` e
sono esclusi dal backup di configurazione.

Usare il pannello esclusivamente per contenuti che si è autorizzati a
scaricare. L'immagine upstream usa un tag `latest` mobile: aggiornarla soltanto
dopo un backup tramite `scripts/update-images.sh media`.

## Aurral, Lidarr, slskd e Navidrome

La procedura completa, inclusi percorsi, onboarding, test e backup,
è in [music-stack.md](music-stack.md). Tutti e quattro i pannelli sono
raggiungibili direttamente dalla Tailnet; i container restano comunque legati
al loopback.

## Immich senza machine learning

Aprire `https://TAILSCALE_FQDN:8447/` e creare il primo amministratore.
Il Compose non contiene `immich-machine-learning`.

In **Administration > Settings**:

1. disabilitare interamente Machine Learning, compresi smart search,
   riconoscimento facciale, OCR e duplicate detection ML;
2. impostare concorrenza 1 per conversione video e generazione thumbnail;
3. in Video transcoding scegliere Quick Sync;
4. limitare i thread a 1 o 2;
5. impostare il dominio esterno al relativo URL Tailscale.

La prima importazione resta il momento più pesante. Non eseguirla mentre Ollama
o una transcodifica Jellyfin stanno saturando il mini PC.

Foto e video sono in `/srv/media/immich`; PostgreSQL è in
`/srv/raspberry-server/data/immich/postgres`. Non modificare manualmente la
struttura interna della libreria Immich.

## Vaultwarden

Dopo il restore:

1. verificare più elementi contro il JSON conservato sul PC;
2. verificare allegati, organizzazioni e passkey se usati;
3. sincronizzare telefono e browser;
4. creare e cancellare un elemento di prova;
5. controllare 2FA e recovery code;
6. lasciare `VAULTWARDEN_SIGNUPS_ALLOWED=false`.

Non importare il JSON se il restore completo funziona: Bitwarden non deduplica
gli elementi importati.

## n8n e Ollama

Aprire `https://TAILSCALE_FQDN:8449/`. Per Ollama usare l'URL interno
`http://ollama:11434` e un modello 3B. Vedi [n8n-ollama.md](n8n-ollama.md).
