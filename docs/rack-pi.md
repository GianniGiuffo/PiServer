# Raspberry Pi `rack-pi`

Questa procedura aggiunge un Raspberry Pi 4 da 4 GB con Raspberry Pi OS Lite
64 bit. Il Raspberry offre il DNS secondario e la diagnostica del rack e
coordina i backup del mini PC. NUT, sensori e ventole non fanno parte di questa
fase: non vengono installati servizi placeholder né accessi GPIO non verificati.

## Ruoli e confini

Sul Raspberry, Tailscale, Restic e i timer systemd girano sull'host. Docker
esegue Pi-hole, Homepage, Uptime Kuma, Nebula Sync e Rest Server. Rest Server
ascolta soltanto sull'IPv4 Tailscale configurato e accetta dal mini PC snapshot
append-only: il client remoto non può cancellare o sovrascrivere i pack già
presenti.

I repository sul disco USB sono separati:

```text
/mnt/rack-backup/repositories
├── minipc
│   ├── state       repository storico migrato
│   └── photos      nuovo repository per le sole foto
└── rack-pi
    └── state       configurazione e stato locale del Raspberry
```

Il mini PC conserva la password del proprio storico e quella delle foto. Non
riceve la password del repository `rack-pi/state`. L'account SSH `pibackup` ha
una sola chiave forzata, valida esclusivamente dall'IP Tailscale di `rack-pi`, e
può eseguire soltanto `scripts/remote-backup.sh` tramite una regola sudo esatta.

## 1. Installazione pulita

Installare Raspberry Pi OS Lite 64 bit sulla SanDisk da 64 GB, impostare
hostname `rack-pi`, abilitare SSH con chiave e collegare Ethernet. La vecchia
installazione viene deliberatamente sostituita senza immagine di rollback.
Prima di formattare, verificare comunque che Vaultwarden e Pi-hole siano già
attivi sul mini PC e che password e repository Restic siano apribili.

Nel FRITZ!Box 7530 AX creare prenotazioni DHCP stabili per `mini-pc` e
`rack-pi`. Poi sul Raspberry:

```bash
sudo git clone https://github.com/GianniGiuffo/PiServer.git /opt/raspberry-server
sudo chown -R "$USER:$USER" /opt/raspberry-server
cd /opt/raspberry-server
sudo bash rack-pi/scripts/bootstrap.sh

sudo tailscale up --ssh --hostname=rack-pi
sudo tailscale set --accept-dns=false
tailscale ip -4
tailscale status --json | jq -r '.Self.DNSName'
```

La vecchia macchina Tailscale `piserver` va eliminata dalla console soltanto
dopo avere verificato `rack-pi`; la nuova installazione riceve una nuova
identità e non riusa lo stato Tailscale della microSD formattata.

## 2. Configurazione del core

```bash
cd /opt/raspberry-server/rack-pi
cp .env.example .env
chmod 600 .env
nano .env
```

Inserire IP/FQDN Tailscale reali. `RACK_PI_TAILSCALE_IP` deve coincidere con
`tailscale ip -4`: Rest Server viene pubblicato esclusivamente su quell'IP.
Usare password Pi-hole lunghe e alfanumeriche per non rendere ambiguo il
formato `URL|password` di Nebula Sync.

Avviare prima Pi-hole senza Nebula Sync, generare nelle API Pi-hole v6 una
password applicazione su entrambi i Pi-hole e inserirle rispettivamente in
`MINIPC_PIHOLE_SYNC_PASSWORD` e `RACK_PI_PIHOLE_SYNC_PASSWORD`. Il replica ha
`webserver.api.app_sudo=true`, necessario per importare le configurazioni con
una password applicazione.

```bash
bash scripts/preflight.sh
docker compose up -d pihole docker-socket-proxy monitoring-api homepage uptime-kuma
sudo bash scripts/configure-tailscale-serve.sh
docker compose up -d nebula-sync
docker compose logs --tail=100 nebula-sync
sudo systemctl enable --now rack-core-stack.service
```

Nebula Sync opera ogni 15 minuti in modalità selettiva. Replica gruppi, adlist,
domain list, client e record/configurazioni DNS, ma non DHCP, upstream o
listening mode. Il mini PC resta la sorgente di verità per Pi-hole.
Sul Raspberry lo storico query Pi-hole è limitato a 30 giorni, i log Docker
ruotano e journald è limitato a 200 MB per contenere le scritture sulla microSD.

## 3. DNS con FRITZ!Box 7530 AX

FRITZ!OS 8.25 offre un solo campo **Server DNS locale** nel DHCP. Per usare
realmente entrambi i Pi-hole senza trasferire il DHCP al mini PC, lasciare che i
client usino il FRITZ!Box come resolver e configurare:

1. **Internet > Dati di accesso > Server DNS**;
2. DNSv4 preferito: IP LAN del Pi-hole sul mini PC;
3. DNSv4 alternativo: IP LAN del Pi-hole su `rack-pi`;
4. disabilitare il fallback automatico a DNS pubblici, altrimenti il filtro può
   essere aggirato quando i Pi-hole non rispondono;
5. non configurare mai il FRITZ!Box come upstream dei Pi-hole: entrambi usano
   direttamente Quad9 e così non si crea un loop.

Applicare lo stesso principio a IPv6: configurare come DNSv6 preferito e
alternativo gli indirizzi ULA stabili dei due Pi-hole, se disponibili. Dopo il
rinnovo del lease, controllare da almeno un client sia `resolvectl status`
(Linux) sia `ipconfig /all` (Windows): non deve comparire un resolver IPv6
pubblico capace di aggirare il FRITZ!Box/Pi-hole. Se gli ULA non sono ancora
stabili, non dichiarare conclusa la migrazione DNS finché questo percorso non è
stato corretto e verificato.

Questa modalità privilegia la continuità DNS ma Pi-hole vede il FRITZ!Box come
client aggregato. Se in futuro serviranno statistiche per singolo dispositivo,
si potrà trasferire DHCP a Pi-hole e distribuire entrambi gli IP con DHCP option
6; non è incluso in questa fase.

Nella console Tailscale aggiungere entrambi gli IPv4 Tailscale come global
nameserver e mantenere MagicDNS. I due server DNS mantengono
`accept-dns=false` per non interrogare sé stessi.

## 4. Preparare il disco USB da 500 GB

Il disco deve essere dedicato, sano ed ext4. Identificarlo tramite modello,
seriale e `/dev/disk/by-id`; non usare alla cieca `/dev/sda`:

```bash
lsblk -e7 -o NAME,PATH,SIZE,MODEL,SERIAL,TRAN,FSTYPE,MOUNTPOINTS
ls -l /dev/disk/by-id/ | grep usb
```

La formattazione distrugge il contenuto. Solo dopo avere controllato il percorso
esatto, creare GPT, una partizione ext4 e l'etichetta `rack-backup`. Montarla in
`/mnt/rack-backup` tramite UUID con:

```fstab
UUID=UUID_REALE /mnt/rack-backup ext4 defaults,noatime,nofail,x-systemd.automount,x-systemd.idle-timeout=10min,x-systemd.device-timeout=30s 0 2
```

```bash
sudo systemctl daemon-reload
sudo mount /mnt/rack-backup
findmnt -T /mnt/rack-backup
```

Non creare manualmente il marker: `setup-repositories.sh` lo fa solo dopo avere
verificato un mount ext4 reale.

## 5. Migrare senza perdere lo storico

Sul mini PC fermare la vecchia pianificazione, eseguire l'ultimo snapshot locale
e annotare repository e password:

```bash
sudo systemctl stop backup.timer backup-recovery.timer
sudo systemctl start backup.service
sudo journalctl -u backup.service -n 100 --no-pager
sudo cat /etc/raspberry-server/backup.env
```

Spostare fisicamente la vecchia chiavetta sul Raspberry e montarla in sola
lettura in un percorso distinto. Copiare il **contenuto del repository**, non la
directory mount generica, conservando metadati e senza cancellare la sorgente:

```bash
sudo install -d -m 0700 /mnt/old-restic
sudo mount -o ro /dev/disk/by-id/PARTIZIONE_STORICA /mnt/old-restic
sudo install -d -m 0700 /mnt/rack-backup/repositories/minipc/state
sudo rsync -aHAX --numeric-ids --info=progress2 \
  /mnt/old-restic/PERCORSO_REPOSITORY/ \
  /mnt/rack-backup/repositories/minipc/state/
```

Copiare inoltre l'esatta `/etc/restic/password` del mini PC in
`/etc/rack-pi/restic-minipc-password` sul Raspberry, mode `0600`. Non generare
una nuova password per lo storico.

```bash
sudo bash /opt/raspberry-server/rack-pi/scripts/setup-repositories.sh
sudo systemctl enable --now rack-rest-server.service
```

Lo script verifica lo storico, crea i repository foto/rack-pi, genera password
distinte e crea l'utente HTTP `minipc`. Conservare fuori dai server tutte le
password in `/etc/rack-pi/restic-*password`.

## 6. Client ristretto sul mini PC

Sul Raspberry copiare la sola chiave pubblica in staging sul mini PC. Sul mini
PC installare l'account, indicando l'IP Tailscale reale di `rack-pi`:

```bash
cd /opt/raspberry-server
sudo bash scripts/install-remote-backup-client.sh \
  /percorso/minipc-backup.pub IP_TAILSCALE_RACK_PI
```

L'installer aggiunge a OpenSSH la porta dedicata `2222`, accessibile soltanto
all'utente `pibackup` con chiave. È necessaria perché Tailscale SSH intercetta
la porta Tailnet `22`; l'accesso interattivo Tailscale SSH esistente resta
invariato. La chiave forzata accetta inoltre come sorgente soltanto l'IP
Tailscale di `rack-pi`.

Sul mini PC installare `config/backup/remote-state-backup.env.example` come
`/etc/raspberry-server/backup.env`. Usare:

- la password HTTP contenuta sul Raspberry in
  `/etc/rack-pi/rest-server-minipc-password` dentro la URL;
- la vecchia `/etc/restic/password` per cifrare/aprire lo storico;
- `RESTIC_SKIP_RETENTION=true`, perché il client è append-only.

Installare `config/backup/photos-backup.env.example` come
`/etc/raspberry-server/photos-backup.env`, ma lasciare
`PHOTO_BACKUP_ENABLED=false` finché il futuro storage dati non è realmente
montato. Copiare sul mini PC la nuova password foto generata sul Raspberry in
`/etc/restic/photos-password`.

Sul mini PC leggere la fingerprint host Ed25519 reale:

```bash
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256
```

Poi sul Raspberry fissarla, senza accettazione TOFU automatica:

```bash
sudo bash rack-pi/scripts/pin-minipc-host-key.sh \
  IP_TAILSCALE_MINIPC SHA256:FINGERPRINT_VERIFICATA 2222
sudo nano /etc/rack-pi/orchestrator.env
sudo systemctl start rack-backup.service
sudo journalctl -u rack-backup.service -n 200 --no-pager
```

## 7. Foto senza fermare Immich

Quando il disco dati sarà disponibile, impostare il percorso reale in
`PHOTO_SOURCE` (default `/srv/media/immich`), poi impostare
`PHOTO_BACKUP_ENABLED=true` sul mini PC e `PHOTOS_ENABLED=true` in
`/etc/rack-pi/backup.env` sul Raspberry. Lo script:

- richiede che `/srv/media` sia un mount reale con `.piserver-media`;
- rifiuta sorgenti che risolvono fuori dal mount;
- esegue prima il backup di stato e il dump PostgreSQL;
- riavvia Immich prima della scansione delle foto;
- salva le foto live, senza fermare Immich per la durata del trasferimento.

Non è uno snapshot atomico del filesystem: un upload iniziato durante la
scansione può appartenere al backup successivo. Gli asset già presenti non
vengono modificati e il backup giornaliero mantiene l'RPO ampiamente entro una
settimana. Se il futuro filesystem offrirà snapshot LVM/Btrfs/ZFS, questa parte
potrà essere resa point-in-time senza downtime.

Il repository `photos` salva l'intera libreria personale Immich, inclusi gli
eventuali brevi video personali necessari a una libreria/Live Photo coerente.
Film, serie, musica e download restano in directory esterne e non sono inclusi.

## 8. Timer, retention e controlli

Dopo un backup manuale riuscito:

```bash
sudo systemctl enable --now \
  rack-backup.timer rack-backup-recovery.timer \
  rack-retention.timer rack-integrity.timer rack-restore-test.timer
systemctl list-timers 'rack-*'
```

- backup giornaliero tra 04:15 e 05:15;
- retry orario se stato/rack superano 26 ore o foto abilitate superano 8 giorni;
- stato e disco aggiornati ogni 5 minuti per Homepage;
- retention/check strutturale settimanale;
- lettura del 10% di ogni repository ogni mese;
- restore non distruttivo trimestrale.

La retention append-only usa finestre temporali, più sicure contro snapshot
ostili: stato/rack 14 giorni, 2 mesi settimanali e 1 anno mensile; foto 7 giorni,
1 mese settimanale e 6 mesi mensile. I tag storici `pi-server` e
`raspberry-server` non vengono selezionati e non sono eliminati.

## 9. Homepage e Uptime Kuma

Aprire `https://RACK_PI_FQDN/` e configurare Uptime Kuma su `:8448`. Aggiungere
`notificationBot` come canale Telegram e almeno:

- ping mini PC LAN e Tailscale;
- Homepage, Pi-hole, Immich, Vaultwarden e Uptime Kuma del mini PC;
- Push monitor **Backup rack**;
- Push monitor **Manutenzione Restic**.

Inserire le URL locali complete dei due Push monitor in
`/etc/rack-pi/orchestrator.env`. Sul mini PC aggiungere monitor inversi per
`rack-pi`, Pi-hole secondario e Homepage. Mantenere retention Uptime Kuma
contenuta per limitare le scritture sulla microSD.

## Riferimenti dei componenti

- [FRITZ!: configurazione di DNS preferito/alternativo e DNS locale](https://fritz.com/en/apps/knowledge-base/FRITZ-Box-7530/165_configuring-different-dns-servers-in-the-fritz-box)
- [Pi-hole: configurazione con FRITZ!Box](https://docs.pi-hole.net/routers/fritzbox/)
- [Rest Server: append-only, autenticazione e private repositories](https://github.com/restic/rest-server)
- [Restic: sicurezza della retention con repository append-only](https://github.com/restic/restic/blob/master/doc/060_forget.rst#security-considerations-in-append-only-mode)
- [Nebula Sync: replica selettiva per Pi-hole v6](https://github.com/lovelaze/nebula-sync)
