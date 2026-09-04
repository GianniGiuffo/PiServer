# Jellyfin Phone Relay

Jellyfin Phone Relay (JPR) trasforma un telefono Android in un relay locale tra una Fire TV e un server Jellyfin raggiungibile dal telefono tramite Tailscale.

```text
Jellyfin Android TV -> Wi-Fi -> telefono/JPR -> Tailscale -> Jellyfin Server
```

La Fire TV usa il client ufficiale Jellyfin Android TV e non deve avere Tailscale. JPR non esegue login, non contiene un player e non crea una seconda sessione: inoltra HTTP, streaming e WebSocket conservando gli header del client TV.

## Funzioni incluse

- proxy dei metodi HTTP usati da Jellyfin, con path, query, body e header end-to-end;
- streaming progressivo con buffer da 64 KiB, senza file temporanei o film interi in RAM;
- pass-through di `Range`, `206 Partial Content`, `Content-Range`, ETag e metadata di cache;
- WebSocket bidirezionale per sessione TV, eventi e comandi `Riproduci su`;
- riscrittura di `Location` e URL assoluti nelle playlist HLS fino a 4 MiB;
- listener vincolato all'IPv4 Wi-Fi del telefono e riavvio al cambio rete;
- foreground service, notifica con STOP e wake lock solo durante il relay;
- test del server Jellyfin con diagnosi DNS, timeout, route, TLS e risposta non valida;
- metriche, endpoint `/_jpr/health` e log redatto copiabile;
- impostazioni persistenti con Android DataStore.

## APK pronto

L'APK debug compilato è in:

```text
app/build/outputs/apk/debug/app-debug.apk
```

Installazione via ADB, dalla cartella del progetto:

```powershell
adb install -r app\build\outputs\apk\debug\app-debug.apk
```

In alternativa, copia l'APK sul telefono e autorizza temporaneamente l'installazione da sorgenti sconosciute per il file manager usato.

## Utilizzo

1. Installa e attiva Tailscale sul telefono.
2. Verifica che dal telefono il server Jellyfin reale sia raggiungibile, per esempio `http://100.x.y.z:8096`.
3. Collega telefono e Fire TV alla stessa rete Wi-Fi.
4. Apri JPR, inserisci l'URL reale e lascia la porta locale `8097`.
5. Premi **TEST SERVER**, poi **AVVIA RELAY**.
6. In Jellyfin Android TV sulla Fire TV inserisci l'indirizzo mostrato da JPR, per esempio `http://192.168.1.47:8097`.
7. Accedi normalmente dalla Fire TV. La sessione deve comparire nel server Jellyfin e tra le destinazioni **Riproduci su** dell'app Jellyfin del telefono.

Se usi un exit node Tailscale e la Fire TV non raggiunge il telefono, abilita **Allow Local Network Access** in Tailscale. Verifica anche che l'access point non abbia client/AP isolation.

## Build

Requisiti:

- JDK 17;
- Android SDK 34 e Build Tools;
- accesso iniziale a Google Maven e Maven Central.

```powershell
.\gradlew.bat testDebugUnitTest assembleDebug
```

Il progetto usa Kotlin, OkHttp 4.12, NanoHTTPD/NanoWSD 2.3.1, Coroutines e DataStore. La scelta del server è motivata in [ARCHITECTURE.md](ARCHITECTURE.md).

## Verifica rapida dalla LAN

Con JPR attivo, da un altro dispositivo sulla stessa Wi-Fi:

```bash
curl -v http://IP_TELEFONO:8097/System/Info/Public
curl -v http://IP_TELEFONO:8097/_jpr/health
```

La prima risposta deve corrispondere a Jellyfin; la seconda deve riportare lo stato locale del relay senza URL o token.

## Stato e limitazioni

Questo repository contiene un MVP compilabile e testato automaticamente, ma la prova finale richiede hardware reale: telefono con Tailscale, server Jellyfin e Fire TV. La checklist è in [TESTING.md](TESTING.md).

### Correzione 0.1.2: indirizzo LAN

JPR esclude esplicitamente le reti VPN e l'intero intervallo Tailscale `100.64.0.0/10` quando sceglie l'indirizzo da mostrare alla TV o al portatile. Se Android nasconde la rete Wi-Fi dietro la VPN, prova in sequenza le API di connettività, l'indirizzo riportato dal Wi-Fi manager e l'interfaccia fisica `wlan`. L'URL relay deve quindi contenere l'IPv4 Wi-Fi del telefono, tipicamente `192.168.x.x`, `10.x.x.x` o `172.16-31.x.x`, mai un indirizzo `100.x.x.x` Tailscale.

La schermata mostra ora chiaramente la versione installata. Prima di provare il relay verifica che indichi `0.1.2`; questo evita di confondere APK diversi chiamati tutti `app-debug.apk`.

L'URL locale rimane intenzionalmente `http://`: il client si collega direttamente al telefono sulla Wi-Fi, mentre Tailscale protegge il tratto telefono-server. Se il browser reindirizza automaticamente a HTTPS, inserisci l'URL completo con `http://` oppure prova prima `/System/Info/Public` con `curl`.

La toolchain disponibile ha SDK 34, quindi questo build usa `compileSdk/targetSdk 34`. Il codice contiene già il controllo runtime per `ACCESS_LOCAL_NETWORK`, ma prima di portare il target a SDK 37 occorre installare SDK 37, dichiarare la permission nel manifest e ripetere i test su Android 17. Per target 36 o inferiore la documentazione Android indica di non dichiararla.

Le request body in ingresso con `Transfer-Encoding: chunked` non sono supportate dal listener MVP e ricevono un errore upstream; i normali payload Jellyfin Android TV usano `Content-Length`. Le risposte Jellyfin chunked, incluso lo streaming lungo, sono supportate.

Consulta anche [SECURITY.md](SECURITY.md) prima dell'uso su reti che non controlli.
