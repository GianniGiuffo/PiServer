# AI Ops locale con n8n, Qwen e approvazione Telegram

Questa procedura realizza un primo workflow manuale e prudente:

1. l'amministratore invia al bot Telegram `/fix descrizione del problema`;
2. il server raccoglie soltanto la diagnostica ammessa;
3. n8n interroga `qwen3.5:4b` tramite Ollama locale;
4. il bot invia diagnosi, evidenze, azioni, rischi e verifica prevista;
5. nessuna azione parte finché l'utente autorizzato non preme **Conferma**;
6. un gateway host valida nuovamente il piano e avvia solo operazioni in
   allowlist; infine il bot comunica l'esito.

Non servono account, chiavi o credito OpenAI. Prompt, snapshot e inferenza
restano sul server. Telegram riceve necessariamente il comando e i rapporti
che il bot deve mostrare: non inserire comunque password, token o dati privati.

## Confini della prima versione

Qwen non riceve una shell, il socket Docker, `.env`, log applicativi, database,
file Nextcloud o directory media. Può vedere soltanto:

- stato di unità systemd espressamente elencate;
- stato e health dei container Compose;
- `git status --short`;
- spazio del filesystem della repo;
- porzioni limitate dei file infrastrutturali versionati elencati nella policy.

Le sole azioni eseguibili sono:

- riavvio di una unità systemd ammessa;
- riavvio di un servizio Compose ammesso;
- preflight della configurazione;
- avvio della procedura già esistente `media-recovery.service`.

La policy effettiva è
[`config/ai-ops/policy.json`](../config/ai-ops/policy.json). Il gateway rifiuta
target inventati, campi aggiuntivi, shell, patch, percorsi di file e più di tre
azioni per piano. Anche un output errato o malevolo del modello non supera
questo controllo. Le modifiche arbitrarie ai file sono intenzionalmente fuori
scope per `qwen3.5:4b`: potranno essere aggiunte in seguito soltanto come azioni
predefinite e testate, non come comandi generati liberamente.

I piani scadono dopo 15 minuti, sono monouso e vengono registrati con mode
`0600` in `/var/lib/raspberry-server/ai-ops`.

## Architettura

- `ai-ops-gateway.service` gira sull'host come root e ascolta soltanto il socket
  Unix `/run/piserver-ai-ops/gateway.sock`;
- `ai-ops-bridge` è un container non privilegiato sulla rete Docker interna
  `ai-ops` e inoltra al socket esclusivamente le richieste di n8n;
- `ai-ops-telegram` usa long polling in uscita: nessun webhook Telegram viene
  pubblicato su Internet;
- solo `ai-ops-telegram` possiede la credenziale che marca un piano come
  approvato; n8n non può auto-approvare il proprio piano;
- n8n raggiunge Ollama su `http://ollama:11434`; Ollama non pubblica la porta
  `11434` sull'host.

I tre segreti hanno ruoli separati:

| File root-managed | Utilizzo |
| --- | --- |
| `/etc/raspberry-server/ai-ops-token` | n8n → gateway |
| `/etc/raspberry-server/ai-ops-approval-token` | poller Telegram → approvazione gateway |
| `/etc/raspberry-server/ai-ops-telegram-bridge-token` | n8n → invio messaggi Telegram |
| `/etc/raspberry-server/ai-ops-telegram-bot-token` | poller → API ufficiale Telegram |

`install-systemd.sh` genera e conserva automaticamente i primi tre. Il token
BotFather deve essere inserito manualmente e non deve mai entrare in Git.

## 1. Aggiornare la repo e l'ambiente

Sul server:

```bash
cd /opt/raspberry-server
git pull --ff-only
nano .env
```

Assicurarsi che `.env` contenga, oltre ai valori già presenti:

```dotenv
AI_OPS_TELEGRAM_CHAT_ID=123456789
AI_OPS_TELEGRAM_USER_ID=123456789
OLLAMA_MODEL=qwen3.5:4b
OLLAMA_CONTEXT_LENGTH=8192
OLLAMA_NUM_PARALLEL=1
OLLAMA_MAX_LOADED_MODELS=1
OLLAMA_KEEP_ALIVE=5m
```

Se gli ID Telegram non sono ancora noti, lasciare temporaneamente i valori di
esempio e completarli al punto 4 prima di avviare il poller.

Creare la directory di stato, reinstallare le unità e generare i segreti:

```bash
sudo install -d -m 0750 -o 1000 -g 1000 \
  /srv/raspberry-server/data/n8n/ai-ops-telegram
sudo bash scripts/install-systemd.sh "$USER" "$(id -gn)"
sudo systemctl status ai-ops-gateway.service --no-pager
```

## 2. Scaricare Qwen e rimuovere il vecchio modello

Avviare lo stack senza avere ancora creato il file del bot. In questo modo
partono n8n, Ollama e il bridge, mentre il poller Telegram viene saltato:

```bash
sudo systemctl restart automation-stack.service
docker compose -f compose.yaml -f compose.automation.yaml \
  logs -f ollama-model-init
```

Quando il pull è terminato, interrompere soltanto la visualizzazione dei log
con `Ctrl+C` e verificare prima il nuovo modello:

```bash
docker compose -f compose.yaml -f compose.automation.yaml exec ollama \
  ollama list
docker compose -f compose.yaml -f compose.automation.yaml exec ollama \
  ollama show qwen3.5:4b
```

Solo dopo questa verifica rimuovere il vecchio modello:

```bash
docker compose -f compose.yaml -f compose.automation.yaml exec ollama \
  ollama rm qwen2.5:3b
docker compose -f compose.yaml -f compose.automation.yaml exec ollama \
  ollama list
```

Se `ollama list` mostra un nome diverso, usare esattamente quel nome al posto
di `qwen2.5:3b`. La rimozione libera solo i layer non condivisi; non elimina la
configurazione di n8n.

## 3. Creare le due credenziali n8n

Aprire n8n dalla Tailnet e creare due credenziali **Header Auth**.

Prima credenziale:

| Campo | Valore |
| --- | --- |
| Name | `PiServer AI Ops Gateway` |
| Header Name | `Authorization` |
| Header Value | `Bearer <contenuto di /etc/raspberry-server/ai-ops-token>` |

Seconda credenziale:

| Campo | Valore |
| --- | --- |
| Name | `PiServer AI Ops Telegram Bridge` |
| Header Name | `Authorization` |
| Header Value | `Bearer <contenuto di /etc/raspberry-server/ai-ops-telegram-bridge-token>` |

Leggere i valori uno alla volta senza copiarli in file della repo:

```bash
sudo cat /etc/raspberry-server/ai-ops-token
sudo cat /etc/raspberry-server/ai-ops-telegram-bridge-token
```

Non creare una credenziale Ollama o OpenAI per questo workflow: la chiamata a
Ollama resta sulla rete Docker interna.

## 4. Creare il bot e ricavare gli ID

In Telegram aprire la chat verificata di **@BotFather**:

1. inviare `/newbot`;
2. scegliere nome e username;
3. copiare il token ricevuto;
4. aprire la chat del nuovo bot e premere **Start**, poi inviare un messaggio.

Sul server creare il file segreto:

```bash
sudo install -m 0640 -o root -g "$(id -gn)" /dev/null \
  /etc/raspberry-server/ai-ops-telegram-bot-token
sudo nano /etc/raspberry-server/ai-ops-telegram-bot-token
```

Incollare soltanto il token, salvare e uscire. Per leggere gli ID dalla API
ufficiale Telegram:

```bash
sudo bash -c '
  token=$(cat /etc/raspberry-server/ai-ops-telegram-bot-token)
  curl --silent --show-error "https://api.telegram.org/bot${token}/getUpdates"
' | jq '.result[] | {user_id: .message.from.id, chat_id: .message.chat.id}'
```

Inserire i due numeri reali in `.env`. Nella chat privata normalmente
coincidono, ma vanno comunque configurati entrambi. Il poller accetta una
richiesta solo quando coincidono sia utente sia chat.

## 5. Importare e attivare il workflow

Da n8n selezionare **Import from File** e importare:

```text
workflows/n8n-ai-ops-telegram-local.json
```

Aprire tutti i nodi che richiedono credenziali e selezionare quella corretta:

- `PiServer AI Ops Gateway` per diagnostica, registrazione, esecuzione e
  annullamento del piano;
- `PiServer AI Ops Telegram Bridge` per messaggi e callback Telegram.

Il nodo **Ollama Qwen locale** non deve avere credenziali. Salvare e attivare
il workflow: il percorso di produzione deve restare
`piserver-ai-ops-telegram-v1`, perché il poller lo usa sulla rete interna.

## 6. Avviare il poller e verificare

Dopo avere salvato gli ID in `.env` e attivato il workflow:

```bash
docker compose -f compose.yaml -f compose.automation.yaml config --quiet
sudo systemctl restart ai-ops-gateway.service
sudo systemctl restart automation-stack.service
docker compose -f compose.yaml -f compose.automation.yaml ps
docker compose -f compose.yaml -f compose.automation.yaml logs \
  --tail=100 ai-ops-bridge ai-ops-telegram n8n ollama
```

Inviare al bot un test non distruttivo:

```text
/fix verifica se tutti gli stack e i container risultano attivi e segnala eventuali problemi
```

Qwen deve inviare un rapporto. Se non esistono azioni necessarie, non deve
apparire alcun pulsante di conferma. Per provare l'intero ciclo, descrivere un
servizio ammesso realmente non funzionante e controllare attentamente piano e
rischi prima di premere **Conferma**.

Verifiche host utili:

```bash
sudo systemctl status ai-ops-gateway.service automation-stack.service --no-pager
sudo journalctl -u ai-ops-gateway.service -n 100 --no-pager
sudo ls -la /var/lib/raspberry-server/ai-ops
```

## Arresto e rollback operativo

Per disabilitare immediatamente il canale AI Ops senza fermare n8n e Ollama:

```bash
docker compose -f compose.yaml -f compose.automation.yaml stop \
  ai-ops-telegram ai-ops-bridge
sudo systemctl disable --now ai-ops-gateway.service
```

Per riattivarlo:

```bash
sudo systemctl enable --now ai-ops-gateway.service
docker compose -f compose.yaml -f compose.automation.yaml up -d \
  ai-ops-bridge ai-ops-telegram
```

Revocare un bot compromesso da BotFather, sostituire il file token e ricreare
`ai-ops-telegram`. Per ruotare gli altri segreti, fermare i due bridge,
sostituire il relativo file con 32 byte casuali e aggiornare la credenziale n8n
prima della riattivazione.

## Limiti noti

- il trigger iniziale è manuale; il rilevamento automatico verrà aggiunto solo
  dopo un periodo di osservazione dei falsi positivi;
- un modello 4B può sbagliare diagnosi: la policy e la conferma umana sono
  controlli obbligatori, non opzionali;
- la conferma autorizza esattamente il piano mostrato, non una sessione aperta;
- Telegram è un servizio esterno e conserva i messaggi secondo le sue regole;
- il workflow non può modificare codice o configurazioni arbitrarie.
