// The controller is loopback-only on the server and is published by Tailscale
// Serve. No Pi-hole credential ever reaches this page.
(() => {
  const api = `${window.location.protocol}//${window.location.hostname}:8456/api`;

  async function withTimeout(promise, milliseconds = 5000) {
    let timeout;
    try {
      return await Promise.race([
        promise,
        new Promise((_, reject) => {
          timeout = window.setTimeout(() => reject(new Error("tempo scaduto")), milliseconds);
        }),
      ]);
    } finally {
      window.clearTimeout(timeout);
    }
  }

  async function readJson(response) {
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    return payload;
  }

  function labelFor(payload) {
    if (payload.blocking === true) return "Disattiva blocking su entrambi";
    if (payload.blocking === false) return "Attiva blocking su entrambi";
    return "Allinea e attiva il blocking";
  }

  async function installButton() {
    const card = document.querySelector("#system-network");
    if (!card || card.querySelector(".pihole-control")) return;

    const button = document.createElement("button");
    button.type = "button";
    button.className = "pihole-control";
    button.textContent = "Verifica blocking Pi-hole…";
    button.disabled = false;
    button.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      button.disabled = true;
      button.textContent = "Aggiornamento di entrambi i Pi-hole…";
      try {
        const status = await readJson(await withTimeout(fetch(`${api}/status`, {cache: "no-store"})));
        const result = await readJson(await withTimeout(fetch(`${api}/toggle`, {
          method: "POST",
          headers: {"Content-Type": "application/json", "X-CSRF-Token": status.csrf},
          body: "{}",
        })));
        button.textContent = labelFor(result);
      } catch (error) {
        button.textContent = `Errore Pi-hole: ${error.message}`;
      } finally {
        button.disabled = false;
      }
    });
    (card.firstElementChild || card).appendChild(button);

    try {
      const status = await readJson(await withTimeout(fetch(`${api}/status`, {cache: "no-store"})));
      button.textContent = labelFor(status);
    } catch (error) {
      button.textContent = "Riprova controllo Pi-hole";
      button.title = error.message;
    } finally {
      button.disabled = false;
    }
  }

  const observer = new MutationObserver(installButton);
  observer.observe(document.documentElement, {childList: true, subtree: true});
  installButton();
})();

// Homepage's native HTTP monitor has two colors. Extend only Cockpit's dot
// with the collector's three-state result shown in its first widget block.
// No additional browser endpoint or privileged session is needed.
(() => {
  function syncCockpitStatus() {
    const card = document.querySelector("#cockpit-files");
    if (!card) return;
    const text = card.querySelector(".service-block")?.textContent || "";
    let state = "yellow";
    if (text.includes("Non disponibile")) state = "red";
    else if (text.includes("Disponibile")) state = "green";
    const indicator = card.querySelector(".site-monitor-status");
    // A transport error may coexist briefly with cached widget values. Do not
    // advertise green while the monitoring API itself is unreachable.
    const nativeDot = indicator?.querySelector("div");
    if (state === "green" && nativeDot?.className.includes("rose") && !indicator.title.includes("503")) {
      state = "yellow";
    }
    card.dataset.cockpitState = state;
    if (indicator) indicator.setAttribute("aria-label", text.trim() || "Controlli incompleti");
  }
  new MutationObserver(syncCockpitStatus).observe(document.documentElement, {
    childList: true, subtree: true, attributes: true, attributeFilter: ["class", "title"],
  });
  syncCockpitStatus();
})();
