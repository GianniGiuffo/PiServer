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
- **Rete**: traffico istantaneo e controllo coordinato dei due Pi-hole;
- **Raspberry**: stato, servizi e tempo dall'ultimo backup riuscito.

Il contenitore vuoto degli information widget viene nascosto da `custom.css`.
Nelle quattro card di sistema ogni etichetta (per esempio **CPU**) è mostrata
sopra al relativo valore; il CSS è limitato agli ID `system-*` e non cambia i
widget degli altri servizi.

`monitoring-api` legge soltanto i file necessari sotto `/proc` e `/sys` e i
JSON locali con lo stato di media e backup. Non monta `/srv/media` e non riceve
socket Docker o systemd. Sul Raspberry consulta il proxy Docker di sola lettura
per aggregare lo stato dei servizi; la sua API è esposta soltanto in Tailnet.
`media-status.timer` aggiorna capacità e stato del
NAS ogni minuto; se `/srv/media` non è un mount reale, la banda NAS mostra
**Non montato**. Il NAS non è quindi una dipendenza di avvio di Homepage.
Se lo stack media è abilitato, `media-recovery.timer` ritenta ogni minuto il
mount e l'avvio dei servizi dopo un'assenza temporanea dello storage.

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
programmato alle 04:15 con un ritardo casuale massimo di un'ora. Quando è
attivo `rack-pi`, il prossimo avvio effettivo è gestito dal timer sul Raspberry;
il mini PC conserva questo orario soltanto come fallback visuale.

Homepage mostra due controlli distinti per i servizi configurati:

- il controllo Docker indica se il processo è avviato e, quando presente, usa
  anche l'`healthcheck` definito nel Compose;
- `siteMonitor` esegue una richiesta HTTP interna e verifica che
  l'applicazione risponda davvero.

I link delle card servizio usano `target: _blank` e si aprono in una nuova
scheda. Il controllo Pi-hole usa un backend loopback pubblicato da Tailscale
Serve: verifica l'identità Tailnet, non invia password al browser e ripristina
il primo nodo se l'aggiornamento del secondo fallisce.

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
| Seerr | `http://seerr:5055/api/v1/settings/public` |
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

Riutilizzare le due password applicazione già configurate per nebula-sync:
copiarle rispettivamente da `MINIPC_PIHOLE_SYNC_PASSWORD` e
`RACK_PI_PIHOLE_SYNC_PASSWORD` del Raspberry a
`MINIPC_PIHOLE_CONTROL_PASSWORD` e `RACK_PI_PIHOLE_CONTROL_PASSWORD` sul mini
PC. Indicare inoltre l'identità Tailnet autorizzata in
`PIHOLE_CONTROL_ALLOWED_TAILSCALE_LOGINS`. Applicare le route e avviare il
controller:

```bash
sudo bash scripts/configure-tailscale-serve.sh
sudo systemctl enable --now pihole-control.service
```

Sul Raspberry rieseguire `sudo bash scripts/configure-tailscale-serve.sh` per
pubblicare la sola API di stato sulla porta Tailnet 8456.

## Nextcloud

Aprire `https://TAILSCALE_FQDN:8445/`. L'account iniziale usa
`NEXTCLOUD_ADMIN_USER` e `NEXTCLOUD_ADMIN_PASSWORD`; creare poi un utente
quotidiano non amministratore.

In **Administration settings > Basic settings**, scegliere `Cron` come sistema
per i job in background. Il container `nextcloud-cron` esegue `/cron.sh`.

I file risiedono in `/srv/media/nextcloud`; configurazione, app e PostgreSQL
restano sull'SSD. Non installare componenti Office o riconoscimento AI finché
non ne è stata valutata la RAM.

Per i link pubblici con password facoltativa e senza scadenza obbligatoria,
seguire [public-sharing.md](public-sharing.md). Non aprire porte sul router.

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

### Upgrade a Jellyfin 12 e Jellyfin Helper

Jellyfin 12 converte il database al primo avvio e non consente un downgrade
senza ripristino. Prima dell'upgrade verificare di essere almeno su `10.10.7`,
controllare che non esistano utenti i cui nomi differiscono soltanto per
maiuscole/minuscole e rimuovere i plugin di terze parti non compatibili.

Creare e verificare uno snapshot completo, quindi aggiornare la variabile
`JELLYFIN_IMAGE` della `.env` alla versione revisionata in `.env.example`:

```bash
sudo JELLYFIN_FULL_BACKUP=true bash scripts/backup.sh
docker compose -f compose.yaml -f compose.media.yaml pull jellyfin
docker compose -f compose.yaml -f compose.media.yaml up -d jellyfin
docker compose -f compose.yaml -f compose.media.yaml logs -f jellyfin
```

Non interrompere le migrazioni. Quando `/System/Info/Public` riporta la nuova
versione e `/health` risponde, eseguire una scansione completa di tutte le
librerie. Il primo passaggio può durare sensibilmente più del normale.

Installare poi la release verificata di Jellyfin Helper. Lo script installa
anche la versione Jellyfin 12.1 di File Transformation e la sua dipendenza
Newtonsoft.Json 13.0.1, assente dall'archivio upstream. Helper viene compilato
dal tag 3.0.0.2 con tre compatibility file revisionati in
`patches/jellyfin-helper`: alias dei generi italiani per TMDb e una scheda
**Discovery** compatibile con la navigazione React di Jellyfin 12. Lo script
controlla versione Jellyfin e SHA-256 di tutti gli artefatti, conserva eventuali
versioni precedenti e ripristina i plugin se Jellyfin non torna sano:

```bash
bash scripts/install-jellyfin-helper.sh
```

La sola attività Recommendations può essere portata su `Activate` dopo aver
revisionato i risultati: è quella che alimenta Discovery. Lasciare in `Dry Run`
le attività di pulizia o cancellazione finché i relativi log non sono stati
revisionati. Discovery è una scheda del client web, non una libreria Jellyfin;
compare nella barra superiore e nel menu laterale quando esistono suggerimenti
per l'utente corrente.

## Seerr

Aprire `https://TAILSCALE_FQDN:8457/` e completare il wizard usando Jellyfin:

1. impostare `http://jellyfin:8096` come URL interno del server;
2. autenticarsi con l'amministratore solo per il setup iniziale;
3. sincronizzare tutte le librerie Jellyfin interessate;
4. lasciare Radarr e Sonarr non configurati: questa installazione è
   intenzionalmente discovery-only;
5. copiare l'API key Seerr nelle impostazioni di Jellyfin Helper e usare
   `http://seerr:5055` come URL interno;
6. lasciare le richieste in approvazione manuale e verificare che i titoli già
   presenti in Jellyfin non vengano proposti dalla discovery.

La configurazione risiede in `/srv/raspberry-server/data/seerr` ed entra nel
backup Restic. La card corrispondente è nella sezione **Media e file** di
Homepage.

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

La prima importazione resta il momento più pesante. Non eseguirla mentre una
transcodifica Jellyfin sta saturando il mini PC.

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

## n8n e SearXNG

Aprire `https://TAILSCALE_FQDN:8449/`. Ollama e i modelli AI locali non fanno
parte dello stack.

SearXNG e il proxy WebDAV Nextcloud non pubblicano porte. n8n li raggiunge
rispettivamente su `http://searxng:8080` e
`http://nextcloud-readonly:8080`; la configurazione dei relativi strumenti AI
è descritta in [ai-connectors.md](ai-connectors.md).

GitHub e DeepL non richiedono container aggiuntivi: si configurano come nodi
nativi collegati al connettore **Tool** dell'AI Agent, usando credenziali create
nell'interfaccia n8n. La procedura, i permessi GitHub di sola lettura e le
cautele privacy per DeepL sono in
[n8n-github-deepl.md](n8n-github-deepl.md).
