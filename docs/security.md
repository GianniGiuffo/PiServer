# Sicurezza e confini di accesso

## Matrice di esposizione

| Servizio | Percorso | Internet pubblico |
| --- | --- | --- |
| Sito | Cloudflare Tunnel → Caddy | sì |
| Vaultwarden | Cloudflare Tunnel → Caddy | sì |
| webhook n8n | Cloudflare Tunnel → Caddy | solo quando abilitati |
| Homepage | Tailscale Serve `443` | no |
| area privata sito | Tailscale Serve `8443` | no |
| Pi-hole dashboard | Tailscale Serve `8444` | no |
| Nextcloud | Tailscale Serve `8445` | no |
| Jellyfin | Tailscale Serve `8446` | no |
| Immich | Tailscale Serve `8447` | no |
| Uptime Kuma | Tailscale Serve `8448` | no |
| editor n8n | Tailscale Serve `8449` | no |
| StreamingCommunity downloader | Tailscale Serve `8450` | no |
| Pi-hole DNS | porta 53, LAN e Tailnet | no |
| Ollama, PostgreSQL, Redis/Valkey | reti Docker interne | no |

Non creare inoltri sul router per 22, 53, 80, 443, 2283, 3000, 3001, 5432,
5678, 6379, 8000, 8096 o 11434.

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

L'editor n8n è Tailnet-only. L'hostname webhook pubblico rimane
`hooks.invalid` finché non esiste una necessità reale. Ogni webhook pubblico
deve verificare una firma HMAC, un token o un segreto non prevedibile.

`N8N_ENCRYPTION_KEY` è permanente e deve rimanere associata al relativo dump
PostgreSQL. Ollama non pubblica alcuna porta host e n8n lo raggiunge tramite
`http://ollama:11434`.

## StreamingCommunity downloader

Il pannello è raggiungibile soltanto attraverso Tailscale e usa
l'autenticazione Jellyfin (`AUTH_ENABLED=1`). La configurazione persistente
contiene sessioni e una API key Jellyfin: resta sull'SSD con permessi
root-only ed entra esclusivamente nel backup Restic cifrato. Il container può
scrivere soltanto nella directory media `downloads`, non nelle altre librerie
Jellyfin.

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
