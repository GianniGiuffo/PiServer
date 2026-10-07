# Renovate sul Raspberry, proposte per il mini-PC

Renovate OSS CLI di Mend gira in un container arm64 sul Raspberry Pi 4
`rack-pi`. Legge soltanto le immagini del mini-PC in `.env.example` su
`GianniGiuffo/PiServer:master`. Propone aggiornamenti con commit sui branch
`renovate/*` e PR verso `master`. Non approva e non fa merge. Non accede
al mini-PC, al socket Docker, alle chiavi SSH o ai file `.env` dei servizi.

**Il merge della PR non aggiorna i servizi.** Le versioni di produzione sono
nel `.env` locale non versionato: riportare manualmente solo le variabili
approvate dopo la revisione, quindi eseguire backup, pull e ricreazione.
Renovate confronta il riferimento in Git; se produzione diverge da
`.env.example`, riallineare manualmente il riferimento non segreto prima
di interpretare le notifiche come aggiornamenti della produzione.

## Politica delle proposte

- Tutti i servizi nei tre Compose del mini-PC sono rilevati; i servizi
  esclusivi del Raspberry e le dipendenze dei moduli locali sono fuori scope.
- Anche le versioni selezionate appositamente ricevono proposte. Una PR non
  autorizza l'aggiornamento e non verifica la compatibilitÃ  delle patch.
- Aurral ha un avviso specifico: rivedere
  [patch e mount](../patches/aurral/README.md#aggiornare-aurral) prima del merge.
  Il bot cambia solo il riferimento dell'immagine, mai i moduli locali.
- Le immagini database Immich richiedono il controllo del Compose ufficiale
  e delle estensioni insieme alla versione del server.
- `pinDigests` propone di fissare il digest iniziale anche per `latest` e
  `nightly`. Dopo il merge nel riferimento Git, le nuove build di quei tag
  generano PR di aggiornamento digest. Il primo pin non Ã¨ una nuova release.
  I tag mobili restano sul canale scelto, senza passaggio automatico a stable.
- Renovate seleziona le versioni secondo il formato dei tag e le varianti
  compatibili (per esempio alpine/apache). Non Ã¨ un elenco di ogni release
  upstream e non interroga le versioni dei container in esecuzione.
- Nessun limite orario o di PR concorrenti: ogni proposta puÃ² avere una PR.
  Una PR chiusa senza merge puÃ² essere ignorata da Renovate finchÃ© non cambia
  versione; il Dependency Dashboard permette di richiederla nuovamente.

`renovate.json` contiene la politica revisionabile. Il runner monta questo
file e `rack-pi/config/renovate.cjs` in sola lettura; la configurazione globale
usa esclusivamente questa copia locale e ignora eventuali configurazioni
remote. Il suo `force` e i flag CLI disabilitano automerge e auto-approvazione.
Quando cambi la politica, aggiorna manualmente la copia sul Raspberry.

## Credenziali GitHub e StatusBot

Creare un fine-grained PAT per la sola repository `GianniGiuffo/PiServer`,
preferibilmente di un account bot dedicato con accesso alla repo:

- Metadata e Dependabot alerts: lettura;
- Commit statuses: lettura e scrittura;
- Contents: lettura e scrittura, per i soli branch delle proposte;
- Pull requests: lettura e scrittura, per aprire e aggiornare le PR;
- Issues: lettura e scrittura, per il Dependency Dashboard.

Non servono permessi Administration, Actions o Workflows. GitHub non offre
in questi permessi PAT un divieto del solo merge: le protezioni effettive
devono anche impedire al bot di scrivere direttamente su `master` o saltare
le revisioni. Configurare su GitHub una ruleset/protezione di `master` con
PR e revisione obbligatoria e senza bypass del bot. Per impedire anche
l'approvazione tramite permessi di piattaforma sarebbe necessaria una
gestione diversa: Pull requests write consente operazioni sulle review.
Questa installazione non chiama endpoint di review o merge.

In Uptime Kuma aprire la notifica `StatusBot Â· rack-pi` e copiare il token e
il chat ID esistenti nel file locale descritto sotto. Non esportare nÃ© leggere
automaticamente il database Kuma. Il mittente Telegram resta StatusBot; i
messaggi iniziano con `Origine: rack-pi` e `Renovate Â· mini-pc`.

## Installazione e prima verifica

La preparazione del 7 ottobre 2026 ha installato una copia separata in
`/opt/rack-pi-renovate`, senza modificare il checkout di produzione
`/opt/raspberry-server`. Le unità fanno riferimento a questa copia e il timer
resta disabilitato finché credenziali e dry run non sono verificati. Per questa
installazione usare `/opt/rack-pi-renovate` nei comandi qui sotto. La copia non
esegue pull automatici: dopo un merge della configurazione, aggiornare
manualmente anche i file del runner e della politica in questa directory.

I comandi seguenti descrivono invece l'installazione riproducibile dalla repo
principale, dopo il merge; reinstallando le unità da lì il loro percorso
punterà alla copia sotto `/opt/raspberry-server`.

Dopo aver revisionato e portato queste modifiche su `master`, sul Raspberry:

```bash
cd /opt/raspberry-server
git switch master
git pull --ff-only
sudo bash rack-pi/scripts/install-renovate.sh
sudo nano /etc/rack-pi/renovate.env
sudo chmod 600 /etc/rack-pi/renovate.env
```

L'installer non avvia controlli, non abilita il timer e conserva le credenziali
preesistenti. Compilare `RENOVATE_TOKEN`, `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID` ed eventualmente `TELEGRAM_MESSAGE_THREAD_ID`.
L'immagine del bot Ã¨ fissata a una release esplicita; cambiarla manualmente
solo dopo la validazione. Docker scarica l'immagine al primo run.

Prima eseguire un controllo senza scritture GitHub e senza notifiche:

```bash
sudo python3 rack-pi/scripts/run-renovate.py --dry-run
sudo less /var/lib/rack-pi-renovate/renovate.log
```

Il dry run usa la cache locale e non crea branch, PR o issue. Poi avviare il
servizio una volta: questo crea le proposte e invia le notifiche reali.

```bash
sudo systemctl start rack-renovate.service
sudo journalctl -u rack-renovate -n 50 --no-pager
```

Verificare PR e messaggi di StatusBot prima di attivare la pianificazione:

```bash
sudo systemctl enable --now rack-renovate.timer
systemctl list-timers rack-renovate.timer
```

Il controllo parte ogni giorno alle 10:00 Europe/Rome con ritardo casuale fino
a 15 minuti. `Persistent=true` recupera un controllo saltato durante lo
spegnimento. Per fermare la pianificazione:
`sudo systemctl disable --now rack-renovate.timer`.
Per interrompere anche un controllo attivo:
`sudo systemctl stop rack-renovate.service`.

## Homepage del Raspberry

La scheda **Renovate** nel gruppo **Servizi rack** apre le PR di PiServer.
Il widget usa l'API locale `/renovate` per mostrare stato, ultimo controllo
(in Europe/Rome) e numero di PR aperte del bot. Il file pubblico
`/srv/rack-pi/data/monitoring/renovate.json` contiene solo questi riepiloghi:
token e stato delle notifiche restano nei percorsi privati. Il container del
bot parte solo durante i controlli, perciò la scheda non lo considera un
servizio Docker che deve restare acceso.

## Notifiche e stato

Il runner legge i log JSON di lookup della release fissata di Renovate per
notificare versioni/build nuove, anche se la successiva creazione della PR
fallisce. Legge via API GitHub tutte le pagine delle PR aperte su
`master` provenienti da `renovate/*` nella stessa repository e segnala le
nuove PR o le proposte cambiate. Un semplice rebase non genera notifiche.

Le notifiche sono raggruppate e confermate in
`/var/lib/rack-pi-renovate/notifications.json` soltanto dopo il successo
dell'invio Telegram. Le proposte giÃ  segnalate restano silenziose, anche dopo
un riavvio. Un errore di invio viene ritentato al controllo successivo; un
errore persistente del controllo Ã¨ notificato una volta e seguito da un
messaggio di ripristino quando torna operativo. Se Telegram stesso Ã¨
irraggiungibile, il journal registra l'errore senza token.

Cache e checkout del bot sono separati dalla copia di deploy. Il container
riceve il solo token GitHub, fino a 1,5 GB RAM e 1,5 CPU, senza socket Docker
o credenziali Telegram. L'host usa il client Docker soltanto per questo
container. Un timeout interrompe il container; un lock impedisce controlli
manuali contemporanei al timer. L'ultimo log viene sostituito a ogni run.

Il parser dei log Ã¨ legato alla release esplicita: dopo un cambio di versione
verificare che il dry run rilevi il record `packageFiles with updates`.
Un record assente rende il controllo fallito, anzichÃ© silenziosamente vuoto.
Credenziali e stato delle notifiche sono in `/etc/rack-pi` e
`/var/lib/rack-pi-renovate`: il backup locale giÃ  salva `/etc/rack-pi`;
la cache Ã¨ ricostruibile. Se si perde lo stato notifiche, il primo controllo
ripete gli avvisi delle proposte ancora presenti.

## Merge e deploy di una proposta

1. Leggere release notes, diff e avvisi di compatibilitÃ  della PR.
2. Per Aurral adattare le patch e i mount nella stessa proposta prima del merge.
3. Approvare e unire manualmente su GitHub.
4. Sul mini-PC aggiornare soltanto `master`, eseguire un backup Restic
   riuscito e riportare nel `.env` le sole variabili immagine approvate.
5. Usare `bash scripts/update-images.sh core` (oppure `media`/`automation`),
   ricreare lo stack e verificare i servizi. Nessun passaggio Ã¨ avviato dal bot.

Riferimenti:
[Renovate self-hosted](https://docs.renovatebot.com/getting-started/running/),
[manager regex](https://docs.renovatebot.com/modules/manager/regex/),
[configurazione globale](https://docs.renovatebot.com/self-hosted-configuration/).
