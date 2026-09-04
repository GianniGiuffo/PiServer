# Test

## Test automatici

Esegui dalla cartella `jellyfin-phone-relay`:

```powershell
.\gradlew.bat testDebugUnitTest assembleDebug
```

La suite copre:

- mapping path/query verso l'upstream e base path Jellyfin;
- mapping WebSocket HTTPS;
- esclusione delle reti VPN e degli indirizzi Tailscale `100.64.0.0/10` dall'URL LAN;
- filtro degli header hop-by-hop;
- conservazione di autenticazione, Device ID implicito, User-Agent e `Range`;
- conservazione di `Content-Range`, `Accept-Ranges` ed ETag;
- riscrittura `Location` solo per la stessa origine;
- riscrittura playlist HLS senza toccare origini esterne;
- redazione di API key, token e authorization;
- copia del request body limitata alla lunghezza dichiarata;
- integrazione reale HTTP attraverso due listener locali, incluso `206` e byte esatti;
- integrazione WebSocket bidirezionale con echo server locale.

## Test rapido su dispositivo

1. Installa l'APK e attiva Tailscale.
2. Premi **TEST SERVER**.
3. Avvia il relay e annota l'IP mostrato.
4. Da un computer sulla stessa Wi-Fi esegui:

```bash
curl -v http://IP_TELEFONO:8097/System/Info/Public
curl -v http://IP_TELEFONO:8097/_jpr/health
```

Per un URL media valido, senza salvare token nella shell history o nel repository:

```bash
curl -v -H 'Range: bytes=0-1048575' 'http://IP_TELEFONO:8097/Videos/ID/stream?...' -o /dev/null
```

Verifica `206`, `Content-Range` e circa 1 MiB trasferito.

## Checklist hardware obbligatoria

Le caselle restano volutamente non selezionate: richiedono la rete e i dispositivi reali dell'utente.

### Networking

- [ ] Tailscale ON + Wi-Fi ON: relay raggiungibile.
- [ ] L'indirizzo mostrato è l'IPv4 Wi-Fi e non appartiene a `100.64.0.0/10`.
- [ ] Tailscale OFF: errore upstream chiaro.
- [ ] Wi-Fi OFF: nessun falso URL LAN attivo.
- [ ] Cambio IP Wi-Fi: URL e avviso aggiornati.
- [ ] Exit node: verificato `Allow Local Network Access`.
- [ ] Client/AP isolation: caso riconosciuto e documentato.

### Jellyfin API

- [ ] `/System/Info/Public` via relay.
- [ ] Login username/password.
- [ ] Quick Connect, se usato.
- [ ] Home, librerie, immagini, ricerca e metadata.

### Sessione e controllo remoto

- [ ] Fire TV visibile nelle sessioni server.
- [ ] Fire TV visibile in **Riproduci su** sul telefono.
- [ ] Play, pause, resume, seek e stop remoti.
- [ ] Riconnessione WebSocket dopo una breve perdita rete.

### Playback

- [ ] Direct Play MP4/H.264.
- [ ] Direct Play MKV se supportato dalla Fire TV.
- [ ] Seek avanti e indietro con `Range`/`206`.
- [ ] Resume dalla posizione salvata.
- [ ] HLS/transcoding e segmenti concorrenti.
- [ ] Sottotitoli, cambio traccia audio ed episodio successivo.
- [ ] Nessun URL `100.x.x.x` sfugge verso la Fire TV.

### Android lifecycle e performance

- [ ] Schermo spento e telefono bloccato per almeno 30 minuti.
- [ ] Activity chiusa con foreground service ancora attivo.
- [ ] Playback continuo per 1–2 ore.
- [ ] Stop da app e notifica chiude HTTP e WebSocket.
- [ ] RAM stabile e nessun file media temporaneo.
- [ ] Throughput sufficiente per il bitrate reale; prova 1080p prima del 4K.
- [ ] Temperatura e consumo batteria accettabili.

### Android 17

- [ ] Installato SDK 37 e aggiornati `compileSdk`/`targetSdk`.
- [ ] Dichiarata e richiesta `android.permission.ACCESS_LOCAL_NETWORK`.
- [ ] Negazione/revoca del permesso gestita senza falso stato attivo.
- [ ] Listener LAN validato su un dispositivo o emulatore Android 17.
