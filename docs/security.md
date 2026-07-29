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
| Soulseek peer port `50300` | non pubblicata | no |
| Pi-hole DNS | porta 53, LAN e Tailnet | no |
| Ollama, PostgreSQL, Redis/Valkey | reti Docker interne | no |

Non creare inoltri sul router per 22, 53, 80, 443, 2283, 3000, 3001, 5432,
4533, 5030, 5031, 50300, 5678, 6379, 8000, 8096, 8686 o 11434.

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

## Pi-hole e Tailscale

Pi-hole ascolta su tutte le interfacce host per servire LAN e Tailnet, ma la
porta 53 non deve essere inoltrata da Internet. Il server usa
`tailscale set --accept-dns=false` per evitare di interrogare sé stesso.

Nella console Tailscale, l'IPv4 Tailnet del mini PC viene configurato come
nameserver globale con **Override local DNS**. MagicDNS resta attivo.

## Manutenzione

- Applicare regolarmente gli aggiornamenti di sicurezza Debian.
- Aggiornare le immagini soltanto dopo un backup e la lettura delle release
  notes.
- Controllare mensilmente `docker compose ps`, `systemctl --failed`,
  `systemctl list-timers`, `tailscale status` e i log Restic.
- Disabilitare UPnP sul router se non necessario.
- Non committare `.env`, credenziali SMB, database o esportazioni Vaultwarden.
