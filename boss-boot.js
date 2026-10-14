// Runs before the game starts. Reads ?boss=<code>, makes sure the Boss Picker
// service worker is in charge, tells it which boss to use, then starts the game.
(function () {
  "use strict";
  var GAME_SCRIPTS = ["scripts/offlineclient.js", "scripts/main.js", "scripts/register-sw.js"];

  function loadScript(src) {
    return new Promise(function (resolve) {
      var s = document.createElement("script");
      s.src = src; s.type = "module";
      s.onload = resolve; s.onerror = resolve;
      document.body.appendChild(s);
    });
  }

  async function startGame() {
    for (var i = 0; i < GAME_SCRIPTS.length; i++) await loadScript(GAME_SCRIPTS[i]);
  }

  function withTimeout(p, ms) {
    return Promise.race([p, new Promise(function (r) { setTimeout(r, ms); })]);
  }

  async function prepare() {
    var boss = (new URLSearchParams(location.search).get("boss") || "").toLowerCase().replace(/[^a-z0-9-]/g, "");
    if (!("serviceWorker" in navigator)) return;
    try {
      await navigator.serviceWorker.register("sw.js", { scope: "./" });
      if (!navigator.serviceWorker.controller) {
        await withTimeout(new Promise(function (r) {
          navigator.serviceWorker.addEventListener("controllerchange", r, { once: true });
        }), 8000);
      }
      var ctrl = navigator.serviceWorker.controller;
      if (!ctrl) return;
      await withTimeout(new Promise(function (r) {
        function onMsg(e) {
          if (e.data && e.data.type === "bossSet") {
            navigator.serviceWorker.removeEventListener("message", onMsg);
            window.BossPicker = { boss: boss, found: e.data.found };
            if (boss && !e.data.found) console.warn("[Boss Picker] No boss named '" + boss + "'. Playing normal Bowser.");
            r();
          }
        }
        navigator.serviceWorker.addEventListener("message", onMsg);
        ctrl.postMessage({ type: "setBoss", boss: boss });
      }), 5000);
    } catch (e) {
      console.warn("[Boss Picker] couldn't start, playing normal Bowser:", e);
    }
  }

  prepare().then(startGame);
})();
