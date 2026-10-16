# Film e serie condivisi con un amico: NFSv4 tramite Tailscale

Questa procedura permette al tuo Jellyfin e a quello del tuo amico di leggere
gli stessi video, conservando configurazioni, utenti, filtri, metadati e progressi
di visione indipendenti. I file rimangono sul disco collegato al mini PC.
Il tuo Jellyfin continua a leggerli direttamente; quello dell'amico li legge
tramite un mount NFS sull'host Linux, passato al container Docker.

La guida configura il mini PC Debian 13 di PiServer come server NFS e assume
Debian/Ubuntu con systemd anche per i comandi del client. Con un'altra
distribuzione cambiano installazione dei pacchetti e, eventualmente, SELinux.
Non eseguire i comandi dell'amico sul mini PC e viceversa.

## 1. Percorsi e valori da raccogliere

I percorsi previsti dalla repo sono:

| Dove | Percorso | Uso |
| --- | --- | --- |
| Mini PC | `/srv/media/downloads/Films` | film sul disco locale |
| Mini PC | `/srv/media/downloads/Series` | serie sul disco locale |
| Host dell'amico | `/mnt/piserver/Films` | mount NFS dei film |
| Host dell'amico | `/mnt/piserver/Series` | mount NFS delle serie |
| Container dell'amico | `/media/piserver/Films` | libreria film condivisi |
| Container dell'amico | `/media/piserver/Series` | libreria serie condivise |

I percorsi derivano da `compose.media.yaml` e `docs/storage.md`: nel tuo
container i download sono già disponibili sotto `/app/videos`. Verifica che i
film da condividere siano davvero in `Films` e `Series`; il mount `/media` del
tuo Jellyfin corrisponde invece a `/srv/media/jellyfin`. Se usi altre directory,
sostituisci i percorsi in tutta la guida, senza esportare indiscriminatamente
`/srv/media`: contiene anche foto, Nextcloud e altri dati.

Su **entrambi gli host**, con Tailscale già autenticato:

```bash
tailscale ip -4
tailscale status
```

Annotate l'IPv4 Tailscale di ciascuno. Nei file di esempio:

| Valore di esempio | Sostituire con |
| --- | --- |
| `100.101.102.103` | IP Tailscale del tuo mini PC |
| `100.104.105.106` | IP Tailscale dell'host Docker dell'amico |
| `/opt/jellyfin` | directory Compose effettiva dell'amico |
| `compose.yaml` | nome del suo file Compose |
| `jellyfin` | nome del suo servizio Compose |

Gli IP sono esempi, non indirizzi rilevati. Tailscale deve girare sugli **host**:
non basta averlo sul telefono o in un container Docker isolato. Il client NFS
di questa guida è l'host dell'amico, quindi l'export autorizza il suo IP host,
non un IP Docker `172.x`.

## 2. Collegare le due reti Tailscale

Dal tuo account apri [Machines](https://login.tailscale.com/admin/machines),
seleziona il mini PC, scegli **Share** e genera un invito monouso. Passalo
all'amico, che deve accettarlo con l'account proprietario del suo host Linux.
Condividi la macchina, senza aggiungerlo come amministratore della tua rete.

Per il normale sharing tra tailnet, il suo host deve essere un dispositivo
associato al suo utente: i dispositivi client con tag non possono accedere alle
macchine ricevute mediante questo tipo di invito. Se il suo host è tagged,
questa guida richiede prima di adattare l'identità Tailscale; non rimuovere tag
alla cieca perché può cambiare altri accessi. Vedi la
[documentazione sharing](https://tailscale.com/docs/features/sharing).

### Regola sul tuo account

Prima di accettare la condivisione, salvare una copia della policy corrente da
**Access controls**. Integrare nell'array `grants` questa regola, sostituendo
gli IP:

```json
{
  "src": ["100.104.105.106"],
  "dst": ["100.101.102.103"],
  "ip": ["tcp:2049"]
}
```

È un elemento dell'array, non una policy completa da incollare al posto di
quella esistente. Mantieni le regole per backup, rack-pi, SSH e servizi attuali.

**Le autorizzazioni sono additive:** aggiungere questa regola non restringe
una precedente regola che consente già tutto. In particolare, rivedi eventuali
ACL `src: ["*"]` / `dst: ["*:*"]` o grant `src: ["*"]` / `ip: ["*"]`:
possono includere anche gli utenti esterni delle condivisioni.
Sostituisci il sorgente generico delle regole interne con gli utenti/gruppi
interni effettivamente autorizzati, preservando gli accessi necessari dei
dispositivi con tag. Non applicare un esempio minimo che elimini le altre
regole della tua rete. La policy finale deve consentire all'host dell'amico
soltanto `mini-PC:2049`, senza accesso a SSH o alle interfacce web del mini PC.

Se anche l'amico usa una policy restrittiva, deve consentire il traffico
uscente dal suo host al mini PC su TCP 2049 nella propria policy, usando
l'indirizzo del mini PC visibile dalla sua rete. In caso di collisione degli
indirizzi, Tailscale può presentare un IP diverso al destinatario: verificare
`tailscale status` anziché assumere che i due punti di vista coincidano.

Questa procedura usa gli IPv4 per evitare dipendenze da MagicDNS. Non richiede
subnet router, exit node, Tailscale Serve, Funnel o port forwarding sul router.
Non cambiare `scripts/configure-tailscale-serve.sh`.

## 3. Mini PC: verificare il disco e installare il server

I seguenti comandi si eseguono **sul tuo mini PC**. La procedura assume che non
ci siano export NFS già in uso: se esistono, integrare la configurazione prima
di riavviare il servizio, perché limitarlo all'IP Tailscale interromperebbe
gli eventuali client LAN.

```bash
findmnt -M /srv/media -o TARGET,SOURCE,FSTYPE,OPTIONS
mountpoint /srv/media
ls -ld /srv/media/downloads/Films /srv/media/downloads/Series
sudo cat /etc/exports
sudo ls /etc/exports.d
```

È normale che i due ultimi percorsi non esistano prima dell'installazione.
Il mount deve essere quello del disco fisico corretto e il filesystem deve
supportare export NFS e ACL POSIX, per esempio ext4. Non formattare il disco e
non ricreare le directory se manca il mount. Se risulta NTFS/exFAT o un
filesystem remoto, adattare la procedura prima di continuare.

```bash
sudo apt update
sudo apt install nfs-kernel-server acl
sudo systemctl stop nfs-server.service
```

Il pacchetto può avviare automaticamente il servizio: a questo punto non
abbiamo ancora aggiunto export. Non abilitare accessi generici nel firewall.

## 4. Mini PC: identità dedicata e permessi di lettura

Creare un account di sistema senza login:

```bash
id nfsmedia || sudo useradd --system --user-group --no-create-home \
  --shell /usr/sbin/nologin nfsmedia
id nfsmedia
```

Se l'account esiste già e ha un altro scopo, usare un nome diverso in tutta la
procedura. Conservare gli ACL attuali prima delle modifiche; la scansione può
richiedere tempo su librerie grandi:

```bash
sudo install -d -m 0700 /root/piserver-nfs-backup
sudo getfacl -p /srv/media /srv/media/downloads | \
  sudo tee /root/piserver-nfs-backup/parents.acl >/dev/null
sudo getfacl -R -p /srv/media/downloads/Films /srv/media/downloads/Series | \
  sudo tee /root/piserver-nfs-backup/media.acl >/dev/null
```

Eseguire questo backup una sola volta, prima di modificare gli ACL; una nuova
esecuzione sovrascrive la fotografia precedente. Non viene copiato alcun video.

Concedere attraversamento sui genitori e lettura sui contenuti:

```bash
sudo setfacl -m u:nfsmedia:--x /srv/media /srv/media/downloads
sudo setfacl -R -m u:nfsmedia:rX \
  /srv/media/downloads/Films /srv/media/downloads/Series
sudo find /srv/media/downloads/Films /srv/media/downloads/Series -type d \
  -exec setfacl -m d:u:nfsmedia:r-x {} +
sudo -u nfsmedia ls /srv/media/downloads/Films
sudo -u nfsmedia ls /srv/media/downloads/Series
```

`rX` concede lettura e attraversamento delle directory; non rende eseguibili
tutti i video. Non fare `chmod -R 777` né cambiare proprietari e gruppi usati da
Radarr/Sonarr. `setfacl` può ricalcolare la mask ACL: verificare gli eventuali
ACL preesistenti e i permessi effettivi con `getfacl`.

Gli ACL predefiniti aiutano con i nuovi file creati in queste directory, ma
file spostati da fuori e hardlink importati da Radarr/Sonarr mantengono i propri
permessi. Dopo una nuova importazione, verificare la leggibilità come
`nfsmedia`. Se manca, riapplicare il comando ricorsivo sopra solo alle due
librerie e integrare il passaggio nel processo d'importazione. Non concedere
accesso a `.arr-downloads` per aggirare il problema. Il successo della prima
scansione non garantisce automaticamente i permessi delle importazioni future.

## 5. Mini PC: export dei soli film e serie

Nella stessa shell, inserire l'IP reale del server dell'amico:

```bash
FRIEND_TS_IP=100.104.105.106
NFS_MEDIA_UID=$(id -u nfsmedia)
NFS_MEDIA_GID=$(id -g nfsmedia)
sudo install -d -m 0755 /etc/exports.d
sudo tee /etc/exports.d/piserver-friend.exports >/dev/null <<EOF
/srv/media/downloads/Films ${FRIEND_TS_IP}(ro,sync,subtree_check,all_squash,anonuid=${NFS_MEDIA_UID},anongid=${NFS_MEDIA_GID},mountpoint=/srv/media,sec=sys)
/srv/media/downloads/Series ${FRIEND_TS_IP}(ro,sync,subtree_check,all_squash,anonuid=${NFS_MEDIA_UID},anongid=${NFS_MEDIA_GID},mountpoint=/srv/media,sec=sys)
EOF
```

Non mettere uno spazio tra l'IP e `(`. Le variabili vengono risolte quando
scrivi il file: `/etc/exports` non è uno script di shell.

- `ro` impedisce la scrittura anche se il client chiede un mount `rw`.
- `all_squash` mappa tutti gli utenti remoti, incluso root, su `nfsmedia`;
  non serve far coincidere UID/GID tra i vostri Docker.
- `subtree_check` controlla il sottoalbero perché stiamo esportando directory
  di un filesystem che contiene anche altri dati. Rinominare file aperti può
  richiedere di riaprire la riproduzione.
- `mountpoint=/srv/media` evita di esportare le directory sottostanti quando
  il disco non è montato.
- `sec=sys` si affida all'host autorizzato: Tailscale controlla l'accesso di
  rete e cifra il trasporto. Non c'è una password NFS per l'amico.

Non esportare anche `/srv/media` o `/srv/media/downloads` con regole più ampie,
non aggiungere `crossmnt` e non usare `no_root_squash`.

## 6. Mini PC: NFSv4.1/4.2 sul solo indirizzo Tailscale

```bash
sudo install -d -m 0755 /etc/nfs.conf.d
sudo nano /etc/nfs.conf.d/90-piserver-tailscale.conf
```

Inserire, con l'IP reale del **mini PC**:

```ini
[nfsd]
host = 100.101.102.103
port = 2049
tcp = yes
udp = no
vers3 = no
vers4 = yes
vers4.0 = no
vers4.1 = yes
vers4.2 = yes
rdma = no
```

Creare un drop-in per aspettare disco e Tailscale:

```bash
sudo systemctl edit nfs-server.service
```

Inserire:

```ini
[Unit]
Requires=tailscaled.service
After=tailscaled.service
RequiresMountsFor=/srv/media
BindsTo=srv-media.mount
After=srv-media.mount

[Service]
ExecStartPre=/usr/bin/mountpoint -q /srv/media
ExecStartPre=/usr/bin/timeout 60 /usr/bin/bash -c 'until /usr/bin/tailscale ip -4 2>/dev/null | /usr/bin/grep -Fxq 100.101.102.103; do /usr/bin/sleep 1; done'
```

`srv-media.mount` è il nome corrispondente al percorso `/srv/media`, già usato
da PiServer. NFS resta legato al disco; la guida non cambia l'avvio del tuo
stack Docker. Sostituire l'IP di esempio anche nel controllo `ExecStartPre`:
attende fino a 60 secondi che Tailscale riporti l'indirizzo previsto.
`After=tailscaled` da solo non garantisce che l'autenticazione sia completata.
Se l'indirizzo non è pronto entro l'attesa, ripetere l'avvio NFS quando
Tailscale è connesso; non vengono aperte porte su un indirizzo alternativo.

```bash
sudo systemctl daemon-reload
sudo exportfs -rav
sudo systemctl enable --now nfs-server.service
sudo systemctl restart nfs-server.service
sudo exportfs -v
sudo ss -lntp '( sport = :2049 )'
sudo cat /proc/fs/nfsd/versions
```

Devono comparire solo i due export previsti per l'IP dell'amico, con `ro` e gli
ID di `nfsmedia`. La 2049 deve ascoltare **solo sull'IPv4 Tailscale** indicato,
non su `0.0.0.0`, `[::]` o sull'IP LAN. Le versioni disponibili devono includere
4.1/4.2 ed escludere 3 e 4.0. Non procedere se il risultato è diverso: verificare
`/etc/nfs.conf`, gli altri drop-in e le opzioni di avvio del servizio.

NFSv4.1+ usa TCP 2049 per questo collegamento: non aprire 111/rpcbind o porte
mountd/statd verso l'amico. Gli eventuali demoni ausiliari installati non vanno
pubblicati. Se hai già un firewall host restrittivo, aggiungi alla configurazione
esistente l'allow in ingresso su `tailscale0`, sorgente IP dell'amico,
destinazione IP del mini PC, TCP 2049. Non attivare o riscrivere un firewall
generico su un host con Docker/Tailscale: la policy Tailscale e l'export devono
essere verificati comunque, senza presumere che UFW filtri tutto il traffico VPN.

## 7. Amico: verificare Tailscale e montare le cartelle

Da qui i comandi si eseguono **sull'host Linux dell'amico**, non nel container.

```bash
sudo apt update
sudo apt install nfs-common netcat-openbsd
tailscale status
tailscale ping 100.101.102.103
nc -vz -w 5 100.101.102.103 2049
```

Sostituire sempre l'IP. `tailscale ping` aiuta a distinguere percorso diretto e
relay, ma non prova che la porta NFS sia autorizzata: serve anche il test TCP.
Una connessione diretta è preferibile per video pesanti; misurare comunque la
velocità effettiva. Una porta web del mini PC, ad esempio 8446, deve risultare
inaccessibile da lui se avete scelto di autorizzare soltanto NFS.

Creare le directory **vuote**:

```bash
sudo install -d -m 0755 /mnt/piserver/Films /mnt/piserver/Series
```

Salvare una copia di `/etc/fstab` e aggiungere due righe con l'IP reale:

```bash
sudo cp -a /etc/fstab /etc/fstab.before-piserver-nfs
sudo nano /etc/fstab
```

Ogni export seguente è una singola riga:

```fstab
100.101.102.103:/srv/media/downloads/Films /mnt/piserver/Films nfs ro,vers=4.1,proto=tcp,sec=sys,hard,_netdev,nofail,x-systemd.automount,x-systemd.mount-timeout=30s,x-systemd.requires=tailscaled.service,nosuid,nodev,noexec 0 0
100.101.102.103:/srv/media/downloads/Series /mnt/piserver/Series nfs ro,vers=4.1,proto=tcp,sec=sys,hard,_netdev,nofail,x-systemd.automount,x-systemd.mount-timeout=30s,x-systemd.requires=tailscaled.service,nosuid,nodev,noexec 0 0
```

Si fissa 4.1 per compatibilità; si può scegliere 4.2 dopo aver verificato che
entrambi i kernel la supportino. Non usare `nolock`, non serve con NFSv4.
`nofail` permette all'host di completare il boot; il servizio Jellyfin aggiunto
più avanti richiederà comunque i mount. Non aggiungere un idle timeout che
smonti automaticamente una directory già passata al container.

```bash
sudo systemctl daemon-reload
sudo systemctl start mnt-piserver-Films.automount mnt-piserver-Series.automount
ls /mnt/piserver/Films
ls /mnt/piserver/Series
findmnt -t nfs,nfs4 -o TARGET,SOURCE,FSTYPE,OPTIONS
```

`ls` attiva i mount. Verificare che entrambe le directory risultino realmente
NFS, con sorgente corretta e `ro,vers=4.1`: un mount `autofs` da solo non prova
che la connessione NFS sia riuscita.

Verificare anche l'apertura di un video reale, non soltanto la lista:

```bash
head -c 1048576 '/mnt/piserver/Films/PERCORSO_REALE_DEL_VIDEO.mkv' >/dev/null
```

Sostituire il percorso, inclusa l'eventuale sottocartella. Come prova di sola
lettura, il seguente comando deve fallire con filesystem in sola lettura:

```bash
touch /mnt/piserver/Films/.piserver-write-test
```

Se riesce, fermarsi, rimuovere soltanto quel file di prova e correggere export
e mount prima di proseguire.

### Cosa succede se si interrompe Internet

La scelta `hard` ritenta le operazioni NFS finché il server torna disponibile:
una lettura e una scansione Jellyfin possono restare in attesa durante il guasto.
`x-systemd.mount-timeout=30s` limita il tentativo iniziale di montaggio gestito
da systemd, **non** le letture di un mount già attivo. Anche fermare il container
può richiedere che la rete torni disponibile se ha processi bloccati in I/O.

Non promette quindi che tutte le funzioni locali di Jellyfin continuino senza
ritardi. `soft` restituisce errori dopo i tentativi configurati, ma può produrre
letture incomplete/errori e non è un sostituto trasparente di `hard`: questa
guida non lo usa. Se serve autonomia completa durante guasti o spegnimenti del
mini PC, serve una copia locale dei media oppure una diversa separazione dei
servizi. Evitare smontaggi forzati o lazy come procedura ordinaria.

## 8. Amico: aggiungere i bind mount a Jellyfin Docker

Prima salvare il suo Compose e fare un backup della configurazione Jellyfin
con il container fermo, secondo la procedura già usata sul suo server. Conservare
immagine, porte, utenti, accelerazione hardware e mount locali esistenti.

Nel servizio Jellyfin aggiungere questi elementi all'array `volumes` esistente
e impostare la policy indicata per delegare l'avvio a systemd:

```yaml
services:
  jellyfin:
    restart: "on-failure:5"
    volumes:
      # Conservare anche tutti i volumi già presenti, inclusi /config e /cache.
      - type: bind
        source: /mnt/piserver/Films
        target: /media/piserver/Films
        read_only: true
        bind:
          create_host_path: false
      - type: bind
        source: /mnt/piserver/Series
        target: /media/piserver/Series
        read_only: true
        bind:
          create_host_path: false
```

È un frammento da integrare, non un Compose completo. `create_host_path: false`
evita che Docker inventi una directory mancante, ma da solo **non** distingue
una directory vuota da un filesystem NFS: per questo servono i controlli e
l'ordine di avvio del passaggio successivo.

Con `always` o `unless-stopped`, Docker potrebbe riavviare Jellyfin al boot
prima dei mount, aggirando systemd. `on-failure:5` gestisce i crash del processo
senza avviarlo automaticamente dopo il riavvio del daemon Docker. Disattivare
eventuali altri script/unità che avviano lo stesso servizio indipendentemente.

## 9. Amico: avvio Jellyfin solo dopo i mount NFS

Questo esempio assume Compose in `/opt/jellyfin/compose.yaml`, servizio
`jellyfin`, Docker rootful e comando `/usr/bin/docker`. Adattare i percorsi e
riutilizzare l'eventuale servizio systemd già esistente, senza creare due
gestori per lo stesso container. Se usa più file Compose, `.env` altrove o
`--project-name`, conservare le stesse opzioni in **tutti** i comandi sotto.
Verificare il percorso Docker con `command -v docker`.

Creare `/etc/systemd/system/jellyfin-with-piserver.service`:

```ini
[Unit]
Description=Jellyfin Docker after PiServer NFS mounts
Requires=docker.service tailscaled.service
Wants=network-online.target
After=docker.service tailscaled.service network-online.target
RequiresMountsFor=/mnt/piserver/Films /mnt/piserver/Series

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/jellyfin
ExecStartPre=/usr/bin/findmnt -rn -M /mnt/piserver/Films -t nfs,nfs4
ExecStartPre=/usr/bin/findmnt -rn -M /mnt/piserver/Series -t nfs,nfs4
ExecStart=/usr/bin/docker compose -f /opt/jellyfin/compose.yaml up -d --no-deps --force-recreate jellyfin
ExecStop=/usr/bin/docker compose -f /opt/jellyfin/compose.yaml stop jellyfin
TimeoutStartSec=180
TimeoutStopSec=120

[Install]
WantedBy=multi-user.target
```

Per esempio aprire il file con `sudo nano` e incollare il blocco. I mount devono
essere reali prima della creazione del container: un bind Docker già creato su
una directory vuota può continuare a vedere quella directory anche dopo un
montaggio successivo sull'host. Il servizio ricrea soltanto Jellyfin per evitare
di riutilizzare bind vecchi; non elimina i dati persistenti.

Prima attivazione, dalla directory Compose effettiva:

```bash
cd /opt/jellyfin
docker compose -f compose.yaml config --quiet
docker compose -f compose.yaml stop jellyfin
sudo systemctl daemon-reload
sudo systemctl enable --now jellyfin-with-piserver.service
sudo systemctl status jellyfin-with-piserver.service --no-pager
docker compose -f compose.yaml exec jellyfin ls -l /media/piserver/Films
docker compose -f compose.yaml exec jellyfin ls -l /media/piserver/Series
```

Verificare anche la lettura di un file dall'interno del container con `head`,
come nel test sull'host. Se il container esegue la shell da root, ripetere il
test con `exec --user UID:GID` usando l'utente effettivo del processo Jellyfin.
La mappatura `all_squash` opera sul server NFS e permette la stessa lettura
anche con UID diversi; eventuali restrizioni locali del container restano valide.

Conservare `/config` e `/cache` sui dischi locali dell'amico. NFS contiene solo
i video: non spostare database SQLite, cache e transcodifiche sulla condivisione.

## 10. Amico: creare le librerie Jellyfin e scegliere le regole

Nell'amministrazione del **suo** Jellyfin aggiungere, inizialmente separate:

| Nome proposto | Tipo | Percorso nel container |
| --- | --- | --- |
| Film PiServer | Film | `/media/piserver/Films` |
| Serie PiServer | Serie TV | `/media/piserver/Series` |

Può invece aggiungere questi percorsi alle sue librerie Film/Serie esistenti
se preferisce un catalogo unificato. Tenere librerie separate semplifica però
permessi per utente, manutenzione e riconoscimento dei contenuti remoti.

Ciascuno configura nel proprio Jellyfin:

- utenti autorizzati alle librerie e restrizioni per classificazione;
- lingua dei metadati, copertine, raccolte e ordinamento;
- preferenze audio/sottotitoli e qualità di riproduzione;
- progressi di visione, preferiti e accesso dei propri dispositivi.

Disabilitare sulla libreria remota il salvataggio di NFO, immagini e sottotitoli
nella cartella dei video: la condivisione è in sola lettura. Conservare queste
informazioni nel proprio storage Jellyfin. NFO già presenti nei tuoi file
possono comunque essere letti: la priorità dei metadati locali va regolata
anche nelle impostazioni dei lettori di metadati del suo server.

Per NFS usare scansioni pianificate/manuali: non affidarsi al monitoraggio
real-time per rilevare i cambiamenti effettuati sull'altro host. Ridurre o
disattivare inizialmente generazione trickplay, estrazione immagini capitoli e
altre analisi pesanti delle librerie remote: possono leggere grandi quantità
di video attraverso la tua connessione.

Esaminare **Scheduled Tasks / Attività pianificate**: non eseguire la pulizia
di raccolte e playlist quando le cartelle remote sono indisponibili. La
documentazione Jellyfin avverte che possono perdere riferimenti; rimuovere
anche il trigger di avvio per quella pulizia se presente. Evitare inoltre
scansioni manuali su mount assenti e non eseguire plugin di pulizia/cancellazione
automatica sui contenuti remoti. Questo vale anche per Jellyfin Helper se
l'amico lo ha installato.

Il suo server gestisce l'eventuale transcodifica, ma deve prima leggere il file
originale dalla tua rete. Abbassare la qualità sul suo client non riduce
automaticamente la banda necessaria tra il tuo disco e il suo Jellyfin.

## 11. Collaudo, disconnessioni e riavvii

Fare questi controlli prima di considerare terminata la configurazione:

1. Sul mini PC `exportfs -v` mostra soltanto Film/Serie per l'IP previsto;
   `ss` mostra 2049 sul solo IP Tailscale.
2. Dall'amico funzionano lettura host e lettura container; la scrittura fallisce.
3. I film partono nel suo Jellyfin e continuano a partire nel tuo.
4. Cambiare copertina o segnare un video visto nel suo Jellyfin non cambia il tuo.
5. Importare un nuovo video e verificarne i permessi come `nfsmedia`, poi fare
   una scansione della relativa libreria nel suo Jellyfin.
6. Riavviare l'host dell'amico con il mini PC disponibile e verificare mount
   NFS, servizio systemd e riproduzione.

Se il mini PC è spento al boot dell'amico, il sistema operativo può avviarsi,
ma questo servizio Jellyfin **non parte**, anche se ha altre librerie locali.
È la conseguenza voluta del requisito sui mount, non un guasto da correggere
con un avvio Docker fuori da systemd. Per avere le librerie locali disponibili
anche in quel caso occorre una configurazione diversa o una copia locale.

Quando la connessione ritorna, sull'host dell'amico:

```bash
sudo systemctl start mnt-piserver-Films.mount mnt-piserver-Series.mount
findmnt -t nfs,nfs4 -o TARGET,SOURCE,FSTYPE,OPTIONS
sudo systemctl restart jellyfin-with-piserver.service
```

Se era mancato il disco o l'indirizzo Tailscale del mini PC, prima verificare
il mount e riattivare NFS **sul mini PC**:

```bash
mountpoint /srv/media
tailscale ip -4
sudo systemctl restart nfs-server.service
sudo exportfs -v
```

I riavvii possono causare una breve attesa per il recupero dello stato NFS.
Non pianificare spegnimenti del mini PC mentre l'amico sta guardando un video.

## 12. Diagnostica

| Sintomo | Controllo |
| --- | --- |
| TCP 2049 non raggiungibile | Tailscale connesso, invito accettato, host client user-owned, policy in entrambe le reti, binding NFS e firewall host |
| `access denied by server` al mount | IP client nell'export, percorso esatto e altre esportazioni/pseudoroot NFS già esistenti |
| Lista visibile ma video non leggibile | ACL del file e degli antenati; provare sul mini PC `sudo -u nfsmedia head -c 1 'FILE_REALE'` |
| Nuovi film non visibili | permessi di file importati/hardlink, scansione pianificata Jellyfin; non aspettarsi notifiche NFS remote |
| Host vede file, container vede vuoto | mount avvenuto dopo il bind; montare prima e riavviare il servizio che ricrea Jellyfin |
| Servizio systemd attivo, Jellyfin non risponde | controllare `docker compose ps` e log: `RemainAfterExit` non è un health check dell'app |
| Riproduzione lenta o a scatti | bitrate originale, upload del mini PC, download dell'amico, percorso diretto/relay Tailscale e transcodifica sul suo host |
| Letture ferme dopo perdita rete | comportamento del mount `hard`; ripristinare server/rete e controllare i log, senza assumere un timeout di 30 secondi |

Sul mini PC:

```bash
sudo journalctl -u nfs-server.service -b --no-pager -n 100
sudo exportfs -v
```

Sull'host dell'amico:

```bash
sudo journalctl -u jellyfin-with-piserver.service -b --no-pager -n 100
nfsstat -m
cd /opt/jellyfin
docker compose -f compose.yaml logs --tail=100 jellyfin
```

`showmount -e` usa servizi legati a NFSv3/mountd e non è il test decisivo per un
server limitato a NFSv4.1+. Non aprire porte aggiuntive solo per farlo funzionare.

## 13. Backup e revoca

Conservare in modo protetto i file di configurazione host creati dalla guida
(`/etc/exports.d/piserver-friend.exports`, il drop-in NFS, il drop-in systemd,
fstab e il Compose/unità dell'amico), gli UID/GID di `nfsmedia` e gli ACL.
Non presumere che il backup applicativo di PiServer includa automaticamente
questi nuovi file sotto `/etc`. La condivisione NFS non è un backup dei video.

Per interrompere l'accesso, revocare subito la condivisione nella console
Tailscale e rimuovere il grant dedicato. Sul mini PC, se quel file contiene
ancora soltanto i due export di questa guida:

```bash
sudo rm /etc/exports.d/piserver-friend.exports
sudo exportfs -ra
sudo exportfs -v
```

Se NFS era usato soltanto per questo amico, si può anche fermare e disabilitare
`nfs-server.service`. La revoca può lasciare in attesa letture già attive sul
client: concordare lo stop di Jellyfin prima della manutenzione ordinaria.
I video non vengono cancellati.

Per eliminare l'integrazione dal client, fermare/disabilitare il servizio
dedicato, togliere le librerie e i bind NFS dal suo Jellyfin/Compose, smontare i
due percorsi quando non più usati e rimuovere le sole due righe aggiunte a fstab.
Poi ripristinare il gestore d'avvio precedente di Jellyfin. Non usare
`docker compose down -v`: non serve e potrebbe cancellare volumi persistenti.

I backup ACL permettono un ripristino con `setfacl --restore=FILE`, ma riportano
ai permessi della fotografia iniziale anche file modificati nel frattempo:
revisionarli prima, senza applicarli automaticamente a distanza di mesi.

Se in futuro volete condividere anche i suoi film verso di te, ripetere i
ruoli con export, grant e invito Tailscale nella direzione opposta; una sola
condivisione della tua macchina non dà automaticamente accesso al suo disco.

## Riferimenti

- [PiServer: storage](storage.md), [configurazione Jellyfin](service-setup.md#jellyfin)
  e [sicurezza](security.md).
- [Tailscale: machine sharing](https://tailscale.com/docs/features/sharing) e
  [sintassi grants](https://tailscale.com/docs/reference/syntax/grants).
- [Linux NFS: exports](https://man7.org/linux/man-pages/man5/exports.5.html),
  [nfs.conf](https://man7.org/linux/man-pages/man5/nfs.conf.5.html),
  [rpc.nfsd](https://man7.org/linux/man-pages/man8/rpc.nfsd.8.html) e
  [opzioni mount NFS](https://man7.org/linux/man-pages/man5/nfs.5.html).
- [Docker Compose: servizi e bind mounts](https://docs.docker.com/reference/compose-file/services/).
- [Docker: policy di riavvio](https://docs.docker.com/engine/containers/start-containers-automatically/).
- [systemd: mount](https://man7.org/linux/man-pages/man5/systemd.mount.5.html).
- [Jellyfin: storage](https://jellyfin.org/docs/general/administration/storage/),
  [attività pianificate](https://jellyfin.org/docs/general/server/tasks/) e
  [limiti del monitoraggio NFS](https://jellyfin.org/docs/general/administration/troubleshooting/).

Procedura documentale verificata contro la repo e i manuali upstream il
16 ottobre 2026; da collaudare sui due host con i vostri IP e percorsi reali.
