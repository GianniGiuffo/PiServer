# Stack musicale: Aurral, Lidarr, slskd e Navidrome

Questo stack usa:

- Lidarr stabile per catalogo, metadati e libreria permanente;
- Aurral per ricerca, richieste, flow e playlist;
- slskd come sorgente Soulseek esterna e prioritaria per i download di Aurral;
- yt-dlp e ffmpeg inclusi nell'immagine Aurral, abilitati per impostazione
  predefinita come fallback disattivabile;
- Navidrome per indicizzazione e streaming.

Tutti e quattro i pannelli sono raggiungibili tramite Tailscale Serve. I
container ascoltano comunque soltanto su loopback; la porta P2P Soulseek
`50300` non viene pubblicata.

Usare lo stack soltanto per file che si è autorizzati a scaricare e condividere.

## Percorsi

Tutti i file musicali, inclusi quelli temporanei, rimangono nel disco montato:

```text
/srv/media/music
├── library
├── aurral
└── .downloads
    └── slskd
        ├── complete
        └── incomplete
```

`library` è gestita da Lidarr. Aurral 2 sposta in `aurral` i file completati
da slskd oppure importa lì quelli prodotti dal proprio yt-dlp. slskd usa
`.downloads/slskd` come area separata. Navidrome indicizza `library` e la
libreria generata da Aurral, ma non `.downloads`.
Lo stack musicale non scrive né in `/srv/media/download` né nella directory
`/srv/media/downloads` già usata da StreamingCommunity.

Database, utenti, impostazioni e playlist restano sull'SSD sotto
`/srv/raspberry-server/data` e sono inclusi nel backup Restic. Nessun percorso
in `/srv/media/music` entra nel backup di configurazione.

## 1. Aggiornare il repository

Prima del passaggio da Aurral 1.x a 2.x creare e verificare uno snapshot
Restic. Il database viene migrato automaticamente al primo avvio di Aurral 2;
il compose usa già la directory host corretta montata su `/config`. I file
esistenti in `/srv/media/music/aurral` non vengono spostati sul disco: cambia
soltanto il percorso visto dal container, da `/app/downloads` a `/data/aurral`.

Sul server:

```bash
cd /opt/raspberry-server
sudo systemctl start backup.service
sudo systemctl status backup.service --no-pager
sudo journalctl -u backup.service -n 100 --no-pager
git pull --ff-only
sudo systemctl stop media-stack.service
```

Continuare soltanto se il log del backup termina con
`Encrypted configuration and database backup completed.`

## 2. Verificare il disco e creare le directory

Non creare directory media finché i primi tre controlli non hanno successo:

```bash
mountpoint /srv/media
findmnt -no SOURCE,FSTYPE,OPTIONS /srv/media
sudo test -f /srv/media/.piserver-media
```

Leggere UID e GID già usati dagli altri container senza eseguire `.env` come
script Bash, quindi creare i percorsi:

```bash
cd /opt/raspberry-server
PUID=$(bash -c 'source ./scripts/read-stack-path.sh; read_stack_value ./.env PUID')
PGID=$(bash -c 'source ./scripts/read-stack-path.sh; read_stack_value ./.env PGID')
printf 'PUID=%s PGID=%s\n' "${PUID}" "${PGID}"

sudo install -d -m 2770 -o "${PUID}" -g "${PGID}" \
  /srv/media/music/library \
  /srv/media/music/aurral \
  /srv/media/music/.downloads/slskd/complete \
  /srv/media/music/.downloads/slskd/incomplete

sudo install -d -m 0750 -o "${PUID}" -g "${PGID}" \
  /srv/raspberry-server/data/aurral \
  /srv/raspberry-server/data/lidarr \
  /srv/raspberry-server/data/slskd \
  /srv/raspberry-server/data/navidrome \
  /srv/raspberry-server/data/navidrome-cache
```

Verificare proprietari e filesystem:

```bash
findmnt -T /srv/media/music
sudo find /srv/media/music -maxdepth 4 -type d -printf '%u:%g %m %p\n'
```

## 3. Aggiungere immagini e credenziali a `.env`

Generare tre segreti diversi:

```bash
openssl rand -hex 32
openssl rand -hex 32
openssl rand -hex 32
```

Aprire il file:

```bash
cd /opt/raspberry-server
nano .env
```

Aggiungere le immagini:

```dotenv
AURRAL_IMAGE=ghcr.io/lklynet/aurral:2.0.3
LIDARR_IMAGE=lscr.io/linuxserver/lidarr:latest
SLSKD_IMAGE=slskd/slskd:0.26.0
NAVIDROME_IMAGE=deluan/navidrome:0.63.2
```

Per usare lo scrobbling Last.fm di Navidrome, aggiungere anche le credenziali
dell'applicazione API Last.fm (non l'username dell'utente):

```dotenv
NAVIDROME_LASTFM_API_KEY=CHANGE_ME
NAVIDROME_LASTFM_SECRET=CHANGE_ME
```

Questi valori sono necessari al server Navidrome per autorizzare ogni utente
verso Last.fm. Non eseguire `source .env`: Docker Compose legge il file
direttamente.

Aggiungere le credenziali. Il nome Soulseek deve essere unico; il primo accesso
alla rete associa il nome alla password scelta.

```dotenv
SLSKD_SLSK_USERNAME=CHANGE_ME
SLSKD_SLSK_PASSWORD=CHANGE_ME
SLSKD_WEB_USERNAME=admin
SLSKD_WEB_PASSWORD=CHANGE_ME
SLSKD_API_KEY=CHANGE_ME
SLSKD_JWT_KEY=CHANGE_ME
```

Usare i tre valori generati rispettivamente per `SLSKD_WEB_PASSWORD`,
`SLSKD_API_KEY` e `SLSKD_JWT_KEY`. Conservare anche username e password
Soulseek nel password manager. Infine:

```bash
chmod 600 .env
bash scripts/preflight.sh
docker compose -f compose.yaml -f compose.media.yaml config --quiet
```

## 4. Installare le unità e scaricare le immagini

Sostituire `YOUR_LINUX_USER` con l'utente che esegue lo stack:

```bash
cd /opt/raspberry-server
sudo bash scripts/install-systemd.sh YOUR_LINUX_USER
sudo systemctl daemon-reload
sudo systemctl enable media-stack.service

docker compose -f compose.yaml -f compose.media.yaml pull \
  lidarr slskd navidrome aurral
```

Il mount `/srv/media` deve provenire da `/etc/fstab`, quindi deve esistere la
relativa unità systemd:

```bash
systemctl status srv-media.mount
systemctl cat media-stack.service
sudo bash scripts/check-media-mount.sh
```

Avviare lo stack:

```bash
sudo systemctl start media-stack.service
sudo systemctl status media-stack.service --no-pager
docker compose -f compose.yaml -f compose.media.yaml ps \
  lidarr slskd navidrome aurral
```

## 5. Configurare Tailscale

Lo script pubblica nella sola Tailnet:

- Aurral su `https://TAILSCALE_FQDN:8451/`;
- Navidrome su `https://TAILSCALE_FQDN:8452/`;
- Lidarr su `https://TAILSCALE_FQDN:8453/`;
- slskd su `https://TAILSCALE_FQDN:8454/`.

Applicare l'intera configurazione Serve:

```bash
cd /opt/raspberry-server
sudo bash scripts/configure-tailscale-serve.sh
tailscale serve status
```

## 6. Configurare Lidarr e slskd

Da un dispositivo collegato alla Tailnet, visitare:

```text
https://TAILSCALE_FQDN:8453/   Lidarr
https://TAILSCALE_FQDN:8454/   slskd
```

In Lidarr:

1. creare l'amministratore e lasciare attiva l'autenticazione;
2. aprire **Settings > Media Management > Root Folders**;
3. aggiungere `/data/library`;
4. scegliere profilo qualità e schema nomi;
5. in **Settings > General** copiare l'API key;
6. lasciare il monitoraggio album predefinito su `None` finché non è stata
   definita una politica di acquisizione permanente.

Questa configurazione usa Lidarr stabile. Aurral può aggiungere e monitorare
artisti e album; per flow e playlist Aurral 2 orchestra il container slskd
tramite API e usa yt-dlp come fallback. Collegare slskd direttamente a Lidarr
per gli album completi resta un flusso distinto e richiederebbe Lidarr nightly
più Tubifarry.

In slskd:

1. accedere con `SLSKD_WEB_USERNAME` e `SLSKD_WEB_PASSWORD`;
2. verificare che lo stato Soulseek sia **Connected**;
3. controllare che le directory siano
   `/data/.downloads/slskd/incomplete` e
   `/data/.downloads/slskd/complete`;
4. non configurare directory condivise e non pubblicare `50300`;
5. non abilitare Remote Configuration: i segreti arrivano già da `.env`.

## 7. Configurare Navidrome

Aprire:

```text
https://TAILSCALE_FQDN:8452/
```

Creare l'utente amministratore. Per ogni utente che deve inviare ascolti:

1. aprire le impostazioni personali di Navidrome;
2. attivare **Scrobble to Last.fm** e completare l'autorizzazione nella pagina
   Last.fm aperta dal browser;
3. attivare **Scrobble to ListenBrainz** e incollare il relativo User Token.

Last.fm e ListenBrainz possono essere abilitati contemporaneamente. Dopo avere
aggiunto le variabili Last.fm in `.env`, riavviare lo stack attraverso systemd,
così il controllo del mount resta obbligatorio:

```bash
sudo systemctl restart media-stack.service
```

Creare il primo amministratore. La libreria predefinita punta già a
`/data/library`.

La versione configurata supporta più librerie. Lasciare che Aurral crei la
libreria per i flow. Se la creazione automatica non riesce, aggiungere una sola
libreria manuale da **Settings > Libraries** con:

```text
Nome: Aurral
Path: /data/aurral
```

Non aggiungere `/data` o `/data/.downloads`: includerebbero file parziali e
duplicati.

## 8. Configurare Aurral

Aprire:

```text
https://TAILSCALE_FQDN:8451/
```

Completare l'onboarding:

1. creare l'amministratore;
2. impostare il contatto email richiesto da MusicBrainz;
3. collegare Lidarr con URL `http://lidarr:8686` e relativa API key;
4. eseguire **Test library access**: deve vedere `/data/library`;
5. in **Settings > Download Clients > Downloads Folder**, impostare
   `/data/aurral`; il compose rende scrivibile soltanto questa sottodirectory;
6. aprire **Download Clients > slskd**, usare URL `http://slskd:5030` e la
   `SLSKD_API_KEY`, quindi eseguire il test di connessione;
7. lasciare slskd con priorità `10`, scegliere il formato preferito e tenere
   **Strict format only** disabilitato durante i primi test;
8. in **Download Clients > yt-dlp**, lasciare attivo il fallback con priorità
   `50`, staging `/config/_staging`, quindi eseguire il test. Disabilitarlo qui
   se non si vogliono download da YouTube/web;
9. collegare Navidrome con URL `http://navidrome:4533` e l'account creato;
10. mantenere il monitoraggio album predefinito su `None`;
11. configurare Last.fm o ListenBrainz soltanto se si desiderano
    raccomandazioni personalizzate.

Il servizio Aurral usa esplicitamente gli stessi resolver Quad9 configurati
come upstream di Pi-hole. Questo evita dipendenze circolari dal DNS del host
dopo un riavvio, mentre i nomi dei servizi (`lidarr`, `navidrome`, `slskd`)
continuano a essere risolti dal DNS interno di Docker.

Aurral `2.0.3` include già yt-dlp e ffmpeg: non installare un altro container.
Con le priorità indicate prova prima slskd e usa yt-dlp solo quando le sorgenti
precedenti falliscono. L'audio ottenuto da YouTube è normalmente lossy; Aurral
lo valida, applica i tag e invia a **Activity > Review** le corrispondenze con
durata dubbia.

## 9. Homepage

Homepage mostra una nuova sezione `Musica`, con lo stesso layout a quattro
colonne delle altre sezioni, contenente:

- Aurral, Navidrome, Lidarr e slskd, tutti apribili dalla Tailnet.
- un controllo HTTP separato dallo stato Docker per ciascun pannello.

Ricaricare Homepage:

```bash
cd /opt/raspberry-server
docker compose restart homepage
```

## 10. Verifiche

```bash
cd /opt/raspberry-server
sudo bash scripts/check-media-mount.sh
docker compose -f compose.yaml -f compose.media.yaml ps
docker compose -f compose.yaml -f compose.media.yaml logs --tail=100 \
  lidarr slskd navidrome aurral
sudo journalctl -u media-stack.service -n 100 --no-pager
```

Da Aurral avviare il download di una traccia autorizzata e verificare:

```bash
sudo find /srv/media/music -maxdepth 5 -type f -printf '%s %p\n'
```

Con slskd, il file parziale deve apparire soltanto sotto
`.downloads/slskd/incomplete`; quello completato passa da `complete` e infine
arriva sotto `aurral`. Con yt-dlp, il lavoro temporaneo rimane in
`/srv/raspberry-server/data/aurral/_staging` e soltanto il file validato arriva
sotto `aurral`. Dopo la scansione deve comparire in Navidrome.

## 11. Verificare Restic

Il backup arresta brevemente i quattro servizi per ottenere database SQLite
coerenti e salva soltanto lo stato su SSD:

```bash
sudo systemctl start backup.service
sudo systemctl status backup.service --no-pager
sudo journalctl -u backup.service -n 100 --no-pager
```

Controllare che il log termini con:

```text
Encrypted configuration and database backup completed.
```

Musica e download sotto `/srv/media/music`, cache Navidrome e copertine
ricostruibili non sono inclusi.

## Porta Soulseek pubblica: scelta successiva

Senza inoltro della porta `50300`, slskd può collegarsi al server Soulseek e ai
peer raggiungibili in uscita. Alcuni peer non raggiungibili direttamente
potrebbero però non comparire o non accettare il trasferimento.

Pubblicare `50300/tcp` può migliorare la connettività, ma:

- aggiunge un servizio P2P esposto su Internet;
- aumenta la superficie d'attacco del container e del parser di protocollo;
- rende esplicita l'associazione fra IP pubblico e attività Soulseek;
- richiede regole coordinate in Docker, firewall e router;
- non deve mai comportare la pubblicazione delle porte Web `5030` o `5031`.

La configurazione predefinita privilegia la sicurezza. Prima di cambiare questa
scelta verificare per qualche settimana risultati, code e download. L'eventuale
apertura va realizzata come modifica separata e controllata.
