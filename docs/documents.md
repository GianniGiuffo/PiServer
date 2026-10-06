# File e documenti sul mini PC

Stirling PDF e ONLYOFFICE Docs sono servizi core Docker sull'SSD del Dell.
La Homepage del mini PC contiene **File e documenti** con Nextcloud e i due
strumenti. La Homepage di `rack-pi` non viene modificata.

| Servizio | URL Tailnet | Backend sul mini PC |
| --- | --- | --- |
| Nextcloud | `https://TAILSCALE_FQDN:8445/` | configurazione esistente |
| Stirling PDF | `https://TAILSCALE_FQDN:8463/` | `127.0.0.1:8087` |
| ONLYOFFICE Docs | `https://TAILSCALE_FQDN:8464/` | `127.0.0.1:8088` |

I due nuovi servizi sono accessibili solo tramite Tailscale Serve: nessuna
porta aperta sul router, nessuna route Cloudflare e nessun Funnel.
Stirling richiede il login; l'editor Office usa gli account Nextcloud.
La card ONLYOFFICE apre la pagina File Nextcloud: aprire o creare un `.docx`,
`.xlsx` o `.pptx` per avviare l'editor. L'URL 8464 serve l'editor e la pagina
di stato, non un gestore autonomo dei documenti.

## Installazione e integrazione

In `.env` impostare `STIRLING_PDF_IMAGE`, `ONLYOFFICE_IMAGE` alle versioni
revisionate di `.env.example` e generare `ONLYOFFICE_JWT_SECRET` con
`openssl rand -hex 32`. Il segreto non deve essere salvato in Git o mostrato
nei log. Conservare la `.env` con permessi 0600. Non eseguire `source .env`.

Dal checkout sul mini PC:

```bash
python3 scripts/configure-stirling-login.py --prepare
docker compose config --quiet
docker compose pull stirling-pdf onlyoffice
bash scripts/install-stirling-ocr.sh
docker compose up -d --no-deps stirling-pdf onlyoffice
sudo bash scripts/configure-tailscale-serve.sh
# Attendere che entrambi i container siano healthy.
python3 scripts/configure-onlyoffice.py
python3 scripts/configure-stirling-login.py
docker compose restart homepage
```

Su un server esistente si possono aggiungere solo le nuove route, senza
resettare quelle già presenti:

```bash
tailscale serve --bg --https=8463 --set-path=/ http://127.0.0.1:8087
tailscale serve --bg --https=8464 --set-path=/ http://127.0.0.1:8088
```

Questi comandi richiedono root oppure un operatore Tailscale già abilitato
con `sudo tailscale set --operator=tommaso`.

Lo script Python installa/abilita il connettore Nextcloud, registra gli URL
esterno HTTPS e interni `http://onlyoffice/` e `http://nextcloud/`, aggiunge
`nextcloud` ai trusted domain e trasmette il JWT a PHP tramite stdin.
Consente le richieste private nel solo connettore e mantiene la verifica TLS.
Il Document Server usa `JWT_ENABLED=true` e header `AuthorizationJwt`;
la stessa configurazione viene registrata nel connettore.
L'app demo ONLYOFFICE e i servizi AI cloud non sono necessari.

### Login amministratore Stirling

Prima di validare o avviare Compose, preparare la password privata:

```bash
python3 scripts/configure-stirling-login.py --prepare
```

Lo script genera `STIRLING_ADMIN_USERNAME=admin` e una password casuale in
`STIRLING_ADMIN_PASSWORD`, senza stamparla. Una `.env` già configurata viene
conservata. Compose abilita `SECURITY_ENABLELOGIN=true`,
`DISABLE_ADDITIONAL_FEATURES=false` e disabilita la registrazione libera.
Le variabili `SECURITY_INITIALLOGIN_*` si applicano solo a un database nuovo.
Per migrare l'account preesistente `admin/stirling`, dopo che Stirling è healthy:

```bash
python3 scripts/configure-stirling-login.py
```

La migrazione usa l'API ufficiale di cambio password e verifica il nuovo
accesso amministratore. Non reimposta password personalizzate sconosciute.
Su un database nuovo Stirling può richiedere un ulteriore cambio al primo accesso:
conservare poi la password personale nel proprio password manager.
Per leggere la credenziale iniziale da un terminale privato:

```bash
ssh tommaso@mini-pc "sed -n '/^STIRLING_ADMIN_/p' /opt/raspberry-server/.env"
```

Non condividere l'output in chat o nei log. Aprire Stirling dalla card Homepage
e accedere come `admin` per visualizzare le impostazioni amministrative.

Stirling usa l'immagine Full con LibreOffice, Tesseract, OCRmyPDF, Ghostscript,
QPDF e Calibre. Lo script OCR installa `eng`, `ita` e `osd` dalla release
upstream `tessdata_fast/4.1.0`; `TESSDATA_PREFIX` e `SYSTEM_TESSDATADIR`
puntano al volume `/usr/share/tessdata`. Per OCR scegliere italiano, inglese
o entrambi nell'interfaccia. Le configurazioni sono in
`/srv/raspberry-server/data/stirling-pdf/configs`.

## Risorse e disponibilità

| Limite | Stirling PDF | ONLYOFFICE Docs |
| --- | --- | --- |
| RAM massima | 2 GiB | 4 GiB |
| Soglia morbida RAM | 512 MiB | 1 GiB |
| CPU massima | 1 core | 1 core |
| Priorità CPU relativa | 256 | 256 |
| Swap consentita al container | 0 | 0 |

Il Dell ha 16 GB RAM e già circa 12 GB di swap su `/dev/sda3`: non occorre
aggiungerne. `memswap_limit` uguale a `mem_limit` impedisce a questi due
container di generare traffico di swap. Stirling limita l'heap Java a 768 MiB,
i thread Tesseract a uno e ciascun gruppo di processi esterni a una sessione.
Richieste pesanti possono attendere o superare i limiti: usare documenti
moderati ed evitare elaborazioni simultanee molto grandi.
I limiti riducono la contesa ma non garantiscono assenza di ogni rallentamento
quando il server è già saturo; verificare con `docker stats`.

Entrambi usano `restart: unless-stopped` e rientrano nello stack core e nella
sua unità systemd. L'editing Office richiede anche Nextcloud e lo storage
montato. Aggiornamenti: backup verificato, modifica delle versioni in `.env`,
pull e ricreazione dei soli servizi; nessun aggiornamento automatico.

## Verifica

```bash
docker compose ps stirling-pdf onlyoffice
curl --fail http://127.0.0.1:8087/api/v1/info/status
curl --fail http://127.0.0.1:8088/healthcheck
docker compose exec -T stirling-pdf tesseract --list-langs
docker compose -f compose.yaml -f compose.media.yaml exec -T \
  --user www-data nextcloud php occ onlyoffice:documentserver --check
tailscale serve status
docker stats --no-stream
```

Da un altro client Tailscale aprire Stirling e un documento Office Nextcloud.
Verificare caricamento, modifica e salvataggio, poi OCR di una scansione con
testo italiano e conversione di un documento Office in PDF.
Le porte Docker 8087 e 8088 devono risultare pubblicate solo su `127.0.0.1`.

## Backup

`scripts/backup.sh` include `stirling-pdf/configs`, le definizioni sotto
`stirling-pdf/pipeline/defaultWebUIConfigs`, `onlyoffice/data`, il JWT nella
`.env`. ONLYOFFICE 9.3.1 usa PostgreSQL incorporato: `onlyoffice.sql` è un dump
coerente delle tabelle di collaborazione. La directory live `onlyoffice/postgresql`
non viene copiata da Restic; Redis/RabbitMQ e cache sono ricostruibili.
Gli originali risiedono in Nextcloud.
Il connettore entra nel backup delle app custom e nel dump DB Nextcloud.
Stirling viene fermato per la coerenza del database e riavviato anche in
caso di errore. Log, heap dump, dati OCR scaricabili, cache e output documenti
sono esclusi. I file Nextcloud sotto `/srv/media` restano esclusi.

## Ripristino

Ripristinare prima `.env`, configurazione e DB Nextcloud dallo stesso snapshot,
seguendo [backup-and-restore.md](backup-and-restore.md). A servizi documenti
fermi, copiare le directory salvate:

```bash
docker compose stop stirling-pdf onlyoffice
sudo rsync -a /srv/restore/srv/raspberry-server/data/stirling-pdf/configs/ \
  /srv/raspberry-server/data/stirling-pdf/configs/
sudo rsync -a /srv/restore/srv/raspberry-server/data/onlyoffice/data/ \
  /srv/raspberry-server/data/onlyoffice/data/
# Se presente, ripristinare anche pipeline/defaultWebUIConfigs.
bash scripts/install-stirling-ocr.sh
docker compose up -d --no-deps onlyoffice stirling-pdf
# Attendere che i due servizi siano healthy prima di verificare il connettore.
python3 scripts/configure-onlyoffice.py
```

Per ripristinare anche lo stato SQL di ONLYOFFICE, dopo l'inizializzazione
del container e prima di consentire sessioni di editing:

```bash
docker compose exec -T onlyoffice supervisorctl stop ds:docservice ds:converter
docker compose exec -T --user postgres onlyoffice psql -v ON_ERROR_STOP=1 \
  -d onlyoffice -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public AUTHORIZATION onlyoffice;'
cat /srv/restore/srv/raspberry-server/staging/onlyoffice.sql | \
  docker compose exec -T --user postgres onlyoffice psql -v ON_ERROR_STOP=1 -d onlyoffice
docker compose exec -T onlyoffice supervisorctl start ds:docservice ds:converter
```

Usare il percorso effettivo di `STAGING_DIR` presente nello snapshot. Il dump
non contiene gli originali Nextcloud, che restano esclusi dal backup.

Gli originali rimangono in Nextcloud; il restore dello stato non ricrea file
utente o cache di editing esclusi. Eseguire nuovamente le verifiche prima
di eliminare lo snapshot o la directory di restore.

## Caricamento editor e CPU

Il 6 ottobre 2026 il browser ha riprodotto un blocco del frontend 9.4.0:
`Common.Utils.applicationPixelRatio is not a function` in `DimensionPicker.js`.
La [segnalazione upstream 3815](https://github.com/ONLYOFFICE/DocumentServer/issues/3815)
descrive altri blocchi intermittenti nella stessa fase RequireJS. Per evitare
questa regressione è fissata l'immagine ufficiale 9.3.1, con frontend compilato.
Prima di avanzare a una nuova versione verificare l'editor completo, non solo
`healthcheck` o `occ onlyoffice:documentserver --check`.

Il connettore ONLYOFFICE è già installato: non occorre un'altra estensione
Nextcloud per aprire DOCX/XLSX/PPTX. Se una scheda era già bloccata, chiuderla
e riaprire il file; ricaricare forzatamente per eliminare gli asset della versione
precedente. Un documento di prova deve aprirsi, accettare modifiche e risultare
aggiornato anche dopo la chiusura e riapertura.

Al primo avvio o dopo la ricreazione dell'immagine, ONLYOFFICE genera font,
temi e cache JavaScript: può occupare il core assegnato per diversi minuti e
riavviare internamente l'editor. La metrica Docker del 100% equivale a un core.
Il limite CPU e la bassa priorità relativa restano attivi; non aumentare le
risorse per tentare di risolvere un errore JavaScript.

Verifiche del 6 ottobre 2026: editor 9.3.1 aperto nel browser via Tailscale,
DOCX sintetico modificato, chiuso e testo verificato nel file Nextcloud via
WebDAV; dump PostgreSQL ripristinato in un database temporaneo (2 tabelle).
Stirling mostra il login, rifiuta la conversione anonima con HTTP 401 e
converte DOCX in PDF con account admin (HTTP 200). Porte Docker pubblicate
solo su loopback, RAM/CPU/swap verificati e Funnel disabilitato.
Terminata la preparazione iniziale, ONLYOFFICE è stato misurato a circa
0,3% CPU e 1,02 GiB RAM, entro il limite di 4 GiB.
Non è stato eseguito un nuovo trasferimento Restic completo durante questa
diagnosi: il prossimo backup pianificato include i nuovi percorsi e il dump.
