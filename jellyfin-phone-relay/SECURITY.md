# Sicurezza

## Confini di fiducia

Il tratto Tailscale è protetto dalla tailnet, ma il tratto Fire TV–telefono dell'MVP è HTTP in chiaro. Chi controlla o può intercettare la Wi-Fi locale potrebbe vedere traffico Jellyfin e token della sessione TV.

Usa JPR solo su reti fidate e preferisci un account Jellyfin non amministratore, limitato alle librerie necessarie. Spegni il relay appena finita la riproduzione.

## Riduzione dell'esposizione

- Il relay è spento per impostazione predefinita e parte solo da un'azione esplicita.
- Il listener viene vincolato all'IPv4 Wi-Fi corrente, non a tutte le interfacce.
- La notifica persistente offre uno STOP immediato.
- Il servizio e l'Activity non esportano endpoint Android interni.
- `/_jpr/health` mostra solo conteggi e stato, senza upstream, query o credenziali.

Non esiste un'autenticazione proprietaria davanti al relay: il client Jellyfin Android TV ufficiale non saprebbe fornirla. La protezione pratica è l'esposizione breve su una LAN controllata.

## Credenziali e log

JPR non chiede né salva username o password Jellyfin. Token e API key transitano come normali header/query del proxy e non vengono memorizzati intenzionalmente. Il logger elimina query dai path e redige `api_key`, `token`, `Authorization`, `X-Emby-Authorization` e `X-Emby-Token`.

Non pubblicare catture di rete o comandi `curl` contenenti token reali.

## TLS upstream

HTTPS usa la validazione standard Android/OkHttp e le CA di sistema. Non è presente alcun trust manager permissivo, hostname verifier disabilitato o modalità “trust all”. I certificati self-signed devono essere sostituiti con certificati validi o gestiti in una futura funzione esplicita e circoscritta.

HTTP upstream resta consentito perché molte installazioni Jellyfin domestiche usano la porta 8096 all'interno della tailnet cifrata.

## Permessi Android

Il build corrente richiede solo rete, stato Wi-Fi/rete, foreground service `specialUse`, notifica e wake lock. Il wake lock viene acquisito solo durante il relay e rilasciato in stop, distruzione ed errore.

Con target SDK 37 sarà obbligatorio aggiungere `android.permission.ACCESS_LOCAL_NETWORK` al manifest. Il controllo e la richiesta runtime sono già predisposti nel codice, ma il build SDK 34 non dichiara anticipatamente la permission, in accordo con la guida Android per target 36 o inferiore.

## Segnalazione problemi

Per una segnalazione, allega solo il log redatto prodotto dall'app e descrivi metodo/path senza query sensibili. Non allegare password, header di autorizzazione, URL con API key o APK firmati con chiavi private di produzione.
