import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {runInNewContext} from "node:vm";
import test from "node:test";

const source = readFileSync(new URL("../config/homepage/custom.js", import.meta.url), "utf8");
for (const [label, nativeClass, nativeTitle, expected] of [
  ["Disponibile Stato", "bg-emerald-500", "HTTP 200", "green"],
  ["Non disponibile Stato", "bg-rose-500", "HTTP 503", "red"],
  ["Dati scaduti Stato", "bg-rose-500", "HTTP 503", "yellow"],
  ["Controlli incompleti Stato", "bg-rose-500", "HTTP 503", "yellow"],
  ["", "bg-rose-500", "HTTP Error", "yellow"],
  ["Disponibile Stato", "bg-rose-500", "HTTP Error", "yellow"],
]) {
  test(`Cockpit indicator: ${label || "API unavailable"} / ${nativeTitle}`, () => {
    const indicator = {
      title: nativeTitle,
      querySelector: () => ({className: nativeClass}),
      setAttribute() {},
    };
    const card = {
      dataset: {},
      querySelector: (selector) => selector === ".service-block" ? {textContent: label} : indicator,
    };
    const callbacks = [];
    runInNewContext(source, {
      document: {
        documentElement: {},
        querySelector: (selector) => selector === "#cockpit-files" ? card : null,
      },
      window: {location: {protocol: "https:", hostname: "mini-pc.example.ts.net"}},
      MutationObserver: class {
        constructor(callback) { callbacks.push(callback); }
        observe() {}
      },
    });
    assert.equal(card.dataset.cockpitState, expected);
    callbacks.at(-1)();
    assert.equal(card.dataset.cockpitState, expected);
    assert.equal(indicator.title, nativeTitle);
  });
}
