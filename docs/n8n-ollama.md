# n8n, PostgreSQL e Ollama locale

Lo stack opzionale è pensato per il mini PC Debian amd64 con 16 GB di RAM e
i5-7500. `automation-stack.service` avvia:

- **n8n**: editor e scheduler dei workflow;
- **n8n-postgres**: workflow, esecuzioni e credenziali cifrate;
- **Ollama**: inferenza locale raggiungibile soltanto da n8n.

Non viene usata una GPU. Iniziare con modelli quantizzati 3B; modelli grandi e
workflow simultanei saturerebbero rapidamente CPU e RAM.

## 1. Accesso privato e webhook opzionale

L'editor usa il FQDN MagicDNS del mini PC ed è disponibile soltanto attraverso
Tailscale sulla porta 8449. Soltanto l'eventuale webhook ha un dominio
pubblico:

```dotenv
N8N_WEBHOOK_DOMAIN=hooks.invalid
```

Non sostituire `hooks.invalid` e non aggiungere una route Cloudflare finché un
workflow non richiede realmente chiamate esterne.

## 2. Segreti

Generare due valori unici:

```bash
openssl rand -base64 48   # N8N_DB_PASSWORD
openssl rand -hex 32      # N8N_ENCRYPTION_KEY
```

Salvarli in `.env` e nel password manager. `N8N_ENCRYPTION_KEY` è permanente:
sostituirla rende illeggibili le credenziali già presenti in PostgreSQL.

## 3. Configurare Tailscale Serve

`scripts/configure-tailscale-serve.sh` pubblica il loopback locale di n8n su:

```text
https://TAILSCALE_FQDN:8449/
```

Non creare un hostname Cloudflare per l'editor e non inoltrare le porte 5678,
11434 o 5432.

## 4. Avvio automatico

Validare e abilitare l'unità systemd:

```bash
cd /opt/raspberry-server
docker compose -f compose.yaml -f compose.automation.yaml config --quiet
sudo systemctl enable --now automation-stack.service
sudo systemctl status automation-stack.service --no-pager
```

Aprire `https://TAILSCALE_FQDN:8449/` e creare il primo account owner.

## 5. Modello locale

Scaricare un modello piccolo:

```bash
docker compose -f compose.yaml -f compose.automation.yaml exec ollama \
  ollama pull qwen2.5:3b
```

In n8n creare una credenziale Ollama con URL `http://ollama:11434`.
`localhost` indicherebbe invece il container n8n.

## 6. Restic

Eseguire e ispezionare un backup:

```bash
sudo bash scripts/backup.sh
sudo bash -c '
  set -a
  source /etc/raspberry-server/backup.env
  set +a
  restic snapshots --latest 5
'
```

Il backup ferma brevemente n8n, crea `n8n.sql`, salva la directory impostazioni
e riavvia il servizio. I modelli Ollama non vengono salvati.

## Webhook pubblici

Prima di creare un webhook esterno, aggiungere l'hostname `hooks` al tunnel
Cloudflare. Richiedere sempre firma HMAC o segreto e non esporre mai l'editor.
