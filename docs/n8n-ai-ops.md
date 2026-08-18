# AI Ops remoto con n8n, Telegram e approvazione umana

Questa guida installa e collauda la **prima versione manuale** di AI Ops. Alla
fine l'amministratore può inviare `/fix descrizione del problema` al bot
Telegram, ricevere diagnosi e piano, quindi approvare o annullare le modifiche.

OpenAI viene chiamato tramite API remota. Il modello non è locale e non usa
Ollama. Il rilevamento automatico degli errori e la lettura dei nomi delle
cartelle Nextcloud non fanno parte di questa prima versione; sono descritti
nella sezione [Estensioni non ancora implementate](#estensioni-non-ancora-implementate).

## Risultato e flusso di approvazione

1. l'amministratore scrive `/fix descrizione del problema` in una chat privata;
2. il poller Telegram usa `getUpdates` in uscita e inoltra il messaggio al
   webhook n8n sulla sola rete Docker interna;
3. n8n chiede al gateway una diagnostica priva di dati applicativi privati;
4. la Responses API di OpenAI produce diagnosi e piano JSON vincolato;
5. il bot mostra problema, evidenze, modifiche esatte, rischi e verifiche;
6. nessuna modifica avviene finché l'utente autorizzato non preme
   **Conferma modifiche**;
7. il gateway convalida nuovamente il piano, esegue soltanto azioni ammesse e
   restituisce il rapporto finale.

## Confini di sicurezza

Il modello non riceve una shell, il socket Docker o un mount del filesystem.
Riceve soltanto il JSON prodotto da `scripts/ai-ops-gateway.py`. Il profilo
iniziale include:

- stato delle unità systemd selezionate;
- stato e health dei servizi Compose selezionati;
- `git status` della repository;
- spazio disponibile nel filesystem della repository;
- un insieme fisso di configurazioni versionate, tra cui `compose*.yaml` e
  `Caddyfile`.

Sono esclusi esplicitamente:

- `.env`, credenziali, chiavi e token;
- log applicativi;
- database;
- file Nextcloud e directory media;
- letture arbitrarie del filesystem.

Il workflow AI Ops non è collegato a Nextcloud. Quindi non vede né i file né i
nomi delle cartelle Nextcloud. Il connettore Nextcloud eventualmente usato da
altri workflow rimane separato.

Ogni azione mutante passa da un piano con token casuale, scadenza di 15 minuti
e stato persistito in `/var/lib/raspberry-server/ai-ops`. Il primo tap lo marca
come `executing` prima dell'effetto collaterale; tap ripetuti vengono rifiutati.

Solo il poller Telegram possiede
`/etc/raspberry-server/ai-ops-approval-token`. Dopo aver verificato chat ID e
user ID, il poller marca il piano come approvato. Questa credenziale non viene
montata in n8n e non deve essere inserita nel suo gestore credenziali.

Le sole azioni disponibili sono:

| Tipo | Vincolo |
| --- | --- |
| `restart_systemd_unit` | unità elencata nella policy |
| `restart_compose_service` | servizio e stack elencati nella policy |
| `run_maintenance_task` | script predefinito, senza argomenti liberi |
| `apply_repo_patch` | diff Git entro 32 KiB e soli percorsi autorizzati |

Il gateway usa array di argomenti e non invoca `shell=True`. Le patch non
possono modificare gateway, bridge, policy, installer o unità che impongono i
confini. Una patch viene rifiutata se uno dei file interessati ha già modifiche
locali. Non viene eseguito automaticamente alcun commit o push.

Il riavvio di n8n e dell'intero stack automation non è autorizzato nella prima
versione perché interromperebbe il workflow che deve comunicare l'esito. Questi
casi restano interventi manuali via SSH.

La policy versionata è `config/ai-ops/policy.json`. Allargarla è
un'operazione amministrativa manuale: modificare il file, riesaminarlo e poi
eseguire:

```bash
sudo systemctl restart ai-ops-gateway.service
```

## 0. Prerequisiti e decisione go/no-go

Eseguire i comandi sul server Debian come normale utente amministratore con
accesso `sudo`. Gli esempi presumono che la repository sia in
`/opt/raspberry-server`; se `STACK_DIR` ha un altro valore, usare quel percorso.

Servono:

- Docker Engine e plugin Docker Compose;
- `python3`, `openssl`, `curl`, `jq` e Git;
- stack core già funzionante;
- n8n raggiungibile dall'amministratore tramite Tailscale;
- account Telegram;
- account OpenAI API con fatturazione API configurata;
- backup verificato prima di consentire modifiche al server.

Controllare i programmi installati:

```bash
command -v docker
docker compose version
command -v python3
command -v openssl
command -v curl
command -v jq
command -v git
```

Installare gli strumenti host mancanti:

```bash
sudo apt-get update
sudo apt-get install -y python3 openssl curl jq git
```

Prima di procedere, eseguire o verificare un backup seguendo
`docs/backup-and-restore.md`. Non installare AI Ops se il ripristino non è mai
stato provato o se il server ha un problema già in corso che rende rischioso
un riavvio.

## 1. Aggiornare e verificare la repository

Entrare nella repository e verificare che non ci siano modifiche sconosciute:

```bash
cd /opt/raspberry-server
git status --short
```

Se il comando mostra file modificati, fermarsi e riesaminarli. Non usare
`git reset`, non fare stash automatici e non sovrascrivere modifiche locali.
Il gateway rifiuta intenzionalmente di applicare patch a file già modificati.

Con albero pulito, aggiornare solo con fast-forward e ricontrollare:

```bash
git pull --ff-only
git status --short
```

Verificare `.env` e i valori base. I due ID Telegram verranno compilati più
avanti:

```bash
test -r .env
chmod 600 .env
grep -E '^(STACK_DIR|DATA_DIR|PUID|PGID|N8N_IMAGE|MONITORING_API_IMAGE)=' .env
bash scripts/preflight.sh
```

`scripts/preflight.sh` deve terminare con `Compose and host preflight
completed`. Correggere qualunque errore prima di continuare.

## 2. Preparare le directory persistenti

Il poller salva soltanto l'offset Telegram. Con i valori predefiniti di
`.env`, creare la directory con l'utente del container:

```bash
sudo install -d -m 0750 -o 1000 -g 1000 \
  /srv/raspberry-server/data/n8n/ai-ops-telegram
sudo ls -ld /srv/raspberry-server/data/n8n/ai-ops-telegram
```

Se `DATA_DIR`, `PUID` o `PGID` in `.env` non sono quelli predefiniti, sostituire
percorso, proprietario e gruppo nel comando. La directory non deve essere
scrivibile da tutti.

## 3. Installare e verificare il gateway host

L'installer copia le unità systemd e crea, se assenti, tre token indipendenti:

- `ai-ops-token`: n8n verso gateway;
- `ai-ops-approval-token`: poller verso endpoint di approvazione;
- `ai-ops-telegram-bridge-token`: n8n verso bridge Telegram.

I token esistenti vengono preservati.

```bash
cd /opt/raspberry-server
sudo bash scripts/install-systemd.sh "$USER" "$(id -gn)"
sudo systemctl status ai-ops-gateway.service --no-pager
sudo curl --fail --silent --show-error \
  --unix-socket /run/piserver-ai-ops/gateway.sock \
  http://localhost/v1/health
```

La risposta health deve essere JSON con stato positivo. Verificare anche
l'endpoint autenticato senza stampare il token:

```bash
sudo bash -c '
token=$(tr -d "\r\n" </etc/raspberry-server/ai-ops-token)
curl --fail --silent --show-error \
  --unix-socket /run/piserver-ai-ops/gateway.sock \
  --header "Authorization: Bearer ${token}" \
  http://localhost/v1/diagnostics >/dev/null
'
echo "Diagnostica gateway autenticata: OK"
```

In caso di errore:

```bash
sudo journalctl -u ai-ops-gateway.service -n 100 --no-pager
sudo ls -l /run/piserver-ai-ops/gateway.sock
```

Il gateway gira come root perché deve dialogare con systemd e Docker, ma
ascolta soltanto sul socket Unix. Il container `ai-ops-bridge` monta il socket
in sola lettura e lo espone unicamente sulla rete Docker interna `ai-ops`.

## 4. Avviare n8n e il bridge senza Telegram

In questa fase il file
`/etc/raspberry-server/ai-ops-telegram-bot-token` **non deve esistere**. Se
proviene da una prova precedente, spostarlo temporaneamente in una directory
root protetta e ripristinarlo solo nella sezione 9.

Avviare o riavviare lo stack automation:

```bash
sudo systemctl restart automation-stack.service
docker compose -f compose.yaml -f compose.automation.yaml ps \
  n8n n8n-postgres ai-ops-bridge
```

`n8n`, `n8n-postgres` e `ai-ops-bridge` devono risultare avviati; attendere gli
healthcheck prima di proseguire. Se il bridge non è sano:

```bash
docker compose -f compose.yaml -f compose.automation.yaml \
  logs --tail 100 ai-ops-bridge
```

## 5. Creare progetto e chiave OpenAI API

Usare la piattaforma OpenAI, non una chiave o sessione ChatGPT.

1. aprire `https://platform.openai.com/` e accedere;
2. configurare la fatturazione API richiesta dall'account;
3. creare un progetto dedicato, per esempio `PiServer AI Ops`;
4. nel progetto configurare un limite di spesa prudente e almeno un avviso;
5. verificare che il progetto possa usare il modello `gpt-5-mini`;
6. creare una nuova **project API key** dedicata a n8n;
7. copiare la chiave una sola volta e non inserirla in `.env`, file di testo,
   chat o cronologia della shell.

La documentazione OpenAI descrive chiavi, autorizzazioni dei modelli, rate
limit, avvisi e limiti di spesa per progetto:
`https://developers.openai.com/api/reference/typescript/resources/admin/subresources/organization/subresources/projects`.
Il modello `gpt-5-mini` supporta Responses API e output strutturati:
`https://developers.openai.com/api/docs/models/gpt-5-mini`.

Conservare temporaneamente la chiave nel password manager fino alla creazione
della credenziale n8n. La chiave non deve mai arrivare al bot Telegram.

## 6. Creare le tre credenziali n8n

Aprire l'editor privato:

```text
https://TAILSCALE_FQDN:8449/
```

Creare tre credenziali di tipo **Header Auth**. Per tutte il nome dell'header è
esattamente `Authorization`. Nel valore ci deve essere `Bearer`, un singolo
spazio e poi il token, senza virgolette.

| Nome credenziale | Valore header |
| --- | --- |
| `OpenAI API` | `Bearer <project API key OpenAI>` |
| `PiServer AI Ops Gateway` | `Bearer <contenuto di ai-ops-token>` |
| `PiServer AI Ops Telegram Bridge` | `Bearer <contenuto di ai-ops-telegram-bridge-token>` |

Per leggere i due token interni, uno alla volta:

```bash
sudo tr -d '\r\n' </etc/raspberry-server/ai-ops-token
echo
sudo tr -d '\r\n' </etc/raspberry-server/ai-ops-telegram-bridge-token
echo
```

Non leggere né creare in n8n la credenziale
`ai-ops-approval-token`. Dopo aver incollato i valori:

- salvare le credenziali;
- svuotare gli appunti;
- chiudere eventuali terminali condivisi;
- non inserire i token in screenshot o ticket.

n8n cifra le credenziali nel proprio database tramite `N8N_ENCRYPTION_KEY`.
Verificare che quella variabile in `.env` non sia un placeholder e che ne
esista una copia nel backup amministrativo.

## 7. Verificare la credenziale OpenAI prima del workflow

In n8n creare temporaneamente un workflow di prova con un nodo **HTTP
Request**:

- metodo: `POST`;
- URL: `https://api.openai.com/v1/responses`;
- autenticazione: credenziale `OpenAI API`;
- header `Content-Type`: `application/json`;
- body JSON:

```json
{
  "model": "gpt-5-mini",
  "input": "Rispondi esclusivamente con la parola OK"
}
```

Eseguire il nodo. La risposta deve avere stato HTTP 200 e contenere un output
del modello. Se riceve 401, ricontrollare chiave e spazio dopo `Bearer`; con
403 ricontrollare progetto e permessi del modello; con 429 controllare
fatturazione e limiti. Eliminare il workflow temporaneo dopo il test.

## 8. Importare, configurare e pubblicare il workflow

Nell'editor n8n importare il file:

```text
workflows/n8n-ai-ops-telegram.json
```

Il file importato è intenzionalmente inattivo e contiene placeholder. Aprire
tutti i nodi HTTP interessati e sostituire ogni placeholder:

- `REPLACE_OPENAI_CREDENTIAL` con `OpenAI API`;
- `REPLACE_AI_OPS_GATEWAY_CREDENTIAL` con
  `PiServer AI Ops Gateway`;
- `REPLACE_TELEGRAM_BRIDGE_CREDENTIAL` con
  `PiServer AI Ops Telegram Bridge`.

Controllare inoltre:

- `Webhook Telegram interno`: path
  `piserver-ai-ops-telegram-v1`, metodo POST e risposta immediata;
- `OpenAI Responses API`: URL `https://api.openai.com/v1/responses`;
- nodi verso `ai-ops-bridge`: credenziale gateway;
- nodi verso `ai-ops-telegram`: credenziale bridge Telegram;
- `Prepara richiesta OpenAI`: modello `gpt-5-mini`.

Cercare nell'intero workflow la stringa `REPLACE_`: non deve rimanerne alcuna.
Salvare, quindi usare **Publish/Activate** secondo l'etichetta mostrata dalla
versione n8n e verificare che il workflow risulti pubblicato e attivo. Il
webhook di produzione deve essere:

```text
http://n8n:5678/webhook/piserver-ai-ops-telegram-v1
```

È un URL della rete Docker interna. Non aggiungerlo a Cloudflare Tunnel,
Tailscale Serve, Caddy o a un port forwarding del router.

Se la pubblicazione fallisce, controllare le esecuzioni n8n e i log:

```bash
docker compose -f compose.yaml -f compose.automation.yaml logs --tail 100 n8n
```

## 9. Creare e configurare il bot Telegram

Eseguire questa sezione solo dopo aver pubblicato il workflow.

### 9.1 Creare il bot

In una chat privata con `@BotFather`:

1. inviare `/newbot`;
2. assegnare nome e username;
3. copiare il token una sola volta;
4. non aggiungere il bot a gruppi o canali;
5. non inoltrare il messaggio contenente il token.

### 9.2 Salvare il token senza inserirlo nella cronologia

Preparare prima `sudo`, poi acquisire il token con input nascosto. Il file
temporaneo permette di conservare un eventuale token precedente se il comando
viene interrotto prima del `mv` finale:

```bash
sudo -v
sudo install -m 0640 -o root -g "$(id -gn)" /dev/null \
  /etc/raspberry-server/ai-ops-telegram-bot-token.new
read -rsp 'Telegram bot token: ' BOT_TOKEN_INPUT; echo
printf '%s\n' "$BOT_TOKEN_INPUT" | \
  sudo tee /etc/raspberry-server/ai-ops-telegram-bot-token.new >/dev/null
unset BOT_TOKEN_INPUT
sudo chmod 0640 /etc/raspberry-server/ai-ops-telegram-bot-token.new
sudo mv /etc/raspberry-server/ai-ops-telegram-bot-token.new \
  /etc/raspberry-server/ai-ops-telegram-bot-token
sudo test -s /etc/raspberry-server/ai-ops-telegram-bot-token
```

Il file è gestito da root e leggibile dal gruppo amministrativo necessario al
container; non è leggibile da altri utenti. Non è tecnicamente `0600` perché
il poller non gira come root.

### 9.3 Verificare il token e rimuovere eventuali webhook

I comandi seguenti non inseriscono il token nella riga di comando salvata
nella cronologia:

```bash
sudo bash -c '
token=$(tr -d "\r\n" </etc/raspberry-server/ai-ops-telegram-bot-token)
curl --fail --silent --show-error \
  "https://api.telegram.org/bot${token}/getMe"
' | jq

sudo bash -c '
token=$(tr -d "\r\n" </etc/raspberry-server/ai-ops-telegram-bot-token)
curl --fail --silent --show-error --request POST \
  "https://api.telegram.org/bot${token}/deleteWebhook" \
  --data "drop_pending_updates=false"
' | jq
```

Entrambe le risposte devono contenere `"ok": true`. `getUpdates` e webhook
Telegram sono mutuamente esclusivi; non configurare `setWebhook` per questo
bot.

### 9.4 Ricavare chat ID e user ID senza bot di terze parti

Aprire una chat privata con il nuovo bot e inviare:

```text
/start
```

Prima di avviare il poller, leggere l'update una sola volta:

```bash
sudo bash -c '
token=$(tr -d "\r\n" </etc/raspberry-server/ai-ops-telegram-bot-token)
curl --fail --silent --show-error \
  "https://api.telegram.org/bot${token}/getUpdates?timeout=0"
' | jq '.result[] | select(.message != null) | {
  user_id: .message.from.id,
  chat_id: .message.chat.id,
  username: .message.from.username,
  text: .message.text
}'
```

Copiare gli ID numerici dell'account amministratore e della chat privata nella
`.env`:

```dotenv
AI_OPS_TELEGRAM_CHAT_ID=123456789
AI_OPS_TELEGRAM_USER_ID=123456789
```

In una chat privata normalmente coincidono. Non usare ID di gruppi. Verificare
che non siano rimasti `disabled` o i valori di esempio:

```bash
grep -E '^AI_OPS_TELEGRAM_(CHAT|USER)_ID=' .env
```

### 9.5 Validare Compose e avviare il poller

```bash
bash scripts/preflight.sh
docker compose -f compose.yaml -f compose.automation.yaml config --quiet
docker compose -f compose.yaml -f compose.automation.yaml \
  up -d ai-ops-telegram
docker compose -f compose.yaml -f compose.automation.yaml \
  ps ai-ops-telegram
docker compose -f compose.yaml -f compose.automation.yaml \
  logs --tail 100 ai-ops-telegram
```

Il servizio deve risultare avviato e poi sano. Errori 401 indicano token
Telegram o credenziale bridge errati; errori 404 dal webhook n8n indicano che
il workflow non è pubblicato; continui riavvii richiedono il controllo dei
permessi della directory `/state`.

## 10. Collaudo a strati

Non iniziare subito con un riavvio reale. Eseguire i test nell'ordine.

### 10.1 Diagnosi senza azioni

Inviare in chat privata:

```text
/fix Descrivi lo stato generale senza proporre modifiche; se mancano prove restituisci nessuna azione
```

Il primo messaggio deve iniziare con `DIAGNOSI AI - nessuna modifica ancora
eseguita`. Non premere conferma se il piano contiene azioni inattese.

### 10.2 Cancellazione

Generare un piano con azioni, premere **Annulla** e verificare che il rapporto
dica che il piano è stato cancellato. Controllare che nessun servizio sia stato
riavviato.

### 10.3 Scadenza

Generare un nuovo piano, attendere più di 15 minuti e provare ad approvarlo.
L'esecuzione deve essere rifiutata come scaduta.

### 10.4 Approvazione controllata

Chiedere un riavvio innocuo di un servizio esplicitamente consentito dalla
policy, leggere tutto il piano e premere **Conferma modifiche**. Verificare:

- messaggio di esecuzione iniziata;
- rapporto finale con risultato e nuova diagnostica;
- servizio tornato sano;
- audit nel journal.

### 10.5 Idempotenza e autorizzazione

1. premere due volte lo stesso pulsante: la seconda esecuzione deve fallire;
2. scrivere al bot da un altro account: il workflow non deve rispondere;
3. chiedere di leggere `.env`, token, database o un file Nextcloud: il modello
   deve rifiutare o dichiarare di non avere accesso;
4. chiedere un comando shell libero: non deve diventare un piano eseguibile;
5. chiedere una patch su un file con modifiche locali: il gateway deve
   rifiutarla.

Controllare l'audit locale, che non viene inviato a OpenAI:

```bash
sudo ls -l /var/lib/raspberry-server/ai-ops
sudo journalctl -u ai-ops-gateway.service --since today --no-pager
```

L'installazione è accettata soltanto se tutti i test precedenti hanno il
risultato previsto.

## 11. Uso quotidiano

Formato consigliato:

```text
/fix <sintomo osservato, orario, servizio coinvolto e cosa era atteso>
```

Esempio:

```text
/fix Dalle 14:20 la homepage restituisce 502; prima funzionava. Verifica lo stato e proponi una correzione prudente
```

Non incollare password, token, `.env`, dump di database o log non ripuliti. La
diagnostica base evita deliberatamente i log applicativi. Se le prove non
bastano, il modello restituisce `actions: []`; l'amministratore può aggiungere
al prompt un breve estratto già controllato e privato dei segreti.

Prima di approvare verificare sempre:

- che problema ed evidenze corrispondano a ciò che è stato osservato;
- ogni file o servizio che verrà modificato;
- rischi e indisponibilità prevista;
- procedura di verifica e possibilità di rollback.

L'approvazione Telegram non sostituisce il giudizio amministrativo.

## 12. Arresto, revoca e rollback

Per disabilitare immediatamente il canale senza cancellare dati:

```bash
docker compose -f compose.yaml -f compose.automation.yaml \
  stop ai-ops-telegram
sudo systemctl stop ai-ops-gateway.service
```

Per riabilitarlo:

```bash
sudo systemctl start ai-ops-gateway.service
docker compose -f compose.yaml -f compose.automation.yaml \
  up -d ai-ops-bridge ai-ops-telegram
```

Per revocare il bot, rigenerare il token con `@BotFather`, fermare prima il
poller e sostituire il file con la procedura della sezione 9.2.

Per ruotare i token interni:

1. fermare poller e gateway;
2. fare una copia amministrativa delle credenziali n8n esistenti;
3. sostituire i file in `/etc/raspberry-server` con token casuali indipendenti;
4. aggiornare le due credenziali Header Auth n8n;
5. riavviare gateway, bridge e poller;
6. ripetere i test di health, autenticazione e cancellazione.

Il token di approvazione deve restare soltanto nel gateway host e nel poller
Telegram.

## 13. Risoluzione dei problemi

| Sintomo | Verifica |
| --- | --- |
| il bot non risponde | workflow pubblicato, ID in `.env`, log poller |
| `Conflict: terminated by other getUpdates` | esiste un altro poller con lo stesso bot |
| `getUpdates` non funziona | eseguire `deleteWebhook` e fermare altri poller |
| webhook n8n restituisce 404 | workflow non pubblicato o path errato |
| OpenAI restituisce 401 | chiave o formato `Bearer <chiave>` errato |
| OpenAI restituisce 403 | progetto o modello non autorizzato |
| OpenAI restituisce 429 | quota, fatturazione o rate limit |
| bridge restituisce 401 | credenziale gateway/bridge errata |
| poller non diventa sano | token Telegram, rete o permessi `/state` |
| piano rifiutato come scaduto | generare un nuovo piano entro 15 minuti |
| patch rifiutata | file fuori allowlist, diff troppo grande o working tree sporco |

Comandi di diagnosi:

```bash
sudo systemctl status ai-ops-gateway.service --no-pager
sudo journalctl -u ai-ops-gateway.service -n 100 --no-pager
docker compose -f compose.yaml -f compose.automation.yaml ps
docker compose -f compose.yaml -f compose.automation.yaml \
  logs --tail 100 n8n ai-ops-bridge ai-ops-telegram
```

## Estensioni non ancora implementate

La procedura precedente completa l'installazione della versione manuale. Non
considerare presenti le funzionalità seguenti finché non vengono aggiunti e
collaudati workflow dedicati.

### Rilevamento automatico

La fase successiva può riusare la stessa diagnosi con:

- **Error Trigger** n8n per gli errori dei workflow selezionati;
- webhook di Uptime Kuma per un monitor `DOWN`.

Questi ingressi devono solamente creare una richiesta di diagnosi e inviare il
piano su Telegram. Non devono chiamare `/execute`; approvazione umana, token
monouso e scadenza restano obbligatori.

Prima di abilitarli servono deduplicazione degli allarmi, limite di frequenza,
finestra di silenzio, identificatore stabile dell'incidente e test che evitino
loop quando il workflow AI Ops stesso fallisce.

### Metadati Nextcloud senza contenuti

Questa versione non mostra neppure i nomi delle cartelle Nextcloud. Per
aggiungerli in futuro serve un endpoint gateway separato che restituisca solo
una allowlist di nomi o identificatori di cartella, senza file, proprietari,
condivisioni, metadati sensibili o contenuti. L'estensione deve essere
riesaminata e testata prima di modificare la policy iniziale.

## Riferimenti

- [OpenAI Projects](https://developers.openai.com/api/reference/typescript/resources/admin/subresources/organization/subresources/projects)
- [OpenAI GPT-5 mini](https://developers.openai.com/api/docs/models/gpt-5-mini)
- [OpenAI Responses API](https://platform.openai.com/docs/api-reference/responses)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- [Importazione ed esportazione workflow n8n](https://docs.n8n.io/workflows/export-import/)
- [Gestione errori n8n](https://docs.n8n.io/flow-logic/error-handling/)
