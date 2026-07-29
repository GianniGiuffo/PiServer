# Pubblicare sito e Vaultwarden con Cloudflare Tunnel

Il percorso HTTPS pubblico è:

```text
Browser (HTTPS) -> Cloudflare -> encrypted outbound tunnel -> cloudflared -> Caddy -> site or Vaultwarden
```

Funziona con CGNAT perché il mini PC apre una connessione uscente verso
Cloudflare. Non inoltrare porte nel router.

## 1. Portare il DNS del dominio su Cloudflare

1. Accedere a Cloudflare e scegliere **Add a domain**.
2. Inserire `tommasofrancescon.it`.
3. Confrontare i record rilevati e conservare tutti quelli necessari per posta
   e verifiche: in particolare `MX`, `TXT`, SPF, DKIM e DMARC.
4. Presso il registrar sostituire i nameserver autorevoli con quelli indicati
   da Cloudflare.
5. Attendere che la zona risulti **Active**. Non cancellare i record della
   posta.

I record del tunnel verranno creati in seguito. Non puntare record pubblici
all'indirizzo Tailscale o a un indirizzo CGNAT.

## 2. Configurare il tunnel gestito

1. Aprire **Networking** > **Tunnels** > **Create a tunnel**.
2. Riutilizzare il tunnel esistente durante la migrazione oppure crearne uno
   chiamato `pi-server`.
3. Nella schermata di installazione scegliere **Docker** e copiare soltanto il
   token dopo `--token`. Non eseguire il comando mostrato: il connettore è già
   incluso nel Compose.
4. Sul mini PC modificare il file locale:

```bash
cd /opt/raspberry-server
nano .env
```

5. Inserire il token tra apici:

```dotenv
CLOUDFLARE_TUNNEL_TOKEN='paste-the-entire-token-here'
```

6. Avviare o ricreare lo stack e controllare il connettore:

```bash
docker compose up -d
docker compose ps cloudflared caddy
docker compose logs --tail=100 cloudflared
```

Attendere che Cloudflare mostri il connettore come **Healthy**.

## 3. Hostname pubblici

In Cloudflare aprire **Networking** > **Tunnels** > `pi-server` > **Routes** >
**Add route** > **Published application**. Aggiungere le route seguenti. In
entrambi i casi selezionare **HTTP** e usare esattamente `http://caddy:80` come
URL del servizio. `caddy` è il nome interno Docker; non usare `localhost`.

| Public hostname | Service URL |
| --- | --- |
| `tommasofrancescon.it` | `http://caddy:80` |
| `vault.tommasofrancescon.it` | `http://caddy:80` |

Un eventuale secondo sito è opzionale: va aggiunta una terza route soltanto
dopo aver impostato `SITE_2_DOMAIN`. Non pubblicare Homepage, Nextcloud, Immich,
Jellyfin, Pi-hole, Uptime Kuma, l'editor n8n o la chat n8n. Gli endpoint n8n
restano raggiungibili esclusivamente tramite Tailscale.

## 4. Verificare il percorso pubblico

Con il Wi-Fi disattivato su un telefono aprire:

- `https://tommasofrancescon.it`
- `https://vault.tommasofrancescon.it`

Il sito restituisce una risposta 404 di Caddy finché non è configurato il
deploy statico. Questo conferma comunque il funzionamento del tunnel; poi va
configurato `site-1` e, solo se serve, `site-2`.

Per questa migrazione Vaultwarden deve mostrare il vault già ripristinato:
accedere con un account esistente e verificare almeno un elemento. Se appare
una nuova installazione vuota, fermarsi, non importare né creare account e
seguire il rollback in `docs/minipc-migration.md`. Lasciare sempre
`VAULTWARDEN_SIGNUPS_ALLOWED=false`.

## Note di sicurezza

- Il browser usa HTTPS, il tunnel è cifrato e Caddy è raggiungibile soltanto
  dalla rete Docker privata.
- Non salvare il token del tunnel in GitHub. `.env` è ignorato da Git e viene
  incluso nel backup Restic cifrato.
- Non proteggere Vaultwarden con una regola di login browser Cloudflare Access:
  i client Bitwarden devono raggiungerlo direttamente. Usare password master
  robusta e autenticazione a due fattori.
