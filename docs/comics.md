# Kapowarr e libreria Fumetti

Kapowarr è nello stack media, con avvio e arresto gestiti da
`media-stack.service`. L'immagine stabile `mrcas/kapowarr:v1.3.2` è fissata
anche per digest. Database e configurazione stanno sull'SSD in
`/srv/raspberry-server/data/kapowarr`, montati come `/app/db`.

## Storage e accesso

- Libreria: `/srv/media/Comics`, montata come `/comics` in Kapowarr e in
  sola lettura in Jellyfin.
- Download temporanei: `/srv/media/downloads/.kapowarr-downloads`, montati
  come `/app/temp_downloads` in Kapowarr. Non aggiungere questa cartella alle
  librerie Jellyfin.
- UI privata: `https://TAILSCALE_FQDN:8466/`, tramite Tailscale Serve verso
  `127.0.0.1:5656`. Nessuna route Cloudflare o Funnel.
- Homepage include la card Kapowarr nella sezione media.

Prima di avviare il servizio, verificare il mount e il marker descritti in
[storage.md](storage.md), quindi creare le directory sul disco montato con
proprietario `PUID:PGID` e mode `2770`. Lo script di controllo media verifica
anche queste cartelle. Aggiungere `KAPOWARR_IMAGE` a `.env` copiandolo da
`.env.example`, quindi:

```bash
cd /opt/raspberry-server
sudo bash scripts/check-media-mount.sh
docker compose -f compose.yaml -f compose.media.yaml config --quiet
docker compose -f compose.yaml -f compose.media.yaml up -d --no-deps kapowarr jellyfin
sudo tailscale serve --bg --https=8466 --set-path=/ http://127.0.0.1:5656
```

In Kapowarr aggiungere `/comics` in **Settings > Media Management > Root
Folders**. La directory download resta `/app/temp_downloads`.

## Jellyfin

Creare una libreria di tipo **Books** chiamata **Fumetti**, con percorso
`/comics`, lingua italiana, paese Italia e monitoraggio delle modifiche
abilitato. Il mount in sola lettura protegge gli originali.

Jellyfin supporta, tra gli altri, CBZ, CBR, PDF ed EPUB. La lettura effettiva
dipende dal formato e dal client; CBZ è un formato pratico per fumetti nel
lettore web. I nuovi file devono essere leggibili da `PUID:PGID`.

## ComicVine e backup

La chiave ComicVine non è inclusa nella configurazione. Finché non viene
inserita nelle impostazioni di Kapowarr, ricerca e aggiunta delle serie
tramite ComicVine non sono disponibili. È comunque possibile leggere in
Jellyfin i file compatibili copiati nella cartella `Comics`.

Il backup Restic arresta brevemente Kapowarr e include la sua directory
SQLite su SSD, poi lo riavvia soltanto dopo aver ricontrollato il mount.
I fumetti e i download sul disco media seguono la politica di backup dei
media e non entrano nel backup delle configurazioni.

Fonti: [installazione Docker](https://casvt.github.io/Kapowarr/installation/docker/),
[configurazione iniziale](https://casvt.github.io/Kapowarr/installation/setup_after_installation/),
[formati Jellyfin](https://jellyfin.org/docs/general/server/media/books/).
