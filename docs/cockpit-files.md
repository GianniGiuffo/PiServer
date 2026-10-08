# Cockpit Files: gestione amministrativa del mini PC

Cockpit Files viene installato direttamente su Debian 13, con pacchetti ufficiali
`trixie-backports`. Il file manager vede il filesystem del mini PC: sistema,
configurazioni, dati Docker sull'SSD e dischi montati. L'editor integrato gestisce
file di testo, compresi i file di configurazione. I filesystem remoti o montati
in sola lettura restano soggetti ai relativi permessi.

L'accesso web usa esclusivamente Tailscale Serve HTTPS sulla porta **8465**.
Cockpit ascolta solo su `127.0.0.1:9090`; nessuna route Cloudflare, Funnel, apertura
LAN o inoltro sul router. Le regole di accesso della Tailnet continuano a valere.
Il login Cockpit richiede anche l'account e la password Linux. Non configura
SMB, NFS, condivisioni NAS o account pubblici.

## Applicare dopo il merge della PR

Sul solo mini PC, con checkout pulito e aggiornato:

```bash
cd /opt/raspberry-server
git pull --ff-only
sudo bash scripts/install-cockpit-files.sh tommaso
docker compose up -d --force-recreate monitoring-api homepage
```

L'installer verifica Debian 13, l'utente amministratore, il FQDN della
`.env` e l'identità Tailscale del server. Aggiunge i backports solo se mancanti,
installa `cockpit-ws`, `cockpit-bridge`, `cockpit-system` e `cockpit-files` senza pacchetti
raccomandati, configura il socket locale **prima** dell'installazione e aggiunge
solo la route 8465, preservando tutte le altre route Serve.
Rifiuta una route 8465 occupata da un altro servizio o con Funnel attivo.
Il pacchetto `cockpit-system` fornisce la shell web necessaria a Files e include
le pagine di amministrazione di base; la card apre comunque direttamente Files.
Non cambia password, gruppi o regole sudo. Può essere rieseguito.

Aprire la card **Cockpit Files** in **Automazione e controllo** su Homepage del
mini PC. Il collegamento porta direttamente a `/files/` in una nuova scheda.
Accedere come `tommaso` e attivare **Accesso amministrativo** nella barra Cockpit;
usare la password Linux se richiesta. Le operazioni elevate avvengono con
privilegi root. Il login diretto `root` resta bloccato in
`/etc/cockpit/disallowed-users`; gli altri divieti esistenti vengono conservati.

## Stato e statistiche

`cockpit-status.timer` raccoglie i dati ogni 15 secondi attraverso un processo
host. Scrive atomicamente `DATA_DIR/monitoring/cockpit.json`, leggibile dalla
monitoring API già esistente. Homepage e la monitoring API non ricevono socket
systemd, password Linux, accesso root o una sessione Cockpit.

- **Verde / Disponibile:** Files è installato, il socket è attivo, il backend
  risponde come Cockpit e la route Serve è privata con listener solo loopback.
- **Giallo:** controlli/statistiche incompleti, snapshot mancante, invalido o più
  vecchio di 45 secondi. Prima dell'installazione indica “Da configurare”.
- **Rosso / Non disponibile:** Files manca, il socket è fermo, la UI non risponde
  oppure l'esposizione non corrisponde al confine privato previsto.

Homepage aggiorna widget e indicatore ogni cinque secondi. L'indicatore usa
il normale punto della card con i tre colori, sincronizzato al campo Stato.
Cockpit usa socket activation: il processo web inattivo non è un guasto;
il probe locale `/ping` lo avvia su richiesta.

CPU e RAM sono la somma dei processi Cockpit web/session/bridge, comprese le
sessioni elevate, **non** dell'intero server e non dei programmi avviati dal
terminale. La CPU è campionata per un secondo e normalizzata sulla capacità di
tutti i core (0–100%); RAM è la somma RSS dei processi e può includere memoria
condivisa. Spazio libero e utilizzo riguardano il filesystem `/` sull'SSD,
includendo la riserva del filesystem nello spazio non disponibile all'utente.
Non vengono conteggiati o scanditi i file di `/srv/media`.
La card non viene aggiunta alla Homepage di rack-pi.

## Verifiche dopo l'installazione

```bash
systemctl status cockpit.socket cockpit-status.timer --no-pager
sudo systemctl start cockpit-status.service
sudo journalctl -u cockpit-status.service -n 30 --no-pager
ss -lnt 'sport = :9090'
tailscale serve status
cat /srv/raspberry-server/data/monitoring/cockpit.json
```

Verificare che 9090 ascolti esclusivamente su `127.0.0.1`, che 8465 sia
disponibile solo nella Tailnet e che la card apra Files. Dopo il login, verificare
lettura, creazione, modifica, spostamento e cancellazione su file **di prova**
in una directory temporanea creata con proprietario root.
Provare anche dalla LAN senza Tailscale: 9090 e l'interfaccia 8465 non devono
essere raggiungibili. Per simulare il rosso fermare `cockpit.socket` e
`cockpit.service`, poi ripristinare il socket; per il giallo fermare il timer
e attendere oltre 45 secondi, poi riavviarlo.

## Backup, restore e manutenzione

La configurazione `/etc/cockpit`, l'override
`/etc/systemd/system/cockpit.socket.d` e l'eventuale sorgente APT dedicata vengono
inclusi nei backup di stato. Le unità e gli script sono riproducibili dalla repo.
Dopo un restore ripetere l'installer e ricreare monitoring-api e Homepage.

I pacchetti vengono aggiornati soltanto tramite manutenzione APT esplicita;
questo installer non configura aggiornamenti periodici. Per aggiornarli:

```bash
sudo apt-get update
sudo apt-get install --no-install-recommends -t trixie-backports cockpit-ws cockpit-bridge cockpit-system cockpit-files
sudo systemctl restart cockpit.socket
sudo systemctl stop cockpit.service
sudo systemctl start cockpit-status.service
```

Per disattivare: `sudo tailscale serve --https=8465 off`, poi
`sudo systemctl disable --now cockpit-status.timer cockpit.socket` e
`sudo systemctl stop cockpit.service`. Rimuovere anche la route 8465 da
`scripts/configure-tailscale-serve.sh` prima di rigenerare le route globali.

Fonti: [progetto Cockpit Files](https://github.com/cockpit-project/cockpit-files),
[pacchetti Debian](https://packages.debian.org/trixie-backports/cockpit-files),
[privilegi Cockpit](https://cockpit-project.org/guide/latest/privileges),
[socket locale](https://docs.cockpit-project.org/cockpit-guide/latest/guide/listen.html),
[Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve).
