# Architettura

## Flusso principale

```text
Fire TV / Jellyfin Android TV
        |
        | HTTP + WebSocket + media, LAN HTTP
        v
telefono Android / Jellyfin Phone Relay :8097
        |
        | normali socket Android instradati da Tailscale
        v
server Jellyfin remoto :8096
```

JPR è un reverse proxy trasparente. Il client ufficiale Android TV continua a gestire autenticazione, profilo dispositivo, player, transcodifica, sottotitoli, avanzamento e comandi remoti. Gli header `Authorization`, `X-Emby-Authorization`, Device ID, `Range` e User-Agent attraversano il relay; `Host` viene ricreato per l'upstream e gli header hop-by-hop vengono rimossi.

## Componenti

- `MainActivity`: configurazione, test server, stato, metriche e diagnostica.
- `RelayService`: foreground service, notifica STOP, wake lock e lifecycle.
- `WifiNetworkMonitor`: trova l'IPv4 della rete Wi-Fi anche quando la VPN Tailscale è la rete attiva e osserva i cambiamenti.
- `LocalProxyServer`: listener HTTP/WebSocket vincolato all'IPv4 Wi-Fi.
- `StreamingRequestBody` e `CountingResponseInputStream`: copie incrementali da 64 KiB e contatori.
- `RelayWebSocket`: ponte frame text/binary tra NanoWSD e OkHttp.
- `HeaderSanitizer`, `UrlMapper`, `UrlRewriter`: trasparenza HTTP e riscritture limitate.
- `SettingsRepository`: DataStore per URL, porta e ultima configurazione verificata.
- `RelayMetrics`, `SafeLogger`, `Redactor`: telemetria locale senza credenziali.

## HTTP e streaming

Ogni richiesta LAN crea una richiesta OkHttp verso l'URL upstream corrispondente. Il body in ingresso viene letto solo mentre OkHttp lo richiede. La response body viene consegnata a NanoHTTPD come `InputStream`: NanoHTTPD legge blocchi da 16 KiB e il wrapper conta i byte, mentre OkHttp applica la propria backpressure. Non viene creato alcun file media temporaneo.

`Range` e gli header condizionali non vengono interpretati: passano all'upstream. Status e header della risposta, inclusi `206`, `Content-Range`, `Accept-Ranges`, `ETag` e `Last-Modified`, tornano al client senza cambio semantico. Se la Fire TV chiude la connessione, NanoHTTPD chiude l'`InputStream`, che a sua volta chiude la response OkHttp e cancella il download residuo.

Il client upstream ha 12 secondi di connect timeout e nessun read timeout globale, per non interrompere stream lunghi. Il test server usa invece timeout brevi e distinti.

## WebSocket

NanoWSD riconosce genericamente ogni richiesta `Upgrade: websocket`; path, query e header Jellyfin vengono usati per aprire un WebSocket OkHttp verso lo stesso endpoint upstream. I messaggi text e binary viaggiano in entrambe le direzioni. Ping/pong sono gestiti dai due endpoint WebSocket; chiusure ed errori fanno chiudere anche il lato opposto.

Il listener locale viene avviato con socket read timeout infinito, necessario per una sessione Jellyfin inattiva ma ancora controllabile.

## Riscrittura URL

- Un `Location` viene riscritto solo se ha esattamente scheme, host e porta dell'upstream.
- Una playlist riconosciuta da content type o suffisso `.m3u8` viene letta solo se la lunghezza dichiarata è al massimo 4 MiB; le occorrenze dell'origine upstream diventano l'origine del relay.
- I payload JSON generici e i media binari non vengono modificati.
- Dopo una riscrittura vengono invalidati ETag, Content-MD5 e Content-Encoding e viene ricalcolata la lunghezza.

## Scelta del server embedded

NanoHTTPD/NanoWSD 2.3.1 è JVM puro, funziona su Android, offre connessioni concorrenti, keep-alive, risposte `InputStream` e WebSocket in un artefatto piccolo. La response non viene materializzata: la sua API a lunghezza fissa o chunked consente lo streaming reale. OkHttp gestisce pooling, TLS Android, richieste upstream e WebSocket client.

Il trade-off noto è che NanoHTTPD 2.3.1 non decodifica request body chunked in modo adatto al pass-through; l'MVP rifiuta esplicitamente quel raro caso invece di rischiare buffering o corruzione.

## Lifecycle di rete

Il servizio si lega solo all'IPv4 Wi-Fi di una rete con capacità `NOT_VPN`, non a `0.0.0.0` e non all'interfaccia Tailscale. Come seconda barriera, gli indirizzi nel blocco CGNAT Tailscale `100.64.0.0/10` vengono sempre scartati. Se l'indirizzo cambia, il listener precedente viene fermato e ricreato sul nuovo IP; l'interfaccia avvisa che l'URL sulla Fire TV deve essere aggiornato. Senza un IPv4 Wi-Fi valido il servizio resta visibile ma non dichiara il relay disponibile.
