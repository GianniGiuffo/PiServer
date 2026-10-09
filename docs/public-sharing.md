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
sudo bash scripts/configure-tailscale-serve.sh
sudo bash scripts/configure-public-sharing.sh
docker compose -f compose.yaml -f compose.media.yaml ps caddy cloudflared nextcloud navidrome
```

## 2. Nextcloud

Nextcloud accetta sia `TAILSCALE_FQDN` sia `NEXTCLOUD_PUBLIC_DOMAIN`. La UI
completa rimane raggiungibile soltanto su `https://TAILSCALE_FQDN:8445`.
Tailscale Serve inoltra quella porta al bind locale Caddy `18084` (listener
container `8084`). Caddy presenta il dominio pubblico a Nextcloud per l'API
delle condivisioni; l'app locale `public_share_domain` corregge il link copiato
dalla UI, senza esporre il login pubblico.

Non viene forzato `overwritehost`, perché cambierebbe anche URL, redirect e asset
della UI privata. `overwrite.cli.url` definisce il dominio pubblico per email,
job in background e per `public_share_domain`. Nextcloud costruisce il link del
pulsante **Copia** direttamente dall'indirizzo aperto nel browser; l'app modifica
esclusivamente gli URL `/s/<token>` passati agli appunti.

`scripts/configure-public-sharing.sh` rimuove l'eventuale `overwritehost`
persistito, aggiunge il dominio pubblico senza cancellare quelli esistenti,
imposta l'URL CLI pubblico e abilita l'app locale. Per verificare manualmente il
risultato:

```bash
cd /opt/raspberry-server
docker compose -f compose.yaml -f compose.media.yaml exec --user www-data nextcloud \
  php occ config:system:get trusted_domains
docker compose -f compose.yaml -f compose.media.yaml exec --user www-data nextcloud \
  php occ config:system:get overwrite.cli.url
docker compose -f compose.yaml -f compose.media.yaml exec --user www-data nextcloud \
  php occ app:list | grep public_share_domain
```

Creare e copiare il link dalla normale UI privata su
`https://TAILSCALE_FQDN:8445`. Il link restituito deve iniziare con
`https://cloud.tommasofrancescon.it/s/`; non è necessario aprire il dominio
pubblico per accedere come utente.

In **Administration settings > Sharing**:

- consentire i link pubblici;
- lasciare disattivato **Enforce password protection**, così la password resta
  una scelta per ogni link;
- lasciare disattivata la scadenza predefinita/obbligatoria;
- mantenere disabilitati gli upload pubblici; i link ai singoli file possono
  comunque ricevere il permesso di modifica. Questa configurazione non abilita
  caricamenti o modifica nelle condivisioni di cartelle;
- mantenere attiva la protezione brute-force e abilitare la 2FA sugli account.

Per condividere un file o una cartella scegliere **Share > Create a new share
link**. Impostare la password solo quando serve e lasciare vuota la scadenza.
Il token rimane valido finché il link non viene eliminato con **Unshare**.

Il dominio pubblico non inoltra l'applicazione Nextcloud completa. Caddy ammette
soltanto `/s/*`, il DAV pubblico tokenizzato, gli endpoint pubblici di anteprima
e visualizzazione, il connettore ONLYOFFICE per link tokenizzati e le route
limitate dell'editor sotto `/office/`. `/`, `/login`,
`/status.php`, `/remote.php/*` e le API utente non raggiungono Nextcloud e
restituiscono `404`.

### Modifica pubblica di documenti Office sullo stesso dominio

L'editor usa `https://cloud.tommasofrancescon.it/office/`, sullo stesso tunnel e
hostname dei link `/s/<token>`: nessun sottodominio, DNS, porta host o port
forwarding aggiuntivo. Gli ospiti senza Tailscale possono modificare DOCX, XLSX
e PPTX scegliendo **Consenti modifica** sul link al singolo file. Un link di
sola lettura resta tale; revoca, scadenza e password sono gestite da Nextcloud.
La radice `/office/` restituisce intenzionalmente 404: aprire il link al file,
non il servizio come applicazione autonoma.

Caddy inoltra soltanto le risorse statiche dell'editor, i manifest temi/plugin,
le connessioni `doc/<key>/c`, i download dell'editor e la cache con URL firmati.
Per Nextcloud ammette gli asset dell'app custom ONLYOFFICE, la pagina
`/apps/onlyoffice/s/<token>` e l'API di configurazione con `shareToken`.
Nextcloud valida il token, l'appartenenza del file e l'autenticazione della
password prima di emettere la configurazione firmata JWT. Le route private
numeriche `/apps/onlyoffice/<id>` non vengono pubblicate.

`DocumentServerInternalUrl=http://onlyoffice/` e `StorageUrl=http://nextcloud/`
mantengono download e callback di salvataggio nella rete Docker. Il JWT
esistente resta attivo e non viene passato nei comandi o nei log. Caddy rimuove
il prefisso `/office` e imposta `X-Forwarded-Host` con il prefisso, secondo la
[configurazione ufficiale per virtual path](https://github.com/ONLYOFFICE/document-server-proxy/blob/master/nginx/proxy-to-virtual-path.conf).
Il salvataggio aggiorna direttamente il file Nextcloud.

Deploy su un server già configurato, dopo avere salvato Caddyfile,
configurazione Nextcloud e dump del database in una directory privata:

```bash
cd /opt/raspberry-server
git pull --ff-only
docker compose exec -T caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
python3 scripts/configure-onlyoffice.py
python3 scripts/verify-public-office.py
```

Non occorre riavviare Nextcloud o ONLYOFFICE, aggiornare immagini o creare
nuove route nel dashboard Cloudflare. `configure-public-sharing.sh` mantiene
`shareapi_allow_public_upload=no`: non abilita la modifica delle cartelle.
Nessun permesso dei link esistenti viene modificato dal deploy.

La verifica automatica controlla asset pubblici, rifiuto delle route private,
metodi di scrittura esclusi, cache senza firma e richieste senza link valido.
Cloudflare può applicare una challenge ai client non browser; in quel caso
ripetere le verifiche da un browser anonimo senza Tailscale.
Per il collaudo completo aprire file sintetici DOCX/XLSX/PPTX, modificarli,
chiudere l'editor e controllare il contenuto del file salvato. Verificare anche
link di sola lettura, password errata, accesso a un file esterno alla
condivisione e revoca del link. Non usare documenti personali per il collaudo.

Collaudo eseguito il 9 ottobre 2026 dal dominio pubblico in sessioni browser
anonime: DOCX, XLSX, PPTX e Markdown modificati e contenuto salvato verificato
sul server. Verificati inoltre sola lettura, password errata/corretta, file
esterno a una cartella condivisa, token invalido e revoca del link. I file e
i link sintetici vengono eliminati al termine del collaudo. I 14 test di
condivisioni, configurazione Office e recupero del connettore passano su Linux.
La suite generale presenta errori preesistenti nei test media (porta Seerr e
sezioni Homepage non aggiornate) e richiede Node.js per il test Renovate.

Rollback: ricaricare il Caddyfile precedente e ripristinare soltanto
`DocumentServerUrl` al precedente URL Tailnet; nessun file deve essere
ripristinato o cancellato. Il dump di backup è una protezione aggiuntiva,
non va ripristinato globalmente per annullare questa configurazione.

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
3. aprire `https://cloud.tommasofrancescon.it/` e `/login` e verificare `404`;
4. aprire un link Navidrome e verificare riproduzione e, se selezionato,
   download;
5. aprire `https://music.tommasofrancescon.it/` e verificare una risposta 404;
6. revocare entrambi i link e verificare che non siano più utilizzabili.

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
