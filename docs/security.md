# Sicurezza e confini di accesso

## Matrice di esposizione

| Servizio | Percorso | Internet pubblico |
| --- | --- | --- |
| Sito | Cloudflare Tunnel → Caddy | sì |
| Vaultwarden | Cloudflare Tunnel → Caddy | sì |
| webhook e chat n8n | Tailscale Serve `8449` | no |
| Homepage | Tailscale Serve `443` | no |
| area privata sito | Tailscale Serve `8443` | no |
| Pi-hole dashboard | Tailscale Serve `8444` | no |
| Nextcloud | Tailscale Serve `8445` | no |
| Jellyfin | Tailscale Serve `8446` | no |
| Immich | Tailscale Serve `8447` | no |
| Uptime Kuma | Tailscale Serve `8448` | no |
| editor n8n | Tailscale Serve `8449` | no |
| StreamingCommunity downloader | Tailscale Serve `8450` | no |
| Aurral | Tailscale Serve `8451` | no |
| Navidrome | Tailscale Serve `8452` | no |
| Lidarr Web UI | Tailscale Serve `8453` | no |
| slskd Web UI | Tailscale Serve `8454` | no; la porta P2P `50300` resta chiusa |
| Homepage `rack-pi` | Tailscale Serve `443` sul Raspberry | no |
| Pi-hole secondario | DNS LAN/Tailnet + Serve `8444` | no |
| Uptime Kuma `rack-pi` | Tailscale Serve `8448` | no |
| Rest Server append-only | IPv4 Tailscale `rack-pi:8000` | no |
| SSH backup mini PC | IPv4 Tailscale `mini-pc:2222`, solo `pibackup` | no |
| Controller PC gaming | Tailscale Serve `8455`, backend solo loopback | no |
| Sunshine sul PC gaming | IPv4 Tailscale del PC, porte GameStream | no |
| Soulseek peer port `50300` | non pubblicata | no |
| Pi-hole DNS | porta 53, LAN e Tailnet | no |
| Ollama, SearXNG, PostgreSQL, Redis/Valkey | reti Docker interne | no |
| proxy Nextcloud sola lettura | rete Docker `ai-connectors` | no |

Non creare inoltri sul router per 22, 53, 80, 443, 2283, 3000, 3001, 5432,
4533, 5030, 5031, 50300, 5678, 6379, 8000, 8084, 8096, 8455, 8686,
11434, 2222 o per le porte Sunshine 47984-48010.

## Vaultwarden

- Tenere `SIGNUPS_ALLOWED=false` dopo la creazione dell'account.
- Usare master password unica e 2FA.
- Conservare il recovery code fuori dal vault.
- `ADMIN_TOKEN` deve essere un hash Argon2, non una password in chiaro.
- Il database completo Restic è il backup primario; il JSON sul PC è la seconda
  via. Per allegati usare anche l'esportazione ZIP con allegati.
- Non mettere Cloudflare Access davanti al dominio Vaultwarden: i client nativi
  non possono completare un login web interattivo aggiuntivo.

## Homepage e Docker

Homepage non offre un proprio livello di autenticazione ed è accessibile solo
dalla Tailnet. Non monta direttamente `/var/run/docker.sock`: comunica con un
proxy su rete Docker interna che espone soltanto endpoint di lettura e blocca
ogni richiesta POST.

Il socket Docker equivale di fatto ad accesso root. Non aggiungere nuovi
permessi al proxy senza verificare l'endpoint richiesto.

## n8n e Ollama

L'editor, gli endpoint webhook e la chat n8n sono Tailnet-only sulla porta
`8449`. `N8N_WEBHOOK_DOMAIN` deve coincidere con `TAILSCALE_FQDN`; non creare
una route Cloudflare per n8n. Un'eventuale futura esposizione pubblica richiede
un hostname e una configurazione separati, oltre a firma HMAC, token o altro
segreto non prevedibile.

`N8N_ENCRYPTION_KEY` è permanente e deve rimanere associata al relativo dump
PostgreSQL. Ollama non pubblica alcuna porta host e n8n lo raggiunge tramite
`http://ollama:11434`.

Postgres Chat Memory salva il contenuto delle conversazioni nella tabella
`ai_chat_memory` del database n8n. I dati sono protetti dai confini del server
e dal backup Restic cifrato, ma nel database PostgreSQL locale non sono
cifrati campo per campo. Non inserire in chat segreti che non devono essere
conservati.

SearXNG non pubblica porte sull'host: n8n usa la sua API JSON sulla rete
interna `ai-connectors`. Il container dispone di una rete di uscita separata
per interrogare i motori esterni; le query lasciano quindi la rete locale,
anche se l'istanza SearXNG non è accessibile da Internet.

n8n non è collegato direttamente al container Nextcloud: Nextcloud usa la rete
dedicata `nextcloud-access` soltanto con Homepage e Uptime Kuma. Il servizio
`nextcloud-readonly` inoltra soltanto `GET`, `HEAD`, `OPTIONS` e `PROPFIND`
agli endpoint necessari per elencare e scaricare file. Tutte le operazioni
WebDAV di scrittura e le altre API Nextcloud sono bloccate. Usare comunque un
account dedicato, una password applicazione revocabile e una cartella
condivisa senza permesso di modifica.

I risultati web e i documenti possono contenere prompt injection. Il prompt
di sistema deve considerarli dati non attendibili, mai istruzioni, e l'agente
non deve ricevere strumenti di scrittura o segreti non necessari.

Anche i contenuti restituiti da GitHub sono dati non attendibili. Il relativo
token n8n deve avere accesso soltanto ai repository selezionati e permessi di
sola lettura; non collegare all'AI Agent operazioni GitHub di scrittura.

DeepL è un servizio esterno: ogni testo passato al nodo DeepL lascia il server
locale. Non inoltrare automaticamente documenti Nextcloud, segreti o cronologia
della chat. Usare Qwen per la traduzione locale dei documenti privati oppure
richiedere una conferma umana prima di usare DeepL.

## AI Ops locale

Il workflow di manutenzione usa `qwen3.5:4b` dentro Ollama. Prompt e diagnostica
non vengono inviati a un fornitore AI remoto; il comando e i rapporti passano
però attraverso Telegram. Il profilo di raccolta esclude log applicativi,
`.env`, credenziali, database, file Nextcloud e media.

n8n non riceve il socket Docker e non esegue shell. Un gateway host separato
ascolta soltanto su Unix socket, valida azioni tipizzate contro
`config/ai-ops/policy.json` e accetta solo target in allowlist. Shell, patch e
percorsi arbitrari sono rifiutati anche dopo l'approvazione.

Ogni azione richiede conferma Telegram da una combinazione esatta di user ID e
chat ID. La credenziale che marca il piano come approvato è montata soltanto
nel poller Telegram, non in n8n. I piani scadono dopo 15 minuti, sono monouso e
restano registrati localmente per audit. Vedi
[n8n-ai-ops-local.md](n8n-ai-ops-local.md).

## StreamingCommunity downloader

Il pannello è raggiungibile soltanto attraverso Tailscale e usa
l'autenticazione Jellyfin (`AUTH_ENABLED=1`). La configurazione persistente
contiene sessioni e una API key Jellyfin: resta sull'SSD con permessi
root-only ed entra esclusivamente nel backup Restic cifrato. Il container può
scrivere soltanto nella directory media `downloads`, non nelle altre librerie
Jellyfin.

## Stack musicale

Tutti i pannelli musicali sono pubblicati nella sola Tailnet tramite Tailscale
Serve; i rispettivi container restano legati a `127.0.0.1`. Le card Homepage
contengono i collegamenti Tailnet, senza esporre nulla alla LAN o a Internet.

La porta Soulseek `50300/tcp` non viene pubblicata da Docker né inoltrata sul
router. slskd usa soltanto connessioni in uscita e non condivide directory.
L'eventuale apertura futura è un'eccezione al modello Tailnet-only e richiede
una valutazione separata di firewall, router, aggiornamenti e contenuti
condivisi.

Navidrome monta l'intera radice musicale in sola lettura. Aurral vede la
libreria permanente in sola lettura e può scrivere soltanto il proprio output
e consumare i download slskd completati.

## Storage di rete

Un mount NAS assente non deve essere sostituito da una normale directory
locale. `check-media-mount.sh` richiede sia un mount reale sia il marker
`.piserver-media`. Le credenziali SMB, se usate, hanno mode `0600`.

Il media remoto non è coperto dal backup Restic di configurazione. Un guasto del
disco da 4 TB comporterà la perdita dei file finché non verrà predisposta una
seconda copia.

## Raspberry `rack-pi` e backup remoto

Rest Server ascolta soltanto sull'IPv4 Tailscale di `rack-pi`, usa autenticazione
bcrypt e modalità append-only/private-repos. HTTP non è esposto alla LAN: il
trasporto è protetto da Tailscale e i pack Restic sono già cifrati end-to-end.
Le operazioni distruttive `forget` e `prune` avvengono soltanto localmente sul
Raspberry dopo avere fermato l'endpoint remoto.

Il mini PC non accetta una shell amministrativa dal Raspberry. L'utente
`pibackup` ha password bloccata, chiave Ed25519 limitata all'IP Tailscale del
Raspberry, opzione OpenSSH `restrict`, forced command e una sola regola sudo
senza argomenti. La host key del mini PC viene confrontata fuori banda e poi
fissata in un `known_hosts` root-only. L'automazione usa OpenSSH sulla porta
dedicata 2222, limitata al solo `pibackup`, perché la porta Tailnet 22 continua
a essere gestita da Tailscale SSH per gli accessi interattivi.

Il repository delle configurazioni del Raspberry usa password e percorso
separati e non è raggiungibile dalle credenziali `minipc`. La chiavetta storica
viene conservata offline dopo la migrazione. Rimane accettato il rischio di sito
singolo: non esiste una copia off-site contro furto, incendio o perdita
simultanea del rack.

## Pi-hole e Tailscale

Pi-hole ascolta su tutte le interfacce host per servire LAN e Tailnet, ma la
porta 53 non deve essere inoltrata da Internet. Il server usa
`tailscale set --accept-dns=false` per evitare di interrogare sé stesso.

Nella console Tailscale, l'IPv4 Tailnet del mini PC viene configurato come
nameserver globale con **Override local DNS**. MagicDNS resta attivo.

Non serve duplicare in SearXNG le blocklist gestite da Pi-hole. Pi-hole resta
però un filtro DNS, non una protezione completa contro URL arbitrari o SSRF:
gli strumenti HTTP e RSS controllati dal modello devono usare destinazioni
fisse o validate.

## Cloud gaming

Il controller gaming è un processo host distinto da `monitoring-api`: la
seconda resta read-only. Il backend ascolta esclusivamente su `127.0.0.1:8084`
e riceve richieste umane tramite Tailscale Serve `8455`. Autorizza soltanto i
login elencati e si fida degli header di identità perché una connessione di
rete non può raggiungere direttamente il loopback. Le azioni web richiedono
anche un token CSRF effimero.

Il magic packet contiene soltanto il MAC fisso configurato e viene inviato al
broadcast LAN fisso. Lo spegnimento usa una chiave Ed25519 dedicata, host key
verificata fuori banda, IP Tailscale del mini PC come unica sorgente e un
forced command Windows che rifiuta shell, SFTP e comandi diversi da
`shutdown`. L'account `gaming` resta non amministratore.

Sunshine e OpenSSH sul PC Windows accettano soltanto sorgenti Tailnet tramite
Windows Firewall; UPnP resta disabilitato. Il token condiviso con i callback
Sunshine può soltanto marcare inizio/fine sessione e non accende né spegne il
PC. L'auto-spegnimento si arma esclusivamente quando il controller ha inviato
il Wake-on-LAN e fallisce in modo conservativo lasciando il PC acceso.

Windows 10 Home 22H2 non riceve gli aggiornamenti di sicurezza ordinari dopo
il 14 ottobre 2025. Per questa macchina è accettato temporaneamente il rischio
residuo senza ESU; l'isolamento Tailnet riduce l'esposizione in ingresso ma non
sostituisce le patch contro contenuti, launcher o software vulnerabile.

## Manutenzione

- Applicare regolarmente gli aggiornamenti di sicurezza Debian.
- Aggiornare le immagini soltanto dopo un backup e la lettura delle release
  notes.
- Controllare mensilmente `docker compose ps`, `systemctl --failed`,
  `systemctl list-timers`, `tailscale status` e i log Restic.
- Disabilitare UPnP sul router se non necessario.
- Non committare `.env`, credenziali SMB, database o esportazioni Vaultwarden.
