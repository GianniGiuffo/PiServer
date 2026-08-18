# n8n, PostgreSQL e Ollama locale

Lo stack opzionale è pensato per il mini PC Debian amd64 con 16 GB di RAM e
i5-7500. `automation-stack.service` avvia:

- **n8n**: editor e scheduler dei workflow;
- **n8n-postgres**: workflow, esecuzioni e credenziali cifrate;
- **Ollama**: inferenza locale raggiungibile soltanto da n8n.

Non viene usata una GPU. Il modello selezionato è `qwen3.5:4b`, quantizzato
Q4 e grande circa 3,4 GB su disco. Ollama ha un limite massimo di 8 GB,
contesto 4K, una sola richiesta parallela e un solo modello caricato. Il
modello residente occupa normalmente circa 4-5 GB: il limite non è RAM
preallocata.

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
OLLAMA_MODEL=qwen3.5:4b
OLLAMA_CONTEXT_LENGTH=4096
OLLAMA_NUM_PARALLEL=1
OLLAMA_MAX_LOADED_MODELS=1
OLLAMA_KEEP_ALIVE=30m
```

`N8N_WEBHOOK_DOMAIN` deve essere uguale a `TAILSCALE_FQDN`. Non aggiungere una
route Cloudflare per n8n: editor, webhook e chat restano Tailnet-only.

Dopo aver aggiornato `.env`, ricreare i servizi che ricevono queste variabili:

```bash
docker compose -f compose.yaml -f compose.automation.yaml \
  up -d n8n-postgres ollama ollama-model-init n8n
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

All'avvio `ollama-model-init` scarica automaticamente il modello selezionato
prima di avviare n8n. Il download iniziale richiede accesso Internet in uscita
e può impiegare diversi minuti. L'unità systemd usa un timeout iniziale di 30
minuti proprio per consentire questo primo download. Seguire l'avanzamento con:

```bash
docker compose -f compose.yaml -f compose.automation.yaml \
  logs -f ollama-model-init
```

Al termine verificare modello e processo:

```bash
docker compose -f compose.yaml -f compose.automation.yaml exec ollama \
  ollama show qwen3.5:4b
docker compose -f compose.yaml -f compose.automation.yaml exec ollama \
  ollama ps
```

Subito dopo il download `ollama ps` può essere vuoto: il modello viene caricato
in RAM soltanto alla prima richiesta e resta residente per `OLLAMA_KEEP_ALIVE`.

In n8n creare una credenziale Ollama con URL `http://ollama:11434`.
`localhost` indicherebbe invece il container n8n.

Nel nodo **Ollama Chat Model** selezionare `qwen3.5:4b`. Per il primo test
usare temperatura `0.2`-`0.4`; se l'interfaccia espone il controllo del
ragionamento, tenerlo basso o disattivato finché non sono state misurate
latenza e RAM.

Per AI Ops usare i valori più conservativi già presenti nel workflow:
temperatura `0`, thinking disattivato, quattro thread, contesto `4096`, context
batch `1024` e massimo `768` token generati. Il contesto più grande usa più RAM
ma su questo processore aumenta anche la latenza; non è un acceleratore.

Per collegare la ricerca Internet privata e i file Nextcloud in sola lettura,
proseguire con [ai-connectors.md](ai-connectors.md).

Per la diagnosi operativa manuale con piano Qwen e approvazione Telegram,
seguire [n8n-ai-ops-local.md](n8n-ai-ops-local.md). Questo workflow usa l'API
Ollama interna direttamente e non richiede account o credito OpenAI.

## 6. Postgres Chat Memory

La memoria usa lo stesso PostgreSQL già impiegato da n8n. La tabella
`ai_chat_memory` rimane separata dalle tabelle applicative, ma entra nello
stesso dump `n8n.sql`; non serve un secondo container PostgreSQL.

In n8n creare una credenziale **Postgres**:

| Campo | Valore |
| --- | --- |
| Host | `n8n-postgres` |
| Database | `n8n` |
| User | `n8n` |
| Password | valore locale di `N8N_DB_PASSWORD` |
| Port | `5432` |
| SSL | disabilitato |

La connessione resta sulla rete Docker interna `automation`; non pubblicare la
porta 5432.

Nel workflow:

1. eliminare o scollegare **Simple Memory**;
2. aggiungere **Postgres Chat Memory**;
3. selezionare la credenziale appena creata;
4. impostare **Session Key** su **Connected Chat Trigger Node**;
5. impostare **Table Name** su `ai_chat_memory`;
6. impostare **Context Window Length** su `10`;
7. collegare la stessa memoria sia ad **AI Agent** sia a **Chat Trigger**;
8. nel Chat Trigger impostare **Load Previous Session** su **From Memory**.

Usare una sola istanza di memoria condivisa tra Chat Trigger e Agent. Dopo una
conversazione di prova verificare la tabella:

```bash
docker compose -f compose.yaml -f compose.automation.yaml exec -T \
  n8n-postgres psql -U n8n -d n8n -c '\dt ai_chat_memory'
```

La pulizia delle esecuzioni n8n non elimina questa tabella: le conversazioni
restano finché non vengono cancellate esplicitamente dal workflow o dal
database.

## 7. Pubblicare la chat nella Tailnet

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

## 8. Restic

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

Il backup ferma brevemente n8n, crea `n8n.sql` includendo
`ai_chat_memory`, salva la directory impostazioni e riavvia il servizio. I
modelli Ollama non vengono salvati e vengono riscaricati automaticamente da
`ollama-model-init` dopo un ripristino.

## Webhook

Gli URL generati da n8n sono privati e raggiungibili soltanto dalla Tailnet.
Una futura esposizione pubblica richiede una progettazione separata con
hostname dedicato, autenticazione e regole Cloudflare; non riutilizzare
automaticamente l'endpoint della chat privata.
