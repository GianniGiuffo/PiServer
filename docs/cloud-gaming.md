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

La cartella `windows/gaming` della repository deve trovarsi sul PC insieme ai
due file trasferiti. Aprire PowerShell **come amministratore**:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
cd F:\percorso\PiServer\windows\gaming
.\install-gaming-host.ps1 `
  -GamingUser gaming `
  -MiniPcTailscaleIp 100.x.y.z `
  -ControllerUrl https://mini-pc.example-tailnet.ts.net:8455 `
  -ControllerPublicKeyPath C:\percorso\id_ed25519.pub `
  -SessionTokenFile C:\percorso\session-token
```

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

In **Configuration > General > Global Prep Commands** aggiungere una voce non
elevata:

**Do**

```text
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "C:\ProgramData\PiServer\gaming-session.ps1" start
```

**Undo**

```text
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "C:\ProgramData\PiServer\gaming-session.ps1" stop
```

Salvare e riavviare Sunshine dalla sua interfaccia. Questi callback non possono
accendere o spegnere il PC: modificano soltanto lo stato `session_active` del
controller.

## 7. Verificare e fissare la host key dal mini PC

Lasciare Windows acceso e Tailscale online. Sul mini PC usare la fingerprint
letta direttamente sul PC:

```bash
cd /opt/raspberry-server
sudo bash scripts/pin-gaming-pc-host-key.sh \
  100.x.y.z SHA256:FINGERPRINT_VERIFICATA
```

Lo script scarica soltanto la chiave Ed25519, confronta la fingerprint e non
accetta trust-on-first-use.

Validare e avviare il controller:

```bash
sudo bash scripts/setup-gaming-controller.sh UTENTE_LINUX --enable
sudo systemctl status gaming-pc-controller.service
curl http://127.0.0.1:8084/health
sudo bash scripts/configure-tailscale-serve.sh
tailscale serve status
```

`configure-tailscale-serve.sh` ricrea tutte le route private già gestite e
aggiunge:

```text
https://TAILSCALE_FQDN:8455/ → http://127.0.0.1:8084
```

Riavviare Homepage per caricare subito la nuova card:

```bash
docker compose restart homepage
```

Aprire `https://TAILSCALE_FQDN:8455/` da un dispositivo Tailscale autenticato
con il login inserito in `GAMING_ALLOWED_TAILSCALE_LOGINS`. Un errore `401`
indica login non corrispondente o dispositivo registrato con un tag.

## 8. Selezionare il monitor in Sunshine

Due monitor non costituiscono un problema. Il rischio nasce quando un monitor
spento smette di pubblicare il proprio EDID: Windows può rimuoverlo e Sunshine
può scegliere l'altro output o non trovarne nessuno. DisplayPort tende a
comportarsi così più spesso di HDMI, ma dipende dai monitor.

1. Con entrambi accesi, aprire Sunshine e identificare l'output HDMI.
2. Selezionarlo come output di cattura e impostarlo come principale in Windows.
3. Spegnere entrambi i monitor, spegnere il PC e riaccenderlo tramite la pagina.
4. Avviare uno stream e verificare che l'output HDMI esista ancora.
5. Provare separatamente standby e interruttore fisico del monitor.

Se Windows continua a rilevare l'HDMI non serve un dummy plug. Installare un
display virtuale o usare un dongle HDMI soltanto se il test fallisce. Per il
primo collaudo lasciare invariata la risoluzione host; l'automazione del cambio
risoluzione può essere aggiunta dopo avere validato entrambe le modalità.

## 9. Installare Switchroot Android

Usare esclusivamente le guide correnti del
[progetto Switchroot](https://wiki.switchroot.org/wiki/android/android-14-15)
e l'immagine ufficiale LineageOS per il proprio modello. In sintesi:

1. aggiornare Hekate alla versione richiesta dalla guida;
2. creare un backup completo e verificato di BOOT0/BOOT1 e RAW GPP;
3. conservare una copia offline della microSD prima di ripartizionarla;
4. scegliere **Android 15 Tablet**, non Android TV;
5. installare sulla microSD tramite il partition manager di Hekate;
6. evitare l'installazione eMMC: il guadagno è marginale e aumenta il rischio;
7. non installare Magisk: Tailscale e Moonlight non richiedono root;
8. completare gli aggiornamenti OTA prima di configurare le app.

Installare poi Tailscale e Moonlight dalle rispettive fonti ufficiali.

In Tailscale:

- autenticare la Switch con lo stesso login autorizzato dal controller;
- abilitare la VPN sempre attiva se disponibile;
- escludere Tailscale dall'ottimizzazione batteria;
- assegnare dalla console il nome `switch-cloud`;
- verificare l'accesso a Homepage e alla porta `8455`.

In Moonlight aggiungere manualmente l'IPv4 Tailscale del PC Windows. Eseguire
il pairing PIN con il PC acceso; non usare l'indirizzo pubblico domestico.

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
telefono fornisce soltanto Internet. Dal PC Windows si può controllare il
percorso con:

```powershell
tailscale ping switch-cloud
```

`direct` è preferibile. Un percorso `DERP` non espone porte pubbliche ma può
aggiungere latenza; in quel caso ridurre bitrate e verificare copertura mobile,
upload domestico e packet loss.

## 10. Collaudo completo

Eseguire nell'ordine:

1. **WoL locale:** PC spento, pagina su `8455`, premere Accendi.
2. **Boot:** attendere `Pronto per Moonlight` e verificare login automatico.
3. **Pairing:** collegare Moonlight all'IPv4 Tailscale del PC.
4. **Controller:** provare Joy-Con, audio e Steam Big Picture.
5. **Monitor:** ripetere con HDMI e DisplayPort spenti.
6. **Callback:** durante lo stream la pagina deve mostrare `Sessione Moonlight
   attiva`; dopo la chiusura deve apparire il conto alla rovescia.
7. **Riconnessione:** ricollegarsi durante i 30 minuti; il timer deve sparire.
8. **Spegnimento manuale:** premere Spegni e verificare l'arresto dopo 60
   secondi. Localmente `shutdown /a` può annullarlo durante il preavviso.
9. **Timeout:** per un test breve impostare temporaneamente
   `GAMING_IDLE_TIMEOUT_SECONDS=300`, riavviare il controller e poi ripristinare
   `1800`.
10. **Hotspot:** disattivare il Wi-Fi normale della Switch, collegarla al
    telefono e ripetere accensione, stream e spegnimento.

Controlli sul mini PC:

```bash
journalctl -u gaming-pc-controller.service -f
systemctl is-enabled gaming-pc-controller.service
ss -lnt '( sport = :8084 )'
tailscale serve status
```

`ss` deve mostrare soltanto `127.0.0.1:8084`, mai `0.0.0.0:8084`.

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
