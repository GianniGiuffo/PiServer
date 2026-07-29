# n8n, PostgreSQL e Ollama locale

Lo stack opzionale è pensato per il mini PC Debian amd64 con 16 GB di RAM e
i5-7500. `automation-stack.service` avvia:

- **n8n**: editor e scheduler dei workflow;
- **n8n-postgres**: workflow, esecuzioni e credenziali cifrate;
- **Ollama**: inferenza locale raggiungibile soltanto da n8n.

Non viene usata una GPU. Iniziare con modelli quantizzati 3B; modelli grandi e
workflow simultanei saturerebbero rapidamente CPU e RAM.

Ollama non pubblica porte sull'host. Usa una seconda rete Docker senza servizi
collegati soltanto per le connessioni uscenti necessarie a scaricare un modello;
n8n continua a raggiungerlo esclusivamente sulla rete interna `automation`.

## 1. Accesso privato e chat

L'editor e gli endpoint di produzione, incluso il Chat Trigger, usano il FQDN
MagicDNS del mini PC e sono disponibili soltanto attraverso Tailscale sulla
porta 8449:

```dotenv
TAILSCALE_FQDN=mini-pc.example-tailnet.ts.net
N8N_WEBHOOK_DOMAIN=mini-pc.example-tailnet.ts.net
N8N_CHAT_PATH=/webhook/replace-with-the-production-chat-path
OLLAMA_MODEL=qwen2.5:3b
```

`N8N_WEBHOOK_DOMAIN` deve essere uguale a `TAILSCALE_FQDN`. Non aggiungere una
route Cloudflare per n8n: editor, webhook e chat restano Tailnet-only.

Dopo aver aggiornato `.env`, ricreare i servizi che ricevono queste variabili:

```bash
docker compose -f compose.yaml -f compose.automation.yaml up -d ollama n8n
docker compose up -d caddy homepage
```

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

## 6. Pubblicare la chat nella Tailnet

Creare e provare un workflow con `Chat Trigger`, `AI Agent`,
`Ollama Chat Model` e una memoria. Nel Chat Trigger:

1. attivare **Make Chat Publicly Available**;
2. scegliere **Hosted Chat**;
3. attivare il workflow;
4. copiare la **Production Chat URL**.

La URL deve iniziare con:

```text
https://TAILSCALE_FQDN:8449/
```

Copiare in `.env` soltanto la parte che inizia con `/`, per esempio:

```dotenv
N8N_CHAT_PATH=/webhook/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

Non inventare il percorso: usare esattamente quello mostrato dal Chat Trigger.
Ricreare Homepage per applicare il nuovo pulsante:

```bash
docker compose up -d homepage
```

La card **Modello AI** apre la chat. Le card **Ollama** e **Modello AI**
riportano entrambe esclusivamente l'health Docker del container Ollama; non
eseguono un controllo HTTP e la card del modello non verifica che esso sia
caricato in memoria.

## 7. Restic

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

## Webhook

Gli URL generati da n8n sono privati e raggiungibili soltanto dalla Tailnet.
Una futura esposizione pubblica richiede una progettazione separata con
hostname dedicato, autenticazione e regole Cloudflare; non riutilizzare
automaticamente l'endpoint della chat privata.
