# Publish sites and Vaultwarden through Cloudflare Tunnel

This is the public HTTPS path for this server:

```text
Browser (HTTPS) -> Cloudflare -> encrypted outbound tunnel -> cloudflared -> Caddy -> site or Vaultwarden
```

It works with CGNAT because the Raspberry Pi makes an outbound connection to Cloudflare. Do not open or forward ports `80`, `443`, `53`, `22`, `5432` or `6379` in the router.

## 1. Move the domain DNS to Cloudflare

1. Create or sign in to a Cloudflare account and choose **Add a domain**.
2. Enter `tommasofrancescon.it` and select the Free plan if it meets your needs.
3. Cloudflare scans the current DNS records. Before changing anything, compare and copy every record needed for email or verification: especially `MX`, `TXT`, SPF, DKIM and DMARC records.
4. At the company where you bought the domain, replace the existing authoritative nameservers with the two nameservers Cloudflare gives you.
5. Wait until the Cloudflare dashboard reports the zone as **Active**. Do not delete existing mail-related records.

Cloudflare will create the tunnel DNS records in a later step. Do not point records at the CGNAT address `100.65.132.6`.

## 2. Create a managed tunnel

1. In Cloudflare, open **Networking** > **Tunnels** > **Create a tunnel**.
2. Choose **Cloudflared**, name it `pi-server`, and create it.
3. On the connector-install screen choose **Docker** and copy only the long token after `--token`. Do not run Cloudflare's displayed Docker command: the Compose stack already contains the connector.
4. On the Pi, edit the local secret file:

```bash
cd /opt/raspberry-server
nano .env
```

5. Add the token as a single quoted value:

```dotenv
CLOUDFLARE_TUNNEL_TOKEN='paste-the-entire-token-here'
```

6. Start/recreate the stack and check the connector:

```bash
docker compose up -d
docker compose ps cloudflared caddy
docker compose logs --tail=100 cloudflared
```

Wait until Cloudflare marks the connector **Healthy**.

## 3. Add the three public hostname routes

In Cloudflare, open **Networking** > **Tunnels** > `pi-server` > **Routes** > **Add route** > **Published application**. Add each of the following routes. In every case select **HTTP** and use exactly `http://caddy:80` as the service URL. `caddy` is the internal Docker service name; do not use `localhost`.

| Public hostname | Service URL |
| --- | --- |
| `tommasofrancescon.it` | `http://caddy:80` |
| `vault.tommasofrancescon.it` | `http://caddy:80` |
| `secondo.tommasofrancescon.it` | `http://caddy:80` |

Cloudflare automatically creates the DNS records pointing at the tunnel. You may choose another name instead of `secondo`, but it must match `SITE_2_DOMAIN` in `.env` and the Caddy configuration.

## 4. Verify the public edge

With Wi-Fi disabled on a phone, open:

- `https://tommasofrancescon.it`
- `https://vault.tommasofrancescon.it`

The site will return a Caddy 404 response until the static-site deployment is configured. That confirms the public tunnel is working; the next task is to configure `site-1` and `site-2` from their GitHub repositories.

Vaultwarden should show its initial registration page. Create the first account, enable two-factor authentication, then change `VAULTWARDEN_SIGNUPS_ALLOWED=false` in `.env` and run `docker compose up -d vaultwarden`.

## Security notes

- Keep Cloudflare's SSL/TLS mode on **Full** or **Full (strict)**. The browser-to-Cloudflare connection is HTTPS; the tunnel itself is encrypted and Caddy is only reachable on the private Docker network.
- Do not put the tunnel token in GitHub. `.env` is ignored by Git and the encrypted Restic backup includes it.
- Do not protect Vaultwarden with a Cloudflare Access browser-login rule: native Bitwarden clients must reach Vaultwarden directly. The Vaultwarden account, master password and two-factor authentication protect the vault.
