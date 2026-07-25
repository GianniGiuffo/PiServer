# Storage locale e disco di rete

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
│   ├── n8n
│   ├── nextcloud/html
│   ├── nextcloud/postgres
│   ├── ollama
│   ├── pihole
│   ├── uptime-kuma
│   └── vaultwarden
├── sites
└── staging
```

Il disco da 4 TB condiviso in LAN viene montato così:

```text
/srv/media
├── .piserver-media
├── immich       foto e video gestiti da Immich
├── jellyfin     film, serie e musica
└── nextcloud    directory dati di Nextcloud
```

Non usare `/srv/media` per PostgreSQL, SQLite, Redis o configurazioni. I database
richiedono locking POSIX affidabile e bassa latenza; restano sull'SSD locale.

## Protocollo consigliato

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

## Preparazione iniziale

Questi comandi devono essere eseguiti soltanto dopo che `findmnt` conferma il
mount remoto:

```bash
mountpoint /srv/media
sudo mkdir -p /srv/media/{immich,jellyfin,nextcloud}
sudo touch /srv/media/.piserver-media
```

Configurare sul NAS i permessi necessari:

- Immich deve poter scrivere in `immich`;
- l'UID `33` di `www-data` deve poter scrivere in `nextcloud`;
- l'utente indicato da `PUID` deve almeno leggere `jellyfin`.

Verificare:

```bash
cd /opt/raspberry-server
sudo bash scripts/check-media-mount.sh
sudo systemctl enable --now media-stack.service
```

Se il mount o il marker non esistono, lo script termina prima di invocare
Docker. Non creare il marker sull'SSD locale.

## Assenza del NAS

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
