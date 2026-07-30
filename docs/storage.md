# Storage locale, USB e disco di rete

## Struttura

L'SSD interno da 240 GB contiene sistema operativo, immagini Docker,
configurazioni e database:

```text
/opt/raspberry-server
├── repository Git
└── .env

/srv/raspberry-server
├── data
│   ├── caddy
│   ├── immich/postgres
│   ├── jellyfin/config
│   ├── jellyfin/cache
│   ├── aurral
│   ├── lidarr
│   ├── navidrome
│   ├── navidrome-cache
│   ├── n8n
│   ├── nextcloud/html
│   ├── nextcloud/postgres
│   ├── ollama
│   ├── pihole
│   ├── searxng/cache
│   ├── streamingcommunity
│   ├── slskd
│   ├── uptime-kuma
│   └── vaultwarden
├── sites
└── staging
```

Il disco da 4 TB condiviso in LAN viene montato così:

```text
/srv/media
├── .piserver-media
├── downloads    file creati dal downloader e indicizzati da Jellyfin
├── immich       foto e video gestiti da Immich
├── jellyfin     film, serie e musica
├── music
│   ├── library  libreria permanente Lidarr
│   ├── aurral   flow e playlist finali
│   └── .downloads/slskd/{complete,incomplete}
└── nextcloud    directory dati di Nextcloud
```

Non usare `/srv/media` per PostgreSQL, SQLite, Redis o configurazioni. I database
richiedono locking POSIX affidabile e bassa latenza; restano sull'SSD locale.

## Disco USB temporaneo

Per i test è possibile usare un disco USB locale formattato ext4 e montato
sempre in `/srv/media`. Non usare NTFS o exFAT: non offrono il modello di
permessi Linux atteso dai container.

Prima di formattare identificare il disco tramite modello, seriale e percorso
stabile `/dev/disk/by-id`. Non usare ciecamente nomi come `/dev/sda`: possono
cambiare tra un avvio e l'altro.

```bash
lsblk -e7 -o NAME,PATH,SIZE,MODEL,SERIAL,TRAN,FSTYPE,TYPE,MOUNTPOINTS
ls -l /dev/disk/by-id/ | grep usb
```

Soltanto dopo avere verificato che il disco selezionato non contiene dati da
conservare, creare una tabella GPT, una partizione ext4 e l'etichetta
`piserver-test`. Sostituire il placeholder con il percorso `by-id` esatto del
disco intero, senza suffisso `-part1`:

```bash
MEDIA_DISK=/dev/disk/by-id/CHANGE_ME
test -b "${MEDIA_DISK}"
readlink -f "${MEDIA_DISK}"
lsblk -o NAME,PATH,SIZE,MODEL,SERIAL,FSTYPE,MOUNTPOINTS "${MEDIA_DISK}"

sudo parted --script "${MEDIA_DISK}" \
  mklabel gpt \
  mkpart primary ext4 1MiB 100%
sudo partprobe "${MEDIA_DISK}"
sudo udevadm settle
sudo mkfs.ext4 -L piserver-test "${MEDIA_DISK}-part1"
```

Ricavare l'UUID:

```bash
sudo blkid "${MEDIA_DISK}-part1"
```

Aggiungere a `/etc/fstab`, sostituendo `UUID_REALE`:

```fstab
UUID=UUID_REALE /srv/media ext4 defaults,noatime,nofail,x-systemd.automount,x-systemd.device-timeout=10s 0 2
```

Applicare e verificare:

```bash
sudo systemctl daemon-reload
sudo mount /srv/media
ls /srv/media
findmnt -no SOURCE,FSTYPE,OPTIONS /srv/media
```

L'origine deve essere la partizione USB e il filesystem deve risultare `ext4`.

## Disco definitivo in LAN

Preferire NFSv4 quando il NAS/router lo supporta correttamente. Sostituire
`NAS_IP` ed `/export/piserver`:

```fstab
NAS_IP:/export/piserver /srv/media nfs4 rw,noatime,_netdev,nofail,x-systemd.automount,x-systemd.mount-timeout=30s 0 0
```

Poi:

```bash
sudo systemctl daemon-reload
sudo mount /srv/media
findmnt /srv/media
```

Se il dispositivo offre soltanto SMB, creare
`/etc/raspberry-server/media.credentials`:

```ini
username=CHANGE_ME
password=CHANGE_ME
```

Impostare `chmod 600` e usare una riga simile:

```fstab
//NAS_IP/PiServer /srv/media cifs credentials=/etc/raspberry-server/media.credentials,vers=3.1.1,rw,noperm,_netdev,nofail,x-systemd.automount,x-systemd.mount-timeout=30s 0 0
```

Con SMB le autorizzazioni sono controllate principalmente dal server SMB.
Limitare la share al solo mini PC e non esporla a Internet.

## Preparazione del filesystem media

Questi comandi devono essere eseguiti soltanto dopo che `findmnt` conferma il
mount USB o remoto:

```bash
mountpoint /srv/media
sudo mkdir -p /srv/media/{downloads,immich,jellyfin,nextcloud}
sudo mkdir -p \
  /srv/media/music/library \
  /srv/media/music/aurral \
  /srv/media/music/.downloads/slskd/{complete,incomplete}
sudo touch /srv/media/.piserver-media
```

Configurare i permessi necessari sul filesystem locale o sul NAS:

- Immich deve poter scrivere in `immich`;
- `downloads` deve essere scrivibile dal downloader e leggibile dal
  `PUID`/`PGID` usato da Jellyfin; su ext4 usare proprietario `root:PGID` e
  mode `2770`;
- l'UID `33` di `www-data` deve poter scrivere in `nextcloud`;
- l'utente indicato da `PUID` deve almeno leggere `jellyfin`.
- `music` e tutte le sottodirectory devono appartenere a `PUID:PGID`; Lidarr,
  Aurral e slskd scrivono in aree distinte e Navidrome le monta in sola lettura.

Verificare:

```bash
cd /opt/raspberry-server
sudo bash scripts/check-media-mount.sh
sudo systemctl enable --now media-stack.service
```

Se il mount o il marker non esistono, lo script termina prima di invocare
Docker. Non creare il marker sull'SSD locale.

## Storage media assente

I servizi core continuano a funzionare. I servizi media restano fermi oppure
falliscono senza creare directory locali sostitutive. Quando il NAS torna:

```bash
sudo mount /srv/media
sudo systemctl restart media-stack.service
```

Prima di scollegare il disco o spegnere il NAS:

```bash
sudo systemctl stop media-stack.service
sudo umount /srv/media
```

La stessa procedura vale prima di scollegare il disco USB.

## Sostituire il disco temporaneo

Prima di sostituire il disco:

```bash
sudo systemctl disable --now media-stack.service
sudo umount /srv/media
findmnt /srv/media
```

Se i dati di test devono essere conservati, copiarli sul disco definitivo prima
di cambiare la riga `/etc/fstab`; database e configurazioni sull'SSD devono
rimanere associati alla stessa libreria. Se invece i test devono essere
eliminati, non avviare i servizi con un disco vuoto mantenendo i vecchi
database: seguire una procedura di reset controllata per Nextcloud, Immich e
Jellyfin.

Dopo avere montato il nuovo storage nello stesso percorso `/srv/media`,
ricreare o copiare le directory, compreso l'albero `music`, e il marker, eseguire
`check-media-mount.sh` e riabilitare `media-stack.service`.
