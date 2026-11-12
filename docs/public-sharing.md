# Nextcloud pubblico e condivisioni Navidrome

Una volta attivato, [cloud.tommasofrancescon.it](https://cloud.tommasofrancescon.it)
usa gli account, la 2FA e i permessi Nextcloud esistenti. Gli ospiti possono
aprire i link di condivisione senza VPN e senza account.

```text
Internet → HTTPS Cloudflare → tunnel in uscita → Caddy → Nextcloud
Tailnet → Tailscale Serve :8445 → Caddy → Nextcloud
```

Il tunnel funziona anche con CGNAT. Le porte host `8082` (Nextcloud), `18084`
(proxy Tailnet) e `8088` (ONLYOFFICE) restano su loopback. Nessun port
forwarding, UPnP o Funnel.

## Prima di pubblicare

1. Verificare backup di configurazione e database, patch di sicurezza di
   Nextcloud e delle app, e accesso amministrativo via Tailnet. Accertarsi che
   le nuove reti Docker `10.203.253.0/29` e `10.203.253.8/29` non si
   sovrappongano alla LAN, alle VPN o ad altre reti Docker.
2. Lasciare disattivata l'app **Registration**. L'amministratore crea gli
   account dalla pagina **Utenti** di Nextcloud. Configurare la
   [2FA di Nextcloud](https://docs.nextcloud.com/server/stable/admin_manual/configuration_user/two_factor-auth.html)
   per gli account, a partire da tutti gli amministratori, salvare i codici
   di recupero e provare secondo fattore e client ufficiali prima di rendere
   la 2FA obbligatoria in **Impostazioni di amministrazione → Sicurezza**.
   Controllare le esclusioni brute-force: non escludere il proxy o reti
   pubbliche. Usare un account non amministratore ogni giorno.
3. Nel tunnel Cloudflare esistente verificare la route **Published application**
   per `cloud.tommasofrancescon.it` verso `http://caddy:80`, conservando l'header
   Host. Se manca, seguire [la guida al tunnel](cloudflare-tunnel.md). Non puntare
   il DNS all'IP del mini PC. Non mettere Cloudflare Access davanti all'intero
   hostname: anche gli ospiti devono poter aprire i link. Conservare
   `CF-Connecting-IP` ed evitare Worker o trasformazioni che alterano l'IP client.
4. Caddy forza HTTPS per il solo hostname Nextcloud e invia `no-store` anche
   a Cloudflare. Se la zona ha regole che impongono la cache, escludere
   `cloud.tommasofrancescon.it` con [Bypass cache](https://developers.cloudflare.com/cache/how-to/cache-rules/create-dashboard/).
   Mantenere le protezioni WAF del piano e verificare che app e WebDAV non
   ricevano challenge interattive.

## Applicare sul mini PC

Con il flag spento, durante il passaggio i link pubblici Nextcloud rispondono
temporaneamente 404. Pianificare una finestra breve. I token non cambiano.

Nel checkout aggiornato, mantenere nel file locale `.env`:

```dotenv
NEXTCLOUD_PUBLIC_DOMAIN=cloud.tommasofrancescon.it
NEXTCLOUD_PUBLIC_ENABLED=false
```

Su uno stack già avviato, applicare soltanto ai container interessati. Su una
nuova installazione avviare prima core e media seguendo [il setup](service-setup.md#nextcloud).

```bash
cd /opt/raspberry-server
bash scripts/preflight.sh
bash scripts/check-media-mount.sh
docker compose up -d --no-deps --pull never caddy cloudflared
docker compose -f compose.yaml -f compose.media.yaml up -d --no-deps --pull never nextcloud
bash scripts/configure-public-sharing.sh
```

Lo script verifica Caddy e le impostazioni effettive del proxy, aggiunge gli
hostname mancanti e imposta l'URL pubblico per job e notifiche. Disattiva
`public_share_domain` e `registration` se attive. Conserva account, token,
password e scadenze dei link.
Gli upload anonimi restano disabilitati. ONLYOFFICE conserva il JWT e le
callback su Docker; `/office/` ammette solo le route necessarie al browser.

Verificare login via Tailnet e stato del tunnel. Quando tutti i controlli
preliminari sono pronti, impostare `NEXTCLOUD_PUBLIC_ENABLED=true` in `.env`
e ricreare Caddy affinché legga il nuovo ambiente:

```bash
docker compose up -d --no-deps --pull never caddy
python3 scripts/verify-public-office.py cloud.tommasofrancescon.it
```

## Condividere e verificare

Accedere su `https://cloud.tommasofrancescon.it` e usare **Condividi → Crea
link pubblico → Copia**. Nextcloud genera il link sul dominio aperto nel
browser: copiare dalla UI pubblica per i destinatari esterni. I link già
emessi sotto `https://cloud.tommasofrancescon.it/s/…` conservano token e
permessi. Per i file riservati usare password e scadenza e inviare la password
separatamente. Revocare i link che non servono più.

Da rete mobile, con Wi-Fi e Tailscale spenti:

1. Verificare redirect HTTP → HTTPS, login, secondo fattore e logout con un
   account di prova. In anonimo i file personali richiedono autenticazione.
   Collegare un client ufficiale e sincronizzare un file di prova.
2. Aprire un link preesistente e uno nuovo in una finestra anonima. Provare
   download, password errata e revoca. Se si usa ONLYOFFICE, verificare
   modifica e salvataggio di un documento sintetico.
3. Controllare che non compaia `CF-Cache-Status: HIT`. Con un solo login
   volutamente errato di prova verificare che Nextcloud veda l'IP esterno:
   sul server usare `occ security:bruteforce:attempts IP_DEL_CLIENT`.
4. Verificare di nuovo la Tailnet su `:8445`, i bind su loopback e l'assenza
   di nuove regole NAT/UPnP.

Lo script automatico controlla login, autenticazione WebDAV e perimetro
dell'editor. Se Cloudflare presenta una challenge, controllare l'evento WAF
e ripetere da un browser, senza disattivare le protezioni globali.

Cloudflare applica un [limite per singola richiesta](https://developers.cloudflare.com/cache/concepts/default-cache-behavior/#upload-limits)
(100 MB su Free e Pro). Usare client con caricamento a blocchi; per richieste
WebDAV singole più grandi usare la Tailnet.

Per chiudere l'accesso pubblico, reimpostare `NEXTCLOUD_PUBLIC_ENABLED=false`
e ricreare Caddy. I link pubblici vengono sospesi; la Tailnet e le risorse
browser dell'editor restano disponibili. Per tornare alla modalità precedente
con soli link pubblici, ripristinare la versione precedente di Caddy e
Compose, ricreare i container interessati e riabilitare l'app
`public_share_domain` se era in uso. Non serve ripristinare il database.

## Navidrome

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

Da rete esterna verificare riproduzione, download (se abilitato) e revoca.
La radice di `music.tommasofrancescon.it` continua a rispondere 404.
La porta host `4533` resta su loopback.
