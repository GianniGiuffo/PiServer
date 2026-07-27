# Configurazione iniziale dei servizi

## Homepage

Homepage è già configurato dai file in `config/homepage`. Si apre su:

```text
https://TAILSCALE_FQDN/
```

Le statistiche Docker passano attraverso `docker-socket-proxy`, che consente
soltanto letture. Per aggiungere collegamenti modificare `services.yaml` e
committare la modifica: il dashboard rimane così riproducibile da Git.

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
| Aurral | `http://aurral:3001/` |
| Navidrome | `http://navidrome:4533/` |
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
