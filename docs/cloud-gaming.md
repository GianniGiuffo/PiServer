# Cloud gaming privato con Switch, Sunshine e Tailscale

Questa procedura configura il PC fisso Windows come host di gioco, la Switch
come client Tailscale/Moonlight e il mini PC Debian come controllore di
accensione e spegnimento. Non vengono aperte porte sul router e Sunshine non
passa attraverso un reverse proxy: il flusso video è diretto fra Switch e PC
Windows nella Tailnet.

Configurazione di riferimento:

- Switchroot Android 15 Tablet, Tailscale e Moonlight;
- Windows 10 Home 22H2, Intel i7-8700 e RTX 2070 Super;
- account locale standard Windows `gaming` con login automatico;
- MSI H370 Gaming Pro Carbon e PC collegato via Ethernet;
- monitor HDMI preferito per la cattura, con secondo monitor DisplayPort;
- Wake-on-LAN inviato dal mini PC;
- spegnimento manuale o dopo 30 minuti senza stream;
- controller su `https://TAILSCALE_FQDN:8455/`.

Windows 10 Home è mantenuto temporaneamente senza ESU per decisione del
proprietario. Il sistema funziona, ma rimane il rischio documentato in
[security.md](security.md): Tailscale limita l'accesso in ingresso e non
sostituisce gli aggiornamenti di sicurezza del sistema operativo.

## 1. Funzionamento e proprietà del timer

Il controller conserva soltanto stato operativo e non password Windows.

1. L'utente apre la card `Gaming PC` di Homepage e preme **Accendi**.
2. Il mini PC controlla le porte SSH e Sunshine sull'IPv4 Tailscale del fisso.
3. Se il fisso è offline invia tre magic packet al broadcast della LAN.
4. Windows esegue il login automatico dell'account `gaming`; Tailscale e
   Sunshine partono come servizi.
5. Il controller mostra **Pronto per Moonlight** quando la porta Sunshine
   risponde.
6. Una global prep command di Sunshine notifica l'inizio dello stream e mette
   in pausa il timer; l'undo command lo riavvia quando lo stream termina.
7. Dopo 30 minuti senza stream il mini PC invia via SSH il solo verbo
   `shutdown`. Un forced command sul PC rifiuta qualunque altra operazione.

Il timer si arma esclusivamente quando il Wake-on-LAN è partito dal
controller. Se il PC viene acceso dal pulsante fisico, il mini PC non lo spegne
automaticamente. Una notifica Sunshine fallita lascia il PC acceso: è un
fallimento conservativo contro gli spegnimenti accidentali.

## 2. Raccogliere i valori

### Sul mini PC

Individuare interfaccia LAN, indirizzo e broadcast:

```bash
ip -4 -br address
ip -4 address show
tailscale ip -4
tailscale status --json | jq -r '.Self.DNSName'
```

Il broadcast è il valore dopo `brd`, per esempio `192.168.1.255`. Mini PC e
PC fisso devono trovarsi nello stesso segmento Ethernet/VLAN.

### Sul PC Windows

Aprire PowerShell e annotare IPv4 Tailscale, MAC della scheda Ethernet e nome
dell'adattatore:

```powershell
tailscale ip -4
Get-NetAdapter -Physical | Format-Table Name, Status, MacAddress, LinkSpeed
```

Usare il MAC dell'adattatore Ethernet collegato, non quello Wi-Fi o Tailscale.
Nella console Tailscale è consigliabile assegnare al PC il nome
`gaming-pc`. Per un host incustodito si può disabilitare la scadenza della sua
machine key dopo avere protetto l'account Tailscale con MFA.

Annotare inoltre:

- IPv4 Tailscale del mini PC;
- IPv4 Tailscale del PC Windows;
- MagicDNS FQDN del mini PC senza punto finale;
- login Tailscale esatto usato sulla Switch, normalmente l'indirizzo email.

La Switch deve essere autenticata come normale dispositivo dello stesso
utente. Un nodo registrato con un tag non riceve da Tailscale Serve l'header
`Tailscale-User-Login` e la pagina risponderà `401`.

## 3. Preparare il controller sul mini PC

Eseguire dalla copia installata della repository. Sostituire `UTENTE_LINUX`
con l'utente amministratore normale del mini PC:

```bash
cd /opt/raspberry-server
sudo bash scripts/setup-gaming-controller.sh UTENTE_LINUX
sudo nano /etc/raspberry-server/gaming/gaming.env
```

Compilare almeno:

```ini
GAMING_PC_MAC=00:11:22:33:44:55
GAMING_PC_BROADCAST=192.168.1.255
GAMING_PC_TAILSCALE_IP=100.x.y.z
GAMING_PC_SSH_USER=gaming
GAMING_ALLOWED_TAILSCALE_LOGINS=utente@example.com
GAMING_IDLE_TIMEOUT_SECONDS=1800
```

Non modificare il bind loopback. Lo script genera:

- `id_ed25519`: chiave privata SSH del solo controller;
- `id_ed25519.pub`: parte pubblica da copiare su Windows;
- `session-token`: segreto usato soltanto dai callback Sunshine;
- `gaming.env`: valori del PC e identità autorizzata.

La chiave privata, il token e la configurazione hanno permessi ristretti e
sono inclusi nel backup Restic perché risiedono sotto
`/etc/raspberry-server`. Il servizio non viene ancora abilitato.

Trasferire in modo cifrato al PC Windows soltanto questi due file:

```text
/etc/raspberry-server/gaming/id_ed25519.pub
/etc/raspberry-server/gaming/session-token
```

Si può usare Taildrop, una chiavetta tenuta sotto controllo oppure una copia
locale via Tailscale. Eliminare dal PC i file di trasferimento dopo avere
eseguito l'installer. Non copiare mai `id_ed25519`.

## 4. Preparare BIOS e Wake-on-LAN

Nel BIOS della MSI H370 Gaming Pro Carbon aprire **Settings > Advanced > Wake
Up Event Setup** e impostare:

- `Wake Up Event By`: `BIOS`;
- `Resume By PCI-E Device`: `Enabled`.

Se presente, lasciare disabilitato `ErP Ready`, perché può togliere
alimentazione alla scheda di rete durante S5. Non cambiare altre opzioni BIOS
se il Wake-on-LAN funziona già.

In Windows aprire **Gestione dispositivi > Schede di rete > Intel Ethernet >
Proprietà**:

- in **Avanzate**, abilitare `Wake on Magic Packet`;
- in **Risparmio energia**, consentire al dispositivo di riattivare il PC;
- limitare la riattivazione al magic packet, se l'opzione è disponibile.

Per lo spegnimento completo S5, disabilitare **Avvio rapido** in **Pannello di
controllo > Opzioni risparmio energia > Specifica comportamento pulsanti di
alimentazione**. Applicare prima gli aggiornamenti dei driver Intel LAN
distribuiti da MSI/Intel e testare nuovamente dopo ogni cambiamento.

## 5. Account Windows e login automatico

Creare dalle Impostazioni un account locale chiamato `gaming`, assegnargli una
password lunga e lasciarlo nel gruppo **Users**, non **Administrators**.
Accedere almeno una volta come `gaming` affinché Windows crei il profilo, poi:

1. configurare Steam e gli altri launcher richiesti;
2. disabilitare l'avvio automatico di software non necessario;
3. installare gli aggiornamenti della RTX 2070 Super;
4. eseguire [Microsoft Sysinternals Autologon](https://learn.microsoft.com/sysinternals/downloads/autologon)
   come amministratore e registrare l'account locale `gaming`.

Autologon salva la password come segreto LSA, ma un amministratore locale può
recuperarla. L'account deve quindi essere dedicato, standard e privo di dati
personali.

Prima di proseguire, verificare direttamente dall'account `gaming` che il
diritto standard di arresto sia disponibile. Il primo comando programma lo
spegnimento, il secondo lo annulla subito:

```powershell
shutdown.exe /s /t 60
shutdown.exe /a
```

La configurazione predefinita di Windows assegna questo diritto agli utenti
locali. Se il primo comando restituisce un errore di privilegio, fermarsi e
correggere la policy locale: non aggiungere `gaming` agli amministratori e non
proseguire contando sul controller, che riceverebbe lo stesso errore.

## 6. Installare e configurare Tailscale e Sunshine su Windows

Tailscale è già presente. Verificare che il servizio parta automaticamente e
che il PC compaia online nella console dopo un riavvio.

Scaricare l'MSI corrente di Sunshine dalla
[documentazione ufficiale](https://docs.lizardbyte.dev/projects/sunshine/latest/md_docs_2getting__started.html)
e scegliere l'avvio come servizio. Per il gamepad installare il Virtual HID
Driver supportato da Sunshine oppure mantenere il fallback compatibile
Xbox 360/DS4 se adatto ai giochi utilizzati.

Aprire localmente `https://localhost:47990`, creare credenziali amministrative
uniche e impostare:

- `UPnP`: disabilitato;
- `Web UI origin`: `pc`, cioè soltanto localhost;
- porta base: predefinita `47989`;
- cifratura LAN/WAN: preferita se supportata dal client;
- avvio Sunshine al boot: abilitato.

Non installare Moonlight Internet Hosting Tool e non creare regole sul router.

### Installare il canale ristretto di spegnimento

Sul PC Windows servono cinque file, provenienti da due sorgenti diverse:

| File | Provenienza | Utilizzo |
| --- | --- | --- |
| `install-gaming-host.ps1` | repository, cartella `windows\gaming` | installer da eseguire come amministratore |
| `gaming-power.ps1` | repository, cartella `windows\gaming` | forced command che permette soltanto lo spegnimento |
| `gaming-session.ps1` | repository, cartella `windows\gaming` | notifica al mini PC l'inizio e la fine dello stream |
| `id_ed25519.pub` | generato sul mini PC | parte pubblica della chiave autorizzata su Windows |
| `session-token` | generato sul mini PC | autentica esclusivamente i callback Sunshine |

I tre file `.ps1` devono rimanere nella stessa cartella: l'installer trova gli
ultimi due relativamente alla propria posizione. Non è invece necessario
mettere `id_ed25519.pub` e `session-token` nella repository; è preferibile una
cartella temporanea separata.

Se `F:\GitHub\source\repos\PiServer` si trova già sul PC gaming, gli script
sono già disponibili qui e non bisogna copiare tutta la repository:

```text
F:\GitHub\source\repos\PiServer\windows\gaming
```

Se la repository si trova soltanto sul mini PC o su un altro computer, copiare
sul PC Windows l'intera cartella `windows\gaming`, mantenendo insieme i tre
script. Una destinazione possibile è
`C:\Users\NOME_UTENTE\Downloads\PiServerGamingScripts`.

### Copiare sul PC i due file generati dal mini PC

Creare sul PC Windows una cartella temporanea. Questa operazione può essere
eseguita da una normale finestra PowerShell:

```powershell
$SetupDir = Join-Path $env:USERPROFILE "Downloads\PiServerGamingSetup"
New-Item -ItemType Directory -Force -Path $SetupDir
```

Trasferire dal mini PC, attraverso Tailscale o con una chiavetta controllata,
soltanto:

```text
/etc/raspberry-server/gaming/id_ed25519.pub
/etc/raspberry-server/gaming/session-token
```

Per esempio, se l'accesso SSH/Tailscale al mini PC è già configurato e il
comando `scp` è disponibile su Windows:

```powershell
scp UTENTE_LINUX@mini-pc:/etc/raspberry-server/gaming/id_ed25519.pub $SetupDir
scp UTENTE_LINUX@mini-pc:/etc/raspberry-server/gaming/session-token $SetupDir
```

Sostituire `UTENTE_LINUX` con lo stesso utente passato a
`setup-gaming-controller.sh`. Se `mini-pc` non viene risolto da MagicDNS,
usare al suo posto l'IPv4 Tailscale del mini PC. Il trasferimento con `scp`
attraverso Tailscale è cifrato. Non trasferire mai il file privato
`id_ed25519`.

Verificare soltanto l'esistenza e la dimensione dei file, senza visualizzare il
contenuto del token:

```powershell
Get-Item "$SetupDir\id_ed25519.pub", "$SetupDir\session-token"
```

### Eseguire l'installer Windows

Aprire una nuova PowerShell con **Esegui come amministratore**. Copiare ed
eseguire i comandi seguenti **uno alla volta e nell'ordine indicato**. Ogni
blocco contiene intenzionalmente una sola riga, così la copia dall'interfaccia
non può invertire l'ordine e non servono backtick.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
```

```powershell
$SetupDir = Join-Path $env:USERPROFILE "Downloads\PiServerGamingSetup"
```

```powershell
Set-Location "F:\GitHub\source\repos\PiServer\windows\gaming"
```

Controllare il percorso effettivo usato dalla PowerShell amministrativa:

```powershell
$SetupDir
```

```powershell
Test-Path -LiteralPath $SetupDir
```

```powershell
Get-ChildItem -LiteralPath $SetupDir -Force -ErrorAction SilentlyContinue
```

Se la cartella restituisce `False`, crearla:

```powershell
New-Item -ItemType Directory -Force -Path $SetupDir
```

Verificare separatamente i due file richiesti:

```powershell
Test-Path -LiteralPath (Join-Path $SetupDir "id_ed25519.pub")
```

```powershell
Test-Path -LiteralPath (Join-Path $SetupDir "session-token")
```

Entrambi devono restituire `True`. Se uno restituisce `False`, non eseguire
l'installer. La PowerShell amministrativa potrebbe usare un profilo diverso
da quello dal quale sono stati scaricati i file. Cercarli senza mostrarne il
contenuto:

```powershell
Get-ChildItem "C:\Users" -Filter "id_ed25519.pub" -File -Recurse -ErrorAction SilentlyContinue
```

```powershell
Get-ChildItem "C:\Users" -Filter "session-token" -File -Recurse -ErrorAction SilentlyContinue
```

Se entrambi vengono trovati nella stessa cartella, impostare `$SetupDir` al
percorso restituito, per esempio:

```powershell
$SetupDir = "C:\Users\20tom\Downloads\PiServerGamingSetup"
```

Se non vengono trovati, trasferirli dal mini PC. Verificare prima che il client
OpenSSH di Windows fornisca `scp`:

```powershell
Get-Command scp
```

Con il mini PC raggiungibile all'IPv4 Tailscale `100.95.133.122`, sostituire
`UTENTE_LINUX` con lo stesso utente passato a
`setup-gaming-controller.sh`, quindi eseguire una riga alla volta:

```powershell
scp UTENTE_LINUX@100.95.133.122:/etc/raspberry-server/gaming/id_ed25519.pub "$SetupDir\id_ed25519.pub"
```

```powershell
scp UTENTE_LINUX@100.95.133.122:/etc/raspberry-server/gaming/session-token "$SetupDir\session-token"
```

Non trasferire `id_ed25519` senza estensione: è la chiave privata e deve
rimanere sul mini PC. Dopo la copia, ripetere i due `Test-Path` e continuare
soltanto quando restituiscono entrambi `True`.

Eseguire infine l'installer con una singola riga. L'esempio seguente contiene
l'IP e il FQDN reali attualmente raccolti per il mini PC:

```powershell
.\install-gaming-host.ps1 -GamingUser "gaming" -MiniPcTailscaleIp "100.95.133.122" -ControllerUrl "https://mini-pc.taila86e78.ts.net:8455" -ControllerPublicKeyPath (Join-Path $SetupDir "id_ed25519.pub") -SessionTokenFile (Join-Path $SetupDir "session-token")
```

L'URL deve essere una normale stringa fra virgolette, non la sintassi Markdown
`[URL](URL)`. Il nome corretto è `id_ed25519.pub`, senza barra inversa prima
dell'underscore. `MiniPcTailscaleIp` e `ControllerUrl` indicano entrambi il
**mini PC**, non il PC gaming; `GamingUser` deve coincidere con l'account locale
standard creato in precedenza.

L'installer è idempotente: se una precedente esecuzione è stata interrotta,
ripara prima i permessi dei propri file e quelli di `C:\ProgramData\ssh`. Per
OpenSSH applica ricorsivamente l'ACL richiesta dal servizio, con proprietario
`SYSTEM` e accesso limitato a `SYSTEM` e `Administrators`; questo comprende
anche la cartella `logs`, che alcune versioni di OpenSSH verificano all'avvio.

Lo script:

- verifica che `gaming` non sia amministratore;
- installa e avvia OpenSSH Server;
- rende OpenSSH esclusivo all'account `gaming` e al forced command;
- disabilita password, terminale, forwarding e SFTP effettivo;
- limita la porta SSH all'IPv4 Tailscale del mini PC;
- disabilita le regole Sunshine generiche trovate;
- consente le sole porte TCP `47984`, `47989`, `48010` e UDP
  `47998-48000`, `48002` solamente da `100.64.0.0/10`;
- installa gli script di sessione sotto `C:\ProgramData\PiServer`;
- stampa la fingerprint Ed25519 dell'host Windows.

Al termine, l'installer non usa più i file temporanei. Eliminare la copia del
token e della chiave pubblica dalla cartella Download; gli originali necessari
rimangono protetti sul mini PC:

```powershell
Remove-Item -LiteralPath "$SetupDir\session-token" -Force
Remove-Item -LiteralPath "$SetupDir\id_ed25519.pub" -Force
```

Non eliminare `C:\ProgramData\PiServer`, la cartella `.ssh` di `gaming` o i
file sotto `/etc/raspberry-server/gaming` sul mini PC.

L'installer considera OpenSSH dedicato al controller. Se il PC viene già
amministrato via OpenSSH per altri scopi, non eseguirlo senza adattare prima
`AllowUsers` e le regole firewall.

Prima di chiudere la sessione amministrativa, verificare che il servizio sia
attivo e che la configurazione sia valida:

```powershell
Get-Service sshd
& "$env:SystemRoot\System32\OpenSSH\sshd.exe" -t -f "$env:ProgramData\ssh\sshd_config"
```

L'installer valida automaticamente il file e, in caso di errore, ripristina
la copia precedente. Per un ripristino manuale dalla console locale:

```powershell
Copy-Item "$env:ProgramData\ssh\sshd_config.piserver-backup" `
  "$env:ProgramData\ssh\sshd_config" -Force
Restart-Service sshd
```

Confrontare fisicamente la fingerprint stampata anche con:

```powershell
ssh-keygen -lf C:\ProgramData\ssh\ssh_host_ed25519_key.pub -E sha256
```

### Collegare il timer a Sunshine

Prima verificare che i file copiati dall'installer esistano:

```powershell
Get-Item C:\ProgramData\PiServer\gaming-session.ps1
Get-Item C:\ProgramData\PiServer\gaming-session.json
Get-Item C:\ProgramData\PiServer\session-token
```

Aprire `https://localhost:47990`, autenticarsi e andare in **Configuration >
General > Global Prep Commands**. Aggiungere **una sola voce** con i seguenti
campi; i nomi possono apparire come `Do`, `Undo` ed `Elevated` a seconda della
versione di Sunshine.

- abilitare `Elevated`; Sunshine è installato come servizio e, in questa
  modalità, il callback deve essere avviato nel contesto del servizio;
- incollare tutto il comando `Do` su una sola riga;
- incollare tutto il comando `Undo` su una sola riga.

**Do**, eseguito prima dell'apertura dello stream:

```text
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "C:\ProgramData\PiServer\gaming-session.ps1" start
```

**Undo**, eseguito quando lo stream viene chiuso:

```text
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "C:\ProgramData\PiServer\gaming-session.ps1" stop
```

Salvare e usare il comando di riavvio di Sunshine presente nell'interfaccia.
Non creare due prep command separate: `Do` e `Undo` devono appartenere alla
stessa voce, così Sunshine associa correttamente apertura e chiusura.

L'opzione `Elevated` non trasforma l'account locale `gaming` in amministratore:
stabilisce soltanto come Sunshine, già in esecuzione come servizio, avvia il
processo PowerShell. Sunshine annulla l'avvio di un'applicazione se non riesce
ad avviare una prep command o se questa restituisce un errore.
`gaming-session.ps1` gestisce internamente gli errori di rete e restituisce
successo: un controller non raggiungibile non deve quindi impedire di giocare
e, per sicurezza, lascia il PC acceso. Questi callback non possono accendere o
spegnere Windows; modificano soltanto lo stato `session_active` del controller.

Se Moonlight raggiunge l'host ma, subito dopo il tentativo di apertura di
`Desktop`, mostra un errore generico sulle porte TCP, controllare il log di
Sunshine. Una riga `Executing Do Cmd` seguita da `exited with code` indica che
è la prep command ad avere annullato la sessione, non necessariamente il
firewall. Per ripristinare subito lo streaming, eliminare temporaneamente la
voce da **Global Prep Commands**, salvare, riavviare Sunshine e riprovare. Non
lasciare una copia parziale con il solo comando `Do`.

## 7. Verificare e fissare la host key dal mini PC

Lasciare Windows acceso e Tailscale online. Sul mini PC usare la fingerprint
letta direttamente sul PC. Il primo argomento è questa volta l'IPv4 Tailscale
del **PC gaming**, cioè lo stesso valore di
`GAMING_PC_TAILSCALE_IP` in `gaming.env`:

```bash
cd /opt/raspberry-server
sudo bash scripts/pin-gaming-pc-host-key.sh \
  100.x.y.z SHA256:FINGERPRINT_VERIFICATA
```

Da una riga Windows simile a:

```text
256 SHA256:AbCdEf... nome-host (ED25519)
```

copiare soltanto la parte che inizia con `SHA256:`. Lo script scarica la
chiave Ed25519 presentata da Windows, la confronta con quel valore e termina
senza modificare nulla se non coincide. Non accetta trust-on-first-use.

Validare e avviare il controller:

```bash
sudo bash scripts/setup-gaming-controller.sh UTENTE_LINUX --enable
sudo systemctl status gaming-pc-controller.service
curl http://127.0.0.1:8084/health
```

I risultati attesi sono `active (running)` da `systemctl` e:

```json
{"status":"ok"}
```

Se il servizio non parte, non proseguire con Tailscale Serve. Leggere prima
l'errore completo:

```bash
sudo journalctl -u gaming-pc-controller.service -n 100 --no-pager
```

Quando il controllo locale è sano, pubblicarlo nella sola Tailnet:

```bash
cd /opt/raspberry-server
sudo bash scripts/configure-tailscale-serve.sh
tailscale serve status
```

`configure-tailscale-serve.sh` ricrea tutte le route private già gestite e
aggiunge:

```text
https://TAILSCALE_FQDN:8455/ → http://127.0.0.1:8084
```

Lo script esegue `tailscale serve reset` e poi ricrea le route elencate al suo
interno. Eventuali route Serve aggiunte manualmente e non presenti nello script
andrebbero perse: inserirle nello script prima di eseguirlo.

Riavviare Homepage per caricare subito la nuova card:

```bash
cd /opt/raspberry-server
docker compose restart homepage
```

Aprire `https://TAILSCALE_FQDN:8455/` da un dispositivo Tailscale autenticato
con il login inserito in `GAMING_ALLOWED_TAILSCALE_LOGINS`. Un errore `401`
indica login non corrispondente o dispositivo registrato con un tag.

Prima di affidarsi a Sunshine, verificare manualmente i due callback dal PC
Windows con il controller già attivo:

```powershell
& C:\ProgramData\PiServer\gaming-session.ps1 start
Start-Sleep -Seconds 2
& C:\ProgramData\PiServer\gaming-session.ps1 stop
```

Durante `start` la pagina deve mostrare `Sessione Moonlight attiva`; dopo
`stop` deve tornare allo stato precedente. Se compare un warning, controllare
URL, token, Tailscale e la regola policy PC gaming → mini PC TCP `8455`.

## 8. Selezionare il monitor in Sunshine

Due monitor non costituiscono un problema. Il rischio nasce quando un monitor
spento smette di pubblicare il proprio EDID: Windows può rimuoverlo e Sunshine
può scegliere l'altro output o non trovarne nessuno. DisplayPort tende a
comportarsi così più spesso di HDMI, ma dipende dai monitor.

Per il primo test lasciare vuoto `Output Name`: Sunshine userà il display
predefinito di Windows. Con entrambi i monitor accesi:

1. aprire **Impostazioni > Sistema > Schermo** in Windows;
2. premere **Identifica**, riconoscere il monitor HDMI e selezionare **Imposta
   come schermo principale**;
3. riavviare Sunshine e avviare `Desktop` da Moonlight;
4. impostare `Output Name` soltanto se Sunshine cattura il monitor sbagliato.

Per ottenere gli identificatori esatti riconosciuti da Sunshine, aprire
PowerShell sul PC ed eseguire:

```powershell
& "$env:ProgramFiles\Sunshine\tools\dxgi-info.exe"
```

Nell'output cercare il `friendly_name` del monitor HDMI e copiarne il
`device_id`, per esempio `{daeac860-...}`. Inserire quel valore completo in
**Configuration > Audio/Video > Output Name**, salvare e riavviare Sunshine.
Non basarsi soltanto sul numero `DISPLAY1`, che può cambiare dopo uno standby o
un aggiornamento driver.

Eseguire quindi il test EDID:

1. con entrambi i monitor accesi verificare uno stream funzionante;
2. chiudere lo stream e spegnere completamente il PC;
3. mettere i monitor in standby, poi riaccendere il PC dalla pagina `8455`;
4. avviare uno stream senza toccare i monitor;
5. ripetere spegnendo il monitor HDMI con il suo interruttore fisico;
6. ripetere con il solo monitor DisplayPort spento.

Se Windows continua a rilevare l'HDMI non serve un dummy plug. Installare un
display virtuale o usare un dongle HDMI soltanto se il test fallisce. Per il
primo collaudo lasciare invariata la risoluzione host; l'automazione del cambio
risoluzione può essere aggiunta dopo avere validato entrambe le modalità.

## 9. Installare Switchroot Android

Usare esclusivamente la pagina corrente del
[progetto Switchroot](https://wiki.switchroot.org/wiki/android/android-14-15)
e, da lì, la guida ufficiale LineageOS **Tablet (`nx_tab`)** per il proprio
modello. La procedura seguente è una checklist di sicurezza e non sostituisce i
passaggi di flashing specifici indicati da Switchroot:

1. identificare esattamente il modello Switch indicato dalla guida (`v1`,
   `v2`, Lite oppure OLED) e scaricare soltanto i file corrispondenti;
2. aggiornare Hekate alla versione minima richiesta dalla guida;
3. creare da Hekate un backup completo di BOOT0/BOOT1 e RAW GPP;
4. copiare il backup sul PC e su una seconda destinazione prima di continuare;
5. creare una copia dei dati presenti sulla microSD: il partizionamento li può
   cancellare;
6. scegliere **Android 15 Tablet (`nx_tab`)**, non Android TV (`nx`);
7. seguire l'installazione ufficiale su microSD e controllare ogni nome file
   prima del flash;
8. non seguire la guida eMMC: il progetto stesso la considera una procedura
   avanzata con beneficio marginale e rischio maggiore;
9. non installare Magisk: Tailscale e Moonlight non richiedono root;
10. avviare Android, provare Wi-Fi, touchscreen, Joy-Con e dock, quindi
    completare gli aggiornamenti OTA prima di installare le app.

Installare poi:

- Tailscale dal Play Store o dalla
  [pagina Android ufficiale](https://tailscale.com/docs/install/android);
- Moonlight dal Play Store oppure dagli
  [APK ufficiali del progetto](https://github.com/moonlight-stream/moonlight-android/releases).

Se l'installazione Switchroot non include i servizi Google, usare gli APK
ufficiali senza installare store o mirror non necessari.

In Tailscale:

- aprire l'app, accettare la creazione della configurazione VPN e autenticare
  la Switch con lo stesso login inserito in
  `GAMING_ALLOWED_TAILSCALE_LOGINS`;
- in **Impostazioni Android > Rete e Internet > VPN > Tailscale**, abilitare
  `VPN sempre attiva` se la voce è disponibile;
- in **Impostazioni > App > Tailscale > Batteria**, scegliere utilizzo senza
  restrizioni o escludere l'app dall'ottimizzazione;
- aprire **Tailscale > profilo > App-based split tunneling** e verificare che
  Moonlight non sia nell'elenco delle applicazioni escluse: un'app esclusa può
  raggiungere il PC sulla LAN di casa, ma non l'indirizzo `100.x.y.z` quando la
  Switch usa un hotspot;
- dalla console Tailscale rinominare il dispositivo `switch-cloud`, senza
  assegnargli un tag perché il controller richiede un'identità utente;
- aprire dal browser Android `https://FQDN_MINI_PC:8455/` e verificare che la
  pagina del controller compaia senza errore `401`.

In Moonlight la scoperta automatica attraverso Tailscale può non trovare
l'host ed è normale. Con il PC acceso e Sunshine pronto:

1. premere **Add PC** o il pulsante `+`;
2. inserire l'IPv4 Tailscale del **PC gaming**, non quello del mini PC e non
   l'indirizzo LAN/pubblico;
3. Moonlight mostrerà un PIN;
4. sul PC aprire `https://localhost:47990`, entrare nella pagina **PIN** di
   Sunshine e inserire quel codice;
5. verificare che in Moonlight compaiano almeno `Desktop` o l'applicazione
   configurata in Sunshine;
6. avviare prima `Desktop`, poi Steam Big Picture o il gioco desiderato.

Un riquadro trovato automaticamente sul Wi-Fi di casa può conservare
l'indirizzo LAN `192.168.x.y`. Questo riquadro non è una prova del collegamento
remoto: durante il primo test con hotspot premere nuovamente `+` e aggiungere
esplicitamente l'IPv4 Tailscale `100.x.y.z` del PC. Se Moonlight unisce le due
voci, verificare il test mentre la Switch è già scollegata dal Wi-Fi domestico;
se continua a usare l'indirizzo LAN, eliminare il vecchio riquadro e aggiungere
di nuovo soltanto l'indirizzo Tailscale.

Impostazioni iniziali consigliate:

| Modalità | Risoluzione | FPS | Codec iniziale | Bitrate iniziale |
| --- | --- | --- | --- | --- |
| portatile | 1280×720 | 60 | H.264 | 12-15 Mbps |
| dock | 1920×1080 | 60 | H.264, poi HEVC | 20-30 Mbps |

Passare a HEVC soltanto dopo un test stabile. La RTX 2070 Super dispone di
NVENC adatto a entrambi i profili; AV1 non è necessario. Evitare overclock
della Switch finché decodifica, frame pacing e temperature non sono stati
misurati con le impostazioni standard.

Quando si usa l'hotspot, è Tailscale sulla Switch a creare il tunnel: il
telefono fornisce soltanto Internet. Mini PC e PC gaming rimangono a casa;
quindi il mini PC continua a inviare il Wake-on-LAN sulla LAN domestica mentre
la Switch raggiunge la pagina attraverso Tailscale. Dal PC Windows si può
controllare il percorso con:

```powershell
tailscale ping switch-cloud
```

`direct` è preferibile. Un percorso `DERP` non espone porte pubbliche ma può
aggiungere latenza; in quel caso ridurre bitrate e verificare copertura mobile,
upload domestico e packet loss.

Non configurare sul telefono hotspot una subnet Tailscale, un exit node o la
condivisione della VPN: non serve e Android normalmente non inoltra agli utenti
dell'hotspot il tunnel VPN del telefono. Tailscale deve essere attivo sulla
Switch e il telefono deve limitarsi a fornire l'accesso a Internet.

L'avviso `DNS unavailable` è separato dal percorso Moonlight quando si usa
l'IPv4 Tailscale. Per una prova immediata, sulla Switch disabilitare **Use
Tailscale DNS settings**: il tunnel verso gli indirizzi `100.x.y.z` rimane
attivo, ma i nomi MagicDNS non vengono risolti. Se così l'avviso sparisce, il
resolver privato configurato nei **Global nameservers** non è raggiungibile
dalla rete mobile. La soluzione permanente è rendere raggiungibile quel DNS
attraverso la Tailnet oppure sostituirlo con un resolver pubblico supportato;
non è necessario modificare Moonlight se usa direttamente l'IP del PC.

## 10. Collaudo completo

Eseguire nell'ordine e correggere ogni punto prima di passare al successivo:

1. **WoL locale:** arrestare Windows completamente, attendere che ventole e
   LED di attività siano spenti, aprire la pagina `8455` e premere Accendi.
2. **Boot:** attendere fino a tre minuti; la pagina deve passare da `Accensione
   in corso` a `Pronto per Moonlight` e Windows deve entrare automaticamente
   nell'account `gaming`.
3. **Pairing:** aggiungere in Moonlight l'IPv4 Tailscale del PC e completare il
   PIN dall'interfaccia locale di Sunshine.
4. **Desktop:** avviare `Desktop`, controllare immagine, audio, latenza e tutti
   i tasti dei Joy-Con prima di provare un gioco.
5. **Steam:** avviare Steam Big Picture e verificare che Windows veda un
   controller virtuale compatibile.
6. **Monitor:** ripetere l'avvio con HDMI e DisplayPort nelle condizioni
   descritte nella sezione precedente.
7. **Callback:** durante lo stream la pagina deve mostrare `Sessione Moonlight
   attiva`; dopo la chiusura deve apparire il conto alla rovescia.
8. **Riconnessione:** ricollegarsi durante i 30 minuti; il timer deve sparire.
9. **Spegnimento manuale:** premere Spegni e verificare l'arresto dopo 60
   secondi. Localmente `shutdown /a` può annullarlo durante il preavviso.
10. **Timeout:** per un test breve impostare temporaneamente
    `GAMING_IDLE_TIMEOUT_SECONDS=300`, riavviare il controller e poi
    ripristinare `1800`.
11. **Hotspot:** disattivare il Wi-Fi normale della Switch, collegarla al
    telefono, verificare che Moonlight non sia escluso dallo split tunneling,
    aggiungere manualmente l'IPv4 Tailscale del PC e ripetere accensione,
    stream e spegnimento. Non usare una subnet o la VPN del telefono.

Per il test da cinque minuti sul mini PC:

```bash
sudo nano /etc/raspberry-server/gaming/gaming.env
# impostare GAMING_IDLE_TIMEOUT_SECONDS=300
sudo systemctl restart gaming-pc-controller.service
```

Concluso il test, rimettere `1800` nello stesso file e riavviare di nuovo il
servizio. Il timeout parte soltanto per un'accensione richiesta dalla pagina;
prima di provarlo spegnere il PC e riaccenderlo con **Accendi**.

Controlli sul mini PC:

```bash
journalctl -u gaming-pc-controller.service -f
systemctl is-enabled gaming-pc-controller.service
ss -lnt '( sport = :8084 )'
tailscale serve status
```

`ss` deve mostrare soltanto `127.0.0.1:8084`, mai `0.0.0.0:8084`.

### Diagnosi rapida

| Sintomo | Controllo da eseguire |
| --- | --- |
| La pagina `8455` non si apre | Sul mini PC controllare `systemctl status gaming-pc-controller`, `curl 127.0.0.1:8084/health` e `tailscale serve status`. |
| La pagina risponde `401` | Verificare il login esatto in `GAMING_ALLOWED_TAILSCALE_LOGINS`; la Switch deve essere un dispositivo utente, non tagged. |
| `Accendi` non avvia il PC | Ricontrollare MAC Ethernet, broadcast LAN, BIOS, ErP, Avvio rapido e proprietà WoL della scheda Intel. Mini PC e fisso devono condividere la LAN/VLAN. |
| Rimane `Windows online, Sunshine non pronto` | Sul PC controllare il servizio Sunshine, `https://localhost:47990` e le regole `PiServer-Sunshine-*` di Windows Firewall. |
| Moonlight non raggiunge l'host | Verificare di avere inserito l'IPv4 Tailscale del PC gaming e provare `tailscale ping` nei due sensi. |
| Moonlight segnala porte TCP ma il tentativo compare nel log Sunshine | Cercare `Executing Do Cmd` seguito da `exited with code`: rimuovere temporaneamente la global prep command, riavviare Sunshine e verificare che `Desktop` parta. Quando si reinserisce la voce, abilitare `Elevated`. |
| Tailscale Android mostra `DNS unavailable` | Verificare in **DNS > Global nameservers** che il resolver sia raggiungibile dalla Tailnet sia su UDP sia su TCP 53. Per isolare il problema usare in Moonlight l'IPv4 Tailscale del PC. Se il resolver Pi-hole pubblicato da Docker non risponde attraverso `tailscale0`, rimuoverlo dai nameserver globali e disattivare `Override DNS servers`: MagicDNS continua a risolvere i nodi Tailscale, mentre Internet usa il DNS della rete Wi-Fi o dell'hotspot. |
| Immagine nera o monitor errato | Ripetere `dxgi-info.exe`, verificare `Output Name` e rifare il test EDID con il monitor HDMI. |
| La pagina non mostra la sessione attiva | Eseguire manualmente `gaming-session.ps1 start`; controllare URL, token e accesso PC gaming → mini PC TCP `8455`. |
| `Spegni` viene rifiutato | Leggere il journal del controller, verificare servizio `sshd`, host key fissata, firewall SSH e diritto di arresto dell'account `gaming`. |
| Il timer non spegne il PC | Verificare che l'accensione sia partita dalla pagina, che lo stream sia stato chiuso e che il callback `stop` sia arrivato. |

Comandi utili sul PC Windows:

```powershell
Get-Service Tailscale, SunshineService, sshd -ErrorAction SilentlyContinue
Get-NetFirewallRule -Name "PiServer-*" |
  Format-Table Name, Enabled, Direction, Action
tailscale status
```

Il nome effettivo del servizio Sunshine può variare con la versione; se
`SunshineService` non compare, individuarlo senza modificarlo con:

```powershell
Get-Service | Where-Object DisplayName -Like "*Sunshine*"
```

## 11. Tailscale policy e firewall

Le Tailnet nuove possono consentire inizialmente traffico ampio. Quando si
restringe la policy, consentire soltanto:

- Switch → mini PC: TCP `443` e `8455`;
- Switch → PC gaming: TCP `47984`, `47989`, `48010`; UDP
  `47998-48000`, `48002`;
- PC gaming → mini PC: TCP `8455` per i callback start/stop di Sunshine;
- mini PC → PC gaming: TCP `22` e `47984`;
- traffico amministrativo già previsto dalla repository.

Usare utenti, gruppi o tag reali della propria policy senza copiare nomi di
esempio. Prima di salvare una policy restrittiva verificare di non rimuovere
l'accesso amministrativo al mini PC. Windows Firewall costituisce un secondo
livello: Sunshine accetta il range Tailnet e SSH soltanto l'IPv4 del mini PC.

## 12. Manutenzione e ripristino

- Aggiornare Tailscale, Sunshine, Moonlight e Switchroot con release stabili.
- Dopo ogni aggiornamento Sunshine ripetere pairing, callback e controllo
  delle regole firewall: un installer potrebbe ricreare regole generiche.
- Controllare mensilmente il Wake-on-LAN da S5 e dopo aggiornamenti BIOS/NIC.
- Non caricare log Sunshine pubblicamente senza rimuovere nomi host e dettagli
  di rete.
- Dopo un restore del mini PC rieseguire
  `configure-tailscale-serve.sh` e verificare la host key Windows.
- Se Windows viene reinstallato, rieseguire `install-gaming-host.ps1` e fissare
  la nuova host key; non accettare automaticamente una fingerprint cambiata.

Per disabilitare il controller senza cancellare configurazione o chiavi:

```bash
sudo systemctl disable --now gaming-pc-controller.service
sudo tailscale serve --https=8455 --set-path=/ off
```

La configurazione rimane recuperabile sotto `/etc/raspberry-server/gaming` e
lo stato non sensibile sotto `/var/lib/raspberry-server/gaming-controller`.
