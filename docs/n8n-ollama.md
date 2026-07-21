# n8n, PostgreSQL and local Ollama on the mini PC

This optional stack is for the Debian amd64 mini PC with 16 GB RAM and the
Intel i5-7500. It is **not** started by the normal `docker compose up -d` used
on the Raspberry Pi. The three services are declared in
`compose.automation.yaml`:

- **n8n**: the workflow editor and scheduler;
- **n8n-postgres**: workflows, executions and encrypted credentials;
- **Ollama**: local language-model inference, reachable only by n8n on a
  private Docker network.

The stack uses no GPU. Start with small 3B-4B models for classification,
extraction, summarisation and simple assistants. Large models, image generation
and several simultaneous AI workflows will make this four-core CPU feel slow.

## 1. Choose the two names before publishing anything

Use two distinct subdomains, for example:

```dotenv
N8N_DOMAIN=n8n.tommasofrancescon.it
N8N_WEBHOOK_DOMAIN=hooks.tommasofrancescon.it
```

`N8N_DOMAIN` is the private editor that you open in a browser. It will be
protected by Cloudflare Access. `N8N_WEBHOOK_DOMAIN` must remain separate: do
not add it to Cloudflare or the tunnel until a workflow needs a public webhook.
This avoids exposing an unnecessary endpoint and avoids an Access login blocking
webhook providers.

## 2. Add the secrets on the mini PC

After copying `.env.example` to `.env`, set the normal stack values and then
create two additional unique values:

```bash
openssl rand -base64 48   # N8N_DB_PASSWORD
openssl rand -hex 32      # N8N_ENCRYPTION_KEY
```

Put the resulting values directly in `.env`, quote a value if it contains
spaces, `#`, or shell-significant characters. Store both in the password
manager. `N8N_ENCRYPTION_KEY` is permanent: n8n uses it to encrypt and decrypt
credentials in PostgreSQL. Replacing it later makes existing credentials
unreadable.

The initial image tags in `.env.example` are deliberately explicit. Review
release notes, take a successful backup, and update the tags intentionally
rather than tracking `latest`.

## 3. Create the remote-access boundary first

In Cloudflare Zero Trust:

1. Create a **self-hosted Access application** for exactly
   `n8n.tommasofrancescon.it` (substitute your `N8N_DOMAIN`).
2. Create an Allow policy for only your personal identity. One-time PIN to the
   address you control is sufficient for the first setup; add a stronger login
   method later if desired.
3. In the existing Tunnel, add a public hostname `n8n.tommasofrancescon.it`
   whose service is `http://caddy:80`. Cloudflare creates the corresponding
   Tunnel DNS record.
4. Do **not** add `hooks.tommasofrancescon.it` yet. When it is required, add it
   as a second public hostname to the same `http://caddy:80` service, but do
   not attach the interactive Access application to that hostname.

Caddy forwards both names to n8n and sets the forwarded HTTPS headers. n8n is
configured with `WEBHOOK_URL` and `N8N_PROXY_HOPS=1`, which are required when
it runs behind a reverse proxy. See the [n8n reverse-proxy guidance](https://docs.n8n.io/hosting/configuration/configuration-examples/webhook-url/).

No router port forward is needed. Never expose Ollama, PostgreSQL or n8n port
5678 directly.

## 4. Validate and start the optional stack

Run these commands on the mini PC from the repository directory:

```bash
cd /opt/raspberry-server
docker compose -f compose.yaml -f compose.automation.yaml config --quiet
docker compose -f compose.yaml -f compose.automation.yaml pull
docker compose -f compose.yaml -f compose.automation.yaml up -d
docker compose -f compose.yaml -f compose.automation.yaml ps
```

All three services have `restart: unless-stopped`. Since the bootstrap script
enables Docker, they come back automatically after the mini PC reboots; no
additional systemd unit is needed.

Open `https://n8n.tommasofrancescon.it`, pass Cloudflare Access, and create the
first n8n owner account. Use a separate long password even though Access is in
front of it.

## 5. Use the local model from n8n

Download one small model first:

```bash
docker compose -f compose.yaml -f compose.automation.yaml exec ollama \
  ollama pull qwen2.5:3b
```

In n8n, create an **Ollama** credential with base URL
`http://ollama:11434`. `localhost` would mean the n8n container itself, not the
Ollama container. Then add an Ollama Chat Model node and select the model.
Ollama's n8n guide uses the same local credential concept; the Docker service
name replaces its localhost example. [Ollama n8n documentation](https://docs.ollama.com/integrations/n8n)

## 6. Include it in Restic and verify it

On the mini PC, add this one line to `/etc/raspberry-server/backup.env`:

```dotenv
AUTOMATION_COMPOSE_FILE=/opt/raspberry-server/compose.automation.yaml
```

Then run and inspect a backup:

```bash
sudo bash scripts/backup.sh
sudo RESTIC_REPOSITORY=/mnt/rpi-backup/restic-rpi-server \
  RESTIC_PASSWORD_FILE=/etc/restic/password restic snapshots
```

The backup stops n8n briefly, makes `n8n.sql`, backs up its settings directory,
then starts n8n again. It does not back up Ollama model downloads; pull them
again after a restore. Keep the `.env` file and its `N8N_ENCRYPTION_KEY` in the
same Restic snapshot as `n8n.sql`.

## Public webhooks later

Before creating an external webhook, add its `hooks` hostname to the Cloudflare
Tunnel and test a single workflow. For every public webhook, require the
provider's HMAC/signature secret or a randomly generated secret path and reject
unknown requests. Never expose the n8n editor merely to make a webhook work.
