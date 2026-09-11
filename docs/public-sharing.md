# Condivisioni pubbliche Nextcloud e Navidrome

Questa configurazione pubblica link selezionati attraverso il Cloudflare Tunnel
già esistente. Il mini PC apre soltanto connessioni in uscita: non aggiungere
port forwarding al router e non pubblicare le porte Docker `8082` o `4533`.

Questa guida estende `cloudflare-tunnel.md`: l'indicazione di non pubblicare
Nextcloud e Navidrome resta valida per le loro porte host e per l'interfaccia
Navidrome, mentre le route descritte qui sono le sole eccezioni intenzionali.

Il percorso è:

```text
Internet -> HTTPS Cloudflare -> tunnel in uscita -> Caddy -> applicazione
```

La Tailnet rimane il percorso amministrativo privato. La condivisione pubblica
non concede accesso alla Tailnet e non espone PostgreSQL, Redis, il NAS o le
altre applicazioni.

## 1. Hostname

Nel `.env` locale impostare:

```dotenv
NEXTCLOUD_PUBLIC_DOMAIN=cloud.tommasofrancescon.it
NAVIDROME_PUBLIC_DOMAIN=music.tommasofrancescon.it
```

Nel dashboard Cloudflare aprire **Networking > Tunnels > pi-server > Routes**
e aggiungere due **Published application**:

| Public hostname | Service URL |
| --- | --- |
| `cloud.tommasofrancescon.it` | `http://caddy:80` |
| `music.tommasofrancescon.it` | `http://caddy:80` |

Non usare `localhost`: `cloudflared` e Caddy sono container distinti. Le route
gestite creano anche i record DNS del tunnel; non creare record verso l'IP
pubblico, LAN o Tailscale del mini PC.

Applicare la configurazione sul server. Lo script aggiorna soltanto impostazioni
Nextcloud documentate ed è idempotente; non legge le password dal `.env`:

```bash
cd /opt/raspberry-server
bash scripts/preflight.sh
sudo systemctl restart core-stack.service
sudo systemctl restart media-stack.service
sudo bash scripts/configure-public-sharing.sh
docker compose -f compose.yaml -f compose.media.yaml ps caddy cloudflared nextcloud navidrome
```

## 2. Nextcloud

Nextcloud accetta sia `TAILSCALE_FQDN` sia `NEXTCLOUD_PUBLIC_DOMAIN`. Non viene
forzato `overwritehost`, perché un valore unico romperebbe uno dei due percorsi.
`overwrite.cli.url` usa invece il dominio pubblico per email e URL generati dai
job in background.

`scripts/configure-public-sharing.sh` rimuove l'eventuale `overwritehost`
persistito, aggiunge il dominio pubblico senza cancellare quelli esistenti e
imposta l'URL CLI pubblico. Per verificare manualmente il risultato:

```bash
cd /opt/raspberry-server
docker compose -f compose.yaml -f compose.media.yaml exec --user www-data nextcloud \
  php occ config:system:get trusted_domains
docker compose -f compose.yaml -f compose.media.yaml exec --user www-data nextcloud \
  php occ config:system:get overwrite.cli.url
```

Aprire `https://cloud.tommasofrancescon.it` quando si deve creare e copiare un
link destinato all'esterno. Un link creato mentre si usa l'hostname Tailnet
conterrà quell'hostname; in quel caso sostituire soltanto origine e porta con
`https://cloud.tommasofrancescon.it`, lasciando invariato `/s/TOKEN`.

In **Administration settings > Sharing**:

- consentire i link pubblici;
- lasciare disattivato **Enforce password protection**, così la password resta
  una scelta per ogni link;
- lasciare disattivata la scadenza predefinita/obbligatoria;
- disabilitare gli upload pubblici se servono soltanto visualizzazione e
  download;
- mantenere attiva la protezione brute-force e abilitare la 2FA sugli account.

Per condividere un file o una cartella scegliere **Share > Create a new share
link**. Impostare la password solo quando serve e lasciare vuota la scadenza.
Il token rimane valido finché il link non viene eliminato con **Unshare**.

Il dominio pubblico inoltra l'applicazione Nextcloud completa perché anteprime,
download, autenticazione dei link protetti e risorse statiche usano endpoint
diversi da `/s/`. I dati privati continuano a richiedere l'autenticazione
Nextcloud; la sola conoscenza del dominio non permette di leggerli.

## 3. Navidrome

Il compose abilita le condivisioni, genera URL sotto
`https://music.tommasofrancescon.it/share/...`, usa una scadenza predefinita di
100 anni e lascia il download disattivato per impostazione predefinita. Nella
finestra della singola condivisione si può abilitare **Allow downloads**. La
revoca si effettua eliminando la condivisione in Navidrome.

Caddy accetta pubblicamente soltanto `GET`, `HEAD` e `OPTIONS` su `/share` e
`/share/*`. La pagina di login, l'API Subsonic e l'interfaccia normale restano
raggiungibili esclusivamente dalla Tailnet.

Navidrome 0.63 non offre password per singolo share. Quando una traccia deve
essere protetta da password, condividerne il file tramite Nextcloud. Non mettere
una password HTTP unica davanti all'intero dominio musicale: impedirebbe di
scegliere la protezione con granularità per link e renderebbe uguale la password
di tutte le condivisioni.

La versione 0.63 salva sempre una data di scadenza quando crea un link: il valore
`0` scadrebbe immediatamente. `876000h` (100 anni) è quindi l'equivalente
operativo di “finché non lo disattivo”, senza mantenere una patch privata del
server.

## 4. Verifica da una rete esterna

Con Wi-Fi e Tailscale disattivati sul telefono:

1. aprire un link Nextcloud senza password e verificarne anteprima e download;
2. aprire un secondo link Nextcloud protetto e verificare che una password
   errata venga rifiutata;
3. aprire un link Navidrome e verificare riproduzione e, se selezionato,
   download;
4. aprire `https://music.tommasofrancescon.it/` e verificare una risposta 404;
5. revocare entrambi i link e verificare che non siano più utilizzabili.

Controllare infine che il router non abbia nuove regole NAT/UPnP e che Docker
continui a mostrare `127.0.0.1:8082` e `127.0.0.1:4533` come soli bind host.

## Limiti Cloudflare

Questa soluzione è adatta a condivisioni personali occasionali. I termini dei
servizi Cloudflare possono richiedere prodotti specifici per distribuzione di
video o file grandi sui piani Free, Pro e Business. Non usare il tunnel come
CDN o servizio di streaming pubblico continuativo. Se i trasferimenti diventano
frequenti o molto grandi, usare un piccolo VPS pubblico come reverse proxy,
collegato al mini PC esclusivamente tramite Tailscale; il router domestico
resterebbe comunque chiuso.
