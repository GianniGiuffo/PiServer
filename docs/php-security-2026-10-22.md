# Verifica PHP e accessi del 22 ottobre 2026

## Esito e interventi applicati

Il mini-PC eseguiva **Nextcloud 33.0.9 con PHP 8.4.25**, vulnerabile a
**CVE-2026-109618 e CVE-2026-109619**. Il servizio web e il cron sono stati
fermati durante la preparazione e sostituiti con l'immagine verificata:

```text
nextcloud:33.0-apache@sha256:a4f8627d317e6de663b700f6a0d022530f038980930a4b81e967e7c19501b839
Nextcloud 33.0.10 / PHP 8.4.27
```

La versione PHP è stata verificata prima senza volumi e rete, poi nei due
container ricreati; anche il log di avvio Apache riporta PHP 8.4.27.
L'aggiornamento applicativo è concluso, senza maintenance mode né migrazioni
pendenti. Il cron usa lo stesso digest. La build `33.0.9-apache` scaricata per
prima conteneva ancora PHP 8.4.26 ed è stata scartata.

Caddy e il frontend Seerr usano l'immagine standard Caddy 2.11.7, senza
interprete PHP. Negli altri container attivi del mini-PC e nei sette container
del Raspberry non sono stati trovati binari PHP nel percorso eseguibile.
Sui due host non risultano pacchetti runtime PHP installati. Pi-hole v6 usa il
webserver di FTL con Lua, non PHP. L'inventario dei binari non equivale a una
scansione completa di tutte le librerie incorporate nelle immagini.

È stata corretta anche una configurazione NFS diversa dal confine previsto
in [media-nfs-tailscale.md](media-nfs-tailscale.md):

- TCP 2049 ora ascolta soltanto su `100.95.133.122`, l'IPv4 Tailscale;
- NFSv3 e NFSv4.0 sono disabilitati; restano v4.1 e v4.2;
- rpcbind TCP/UDP 111 ascolta solo su `127.0.0.1` e `::1`;
- mountd non offre protocolli di mount v2/v3 e non ha listener di rete;
- rpc-statd, necessario per il locking v2/v3, è mascherato dopo aver
  verificato che anche i due mount in uscita usino NFSv4.2;
- NFS aspetta Tailscale e il mount `/srv/media` all'avvio.

Il client autorizzato si è riconnesso con NFSv4.2. Gli export restano in sola
lettura per il suo IP Tailscale. L'ascolto precedente su tutte le interfacce
non dimostra da solo che le porte fossero raggiungibili da Internet: non è
stata verificata la configurazione firewall/NAT del router.

Lo script riproducibile è
[`scripts/restrict-nfs-to-tailscale.sh`](../scripts/restrict-nfs-to-tailscale.sh).
È destinato a questo mini-PC con `/srv/media` e condivisioni solo NFSv4;
rifiuta mount in uscita che richiedono v2/v3. Non va applicato al Raspberry.

## Indagine sugli accessi

**Non sono emerse evidenze di compromissione nelle fonti controllate. Questo
non consente di escludere ogni intrusione precedente.**

Sono stati controllati:

- autenticazioni SSH/OpenSSH e Tailscale dall'8 ottobre: sul mini-PC i login
  osservati sono dal PC dell'amministratore, più gli accessi di `pibackup`
  dal Raspberry; sul Raspberry dal medesimo PC/account Tailscale;
- un login LAN con password del 16 ottobre alle 18:37, utente `tommaso`,
  da `192.168.178.30`, coincidente con l'IP LAN attuale del PC;
- 172.098 richieste nel log Apache conservato, dal 22 settembre al 22 ottobre:
  nessuna corrispondenza nei pattern cercati per webshell, traversal, file
  sensibili e session upload progress; nessun messaggio di crash/corruzione
  di memoria nei pattern cercati;
- log applicativi Nextcloud disponibili dal 13 al 22 ottobre, senza indicatori
  evidenti nei pattern esaminati;
- codice Nextcloud **precedente** alla patch, archiviato prima della
  sostituzione, confrontato con 24.921 file dell'immagine originale:
  nessun file mancante; unica differenza di contenuto `.htaccess`, con le
  regole generate da Nextcloud; unico file aggiuntivo
  `nextcloud-init-sync.lock`;
- integrità del core dopo l'aggiornamento, senza errori;
- account con UID 0, metadati delle chiavi autorizzate, cron e unità systemd,
  processi, listener e file SUID modificati negli ultimi 14 giorni;
- journal kernel del mini-PC dall'8 ottobre, senza corrispondenze per segfault,
  general protection fault e processi terminati per memoria esaurita.

Le dieci richieste dall'IP esterno `195.231.47.97` riguardano font statici e
si presentano come `Nextcloud-Server-Crawler/33.0.9`. Percorsi e user agent
non indicano da soli un attacco, ma non provano l'identità del chiamante.

Limiti: Caddy non aveva access log completi persistenti; molte richieste
Apache riportano l'IP del proxy Docker anziché quello del browser.
`admin_audit` Nextcloud era disabilitato. Non sono stati acquisiti log
Cloudflare, audit del control plane Tailscale o telemetria del router.
I controlli di pattern non sostituiscono un'analisi forense completa e non
rilevano ogni possibile exploit. Il confronto dell'immagine riguarda il core,
non tutti i file utente o tutte le app personalizzate.

## Log migliorati e verifiche finali

I domini pubblici Caddy ora registrano metadati HTTP in
`${DATA_DIR}/caddy/data/security-access.jsonl`, già persistente nel mount
`/data`. Permessi 0600; rotazione a 10 MiB, massimo dieci archivi, con limite
temporale di 14 giorni per gli archivi al momento della rotazione. Il file
corrente non ha una scadenza temporale automatica.

URI, query string, header della richiesta e della risposta sono eliminati
dall'access log per evitare di conservare token di condivisione, cookie e
credenziali. Restano metodo, host, stato, tempi e IP; `edge_client_ip` riporta
il valore comunicato da Cloudflare, usato solo come metadato. Non è una nuova
regola di autorizzazione e non rende questi log una traccia completa dei
percorsi richiesti. Il filtro riguarda gli access log, non ogni log di errore
applicativo o di runtime.

Verifiche completate:

- validazione e reload Caddy; prova HTTP 404 con cookie/query diagnostici e
  controllo della loro assenza dal log;
- test delle condivisioni pubbliche (9), Office pubblico (2) e recovery
  ONLYOFFICE (3; eseguiti su Linux);
- verifica HTTP pubblica degli asset Office, route private, scritture pubbliche,
  cache non firmate e token non validi;
- stato Nextcloud e PHP del servizio web e cron;
- listener NFS/RPC, versioni abilitate e riconnessione del client.

## Backup e ripristino

Backup sul mini-PC, directory 0700 e file 0600:

```text
/home/tommaso/service-backups/php-audit-20261022/
```

Contiene dump PostgreSQL, archivio dell'applicazione precedente **esclusi i
file utente nella directory data**, configurazione `.env`, inventario dei
container e log Apache precedenti. Non committare questi file: possono
contenere segreti. Le vecchie immagini sono conservate, ma non vanno
riavviate esposte alla rete perché contengono PHP vulnerabile.

Dopo le migrazioni il rollback richiede ripristino coerente di database e
applicazione dal backup; non basta cambiare il tag immagine. Il backup locale
di emergenza non sostituisce Restic né il backup separato dei file utente.

Le configurazioni NFS precedenti sono conservate in directory root-only
`/root/nfs-security-before-*`. Per un rollback NFS rivedere i drop-in salvati,
il masking di `rpc-statd.service` e i requisiti dei client prima del riavvio.

## Fonti

- [PHP: avviso e versioni corrette del 21 ottobre 2026](https://www.php.net/archive/2026.php)
- [CERT-EU 2026-018](https://cert.europa.eu/publications/security-advisories/2026-018)
- [Pi-hole: webserver FTL](https://docs.pi-hole.net/ftldns/webserver/)
- [Nextcloud Docker: aggiornamenti e digest](https://github.com/nextcloud/docker/wiki)
- [Caddy: access log, filtri e rotazione](https://caddyserver.com/docs/caddyfile/directives/log)
