// Boss Picker service worker for a self-hosted copy of Super Mario Construct.
// It replaces the game's own offline service worker. When a player opens
// ".../?boss=<code>", the page tells this worker which boss to use. From then on,
// whenever the game asks for data.json or a sprite sheet that boss changed,
// this worker hands back the boss's version instead of the original.
"use strict";

const STATE_CACHE = "boss-picker-state-v1";
const SCOPE = new URL(self.registration.scope);
let infoFor = null, info = null;
const stats = { images: 0, data: 0 };

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

async function getBoss() {
  const c = await caches.open(STATE_CACHE);
  const r = await c.match("__boss");
  return r ? (await r.text()) : "";
}

async function setBoss(boss) {
  const c = await caches.open(STATE_CACHE);
  await c.put("__boss", new Response(boss || ""));
  infoFor = null; info = null;
}

async function bossInfo(boss) {
  if (!boss) return null;
  if (infoFor === boss) return info;
  try {
    const r = await fetch(new URL(`bosses/${boss}/boss.json`, SCOPE), { cache: "no-cache" });
    info = r.ok ? await r.json() : null;
  } catch (e) { info = null; }
  infoFor = boss;
  return info;
}

self.addEventListener("message", (e) => {
  const m = e.data || {};
  if (m.type === "setBoss") {
    e.waitUntil((async () => {
      await setBoss(m.boss);
      const inf = await bossInfo(m.boss);
      if (e.source) e.source.postMessage({ type: "bossSet", boss: m.boss, found: !!inf });
    })());
  } else if (m.type === "stats" && e.source) {
    e.source.postMessage({ type: "stats", stats });
  }
});

async function patchedData(request, inf) {
  const r = await fetch(request);
  const root = await r.json();
  const objects = root.project[3];
  for (const t of objects) {
    if (Array.isArray(t) && t[0] === "Bowser" && Array.isArray(t[7])) {
      for (const anim of t[7]) {
        if (inf.bowserFrames[anim[0]]) anim[7] = inf.bowserFrames[anim[0]];
      }
    }
  }
  stats.data++;
  return new Response(JSON.stringify(root), { headers: { "Content-Type": "application/json" } });
}

async function handle(event, rel) {
  try {
    const boss = await getBoss();
    const inf = await bossInfo(boss);
    if (inf) {
      if (rel === "data.json" && inf.bowserFrames) return await patchedData(event.request, inf);
      if (inf.images && inf.images.includes(rel)) {
        const r = await fetch(new URL(`bosses/${boss}/${rel}`, SCOPE), { cache: "no-cache" });
        if (r.ok) { stats.images++; return r; }
      }
    }
  } catch (e) {
    console.warn("[Boss Picker] fell back to the original file:", rel, e);
  }
  return fetch(event.request);
}

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== SCOPE.origin || !url.pathname.startsWith(SCOPE.pathname)) return;
  const rel = url.pathname.slice(SCOPE.pathname.length);
  if (rel === "data.json" || (rel.startsWith("images/") && rel.endsWith(".webp"))) {
    event.respondWith(handle(event, rel));
  }
});
