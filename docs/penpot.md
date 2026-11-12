# Penpot sul mini PC

Penpot gira nello stack `core` e si apre su `https://TAILSCALE_FQDN:8470/`.
Tailscale Serve termina HTTPS e inoltra a `127.0.0.1:9001`. Solo il frontend
pubblica una porta host, su loopback. Le registrazioni sono chiuse e il login
usa email e password. Brevo consegna inviti, verifica email e recupero
password quando SMTP è configurato. La scheda **Penpot** è in **File e
documenti** sulla Homepage del mini PC.

## Installazione

Prima di usare il Compose aggiornato, aggiungere al `.env` del mini PC le
cinque variabili `PENPOT_*_IMAGE` da `.env.example`. Generare valori distinti
per `PENPOT_DB_PASSWORD` con `openssl rand -hex 32` e `PENPOT_SECRET_KEY` con
`python3 -c 'import secrets; print(secrets.token_urlsafe(64))'`. Conservare il
file con permessi `0600`.

Da `/opt/raspberry-server` scaricare le immagini, inizializzare il proprietario
del bind mount degli asset e avviare i servizi:

```bash
docker compose config --quiet
docker compose pull penpot-frontend penpot-backend penpot-exporter penpot-postgres penpot-valkey
docker compose run --rm --no-deps --user 0 --entrypoint chown \
  penpot-backend penpot:penpot /opt/data/assets
docker compose up -d penpot-frontend
docker compose restart homepage
tailscale serve --bg --https=8470 --set-path=/ http://127.0.0.1:9001
```

Usare `sudo` per il comando Tailscale se l'utente SSH non è l'operatore del
nodo. Attendere che `curl -fsS http://127.0.0.1:9001/readyz` risponda prima di
creare un account. Eseguire il comando seguente da un terminale interattivo e
inserire la password quando viene richiesta:

```bash
docker compose exec penpot-backend python3 manage.py create-profile -n admin -e EMAIL
```

Per impostare una nuova password di un account esistente, usare
`docker compose exec penpot-backend python3 manage.py update-profile -e EMAIL`.

## Collaboratori esterni

Gli invitati usano `https://penpot.tommasofrancescon.it` tramite Cloudflare
Tunnel e accedono a Penpot con email e password. La stessa istanza si apre
direttamente in Tailscale su `https://TAILSCALE_FQDN:8470/`. Penpot consente
di registrarsi solo tramite un invito valido e verifica l'indirizzo dei
nuovi account via Brevo.

1. In Brevo aprire **Settings → Senders, Domains, IPs → Domains**.
   Aggiungere e autenticare `tommasofrancescon.it` con i record DNS
   mostrati da Brevo. Se il dominio ha già un record DMARC, usare il
   record esistente e aggiornarlo secondo le indicazioni di Brevo.
   In **Senders** creare il mittente, per esempio
   `penpot@tommasofrancescon.it`, e completare l'eventuale verifica.
   [Autenticare il dominio in Brevo](https://help.brevo.com/hc/en-us/articles/12163873383186-Authenticate-your-domain-with-Brevo-Brevo-code-DKIM-DMARC)
2. In **Settings → SMTP & API → SMTP** copiare il **Login** e generare
   una **chiave SMTP** dedicata a Penpot. Inserire i valori nel
   `.env` del mini PC con permessi `0600`.

   ```dotenv
   PENPOT_PUBLIC_DOMAIN=penpot.tommasofrancescon.it
   PENPOT_SMTP_FLAG=enable-smtp
   PENPOT_SMTP_USERNAME=LOGIN_SMTP_BREVO
   PENPOT_SMTP_PASSWORD='CHIAVE_SMTP_BREVO'
   PENPOT_SMTP_DEFAULT_FROM=penpot@tommasofrancescon.it
   PENPOT_SMTP_DEFAULT_REPLY_TO=penpot@tommasofrancescon.it
   ```

   Usare il mittente registrato in Brevo. Il campo `REPLY_TO` è facoltativo.
   Il Compose usa `smtp-relay.brevo.com:587` con STARTTLS. Applicare la
   configurazione dal repository sul mini PC. [Configurazione SMTP Brevo](https://help.brevo.com/hc/en-us/articles/7924908994450-Send-transactional-emails-using-Brevo-SMTP)

   ```bash
   docker compose config --quiet
   docker compose up -d --no-deps caddy penpot-backend penpot-exporter penpot-frontend
   curl -fsS http://127.0.0.1:9001/readyz
   ```

3. In Penpot, dal team che contiene il file da condividere, usare
   **Invite to team → Editor → Send invitation**. Penpot spedisce via
   Brevo un link con il sottodominio pubblico anche quando l'invito
   parte dalla scheda Tailscale. Per il collaudo usare un proprio indirizzo
   che non ha ancora un account Penpot, controllare che arrivi il link
   e verificare che il nuovo account richieda la conferma via email.
   Per una migrazione, lasciare attivo Cloudflare Access durante questa
   prova e usare un indirizzo di test già autorizzato in Access.
4. In Cloudflare aprire **Networking → Tunnels → tunnel del mini PC →
   Routes**. Sulla route `penpot.tommasofrancescon.it`, lasciare il percorso
   vuoto e il servizio su `http://caddy:8089`. In **Additional application
   settings → Access** disattivare **Protect with Access** e salvare la
   route. In **Access controls → Applications** rimuovere l'app Access
   dedicata a Penpot o togliere l'hostname Penpot da quell'app se copre
   anche altri servizi. Mantenere la route pubblicata e il suo record DNS.
   [Parametri Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/origin-parameters/#access)
5. Da una finestra privata fuori Tailscale aprire il sottodominio.
   Deve comparire il login Penpot. Ripetere la prova con un nuovo invitato
   e verificare che, dopo la conferma email, acceda solo ai team di cui fa
   parte. Per revocare un accesso, annullare l'invito in attesa o
   rimuovere il membro dal team.

Per disattivare l'ingresso esterno, rimuovere la route pubblicata. Togliere
poi `PENPOT_PUBLIC_DOMAIN` da `.env` e ricreare i quattro servizi indicati
sopra per tornare agli inviti con URL Tailscale.

## Monitoraggio

In Uptime Kuma su `rack-pi`, aggiungere un monitor **HTTP(s)** chiamato
**Penpot**, su `https://MINIPC_TAILSCALE_FQDN:8470/readyz`. Usare il nome
MagicDNS del mini PC già configurato in `rack-pi/.env` e lasciare attiva la
verifica del certificato. Lo stesso endpoint è usato dalla Homepage del mini PC
attraverso la rete Docker.

## Aggiornamenti

Renovate legge `.env.example` su `master` e propone PR con le notifiche
Telegram già configurate. Prima di portare nel `.env` locale le versioni
approvate, verificare lo snapshot Restic e controllare che frontend, backend
ed exporter abbiano la stessa versione. Verificare le note di rilascio prima
di aggiornare PostgreSQL o Valkey, in particolare se si cambia il tag.
Scaricare e ricreare solo i cinque container Penpot e verificare `/readyz`.

## Ripristino

Il backup Restic `pi-server` salva il dump logico in `STAGING_DIR/penpot/penpot.dump`,
gli oggetti persistenti in `STAGING_DIR/penpot/assets`, il `.env` con i segreti,
il Compose, il Caddyfile e lo script delle route Tailscale. Il backend resta fermo durante
il dump e la copia locale degli asset. La directory di staging viene rimossa
dopo il backup. Lo staging richiede spazio per una copia degli asset sul SSD.
Valkey usa memoria e contiene notifiche e job di esportazione in corso.

1. Estrarre lo snapshot con la [procedura Restic](backup-and-restore.md) e
   verificare che contenga `penpot.dump`, `penpot/assets` e la configurazione.
2. Ripristinare le variabili `PENPOT_*` dal `.env` dello stesso snapshot.
   Partire con la versione Penpot e la major PostgreSQL dello snapshot.
3. Su un'installazione vuota, avviare solo `penpot-postgres` e `penpot-valkey`
   con `docker compose up -d --wait penpot-postgres penpot-valkey`. Se si
   ripristina su un'installazione esistente, conservare i dati correnti e
   usare un database vuoto e una directory asset vuota per il ripristino.
4. Copiare gli asset ripristinati nella directory `${DATA_DIR}/penpot/assets`
   con `sudo rsync -aHAX --numeric-ids`, mantenendo proprietario e permessi.
   Importare il dump nel database `penpot` prima di avviare il backend:

   ```bash
   docker compose exec -T penpot-postgres \
     pg_restore --exit-on-error --single-transaction -U penpot -d penpot < /percorso/penpot.dump
   ```

5. Avviare `docker compose up -d penpot-frontend`, ripristinare la route Serve
   e verificare `/readyz`, il login e l'apertura di un progetto con asset.

[Documentazione ufficiale Penpot](https://help.penpot.app/technical-guide/configuration/)
