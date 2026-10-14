// Recording playback inside the dashboard.
import { creds, ids, launch, out, sleep, suite } from "../lib.mjs";

const t = suite("Recording playback");
const b = await launch({ out, name: "main", height: 1000 });

await b.login(...creds.owner);
await b.waitForPath(`/sites/${ids.demoSite}`);

// Pick a short recording (a long one can take a minute to download).
const listing = await b.eval(`fetch("http://localhost:8000/api/websites/${ids.demoSite}/recordings?days=90&limit=50", { credentials: "include" })
  .then(async (r) => ({ status: r.status, body: await r.json() }))`);
if (!listing.body.results) console.log("recordings request failed:", listing.status, JSON.stringify(listing.body));
const shortest = (listing.body.results ?? []).filter((x) => x.duration >= 15).sort((a, c) => a.duration - c.duration)[0] ?? null;
t.check("there is a recording to play", shortest !== null);
if (!shortest) t.finish(b);

// The list: rows open the player, and nothing mentions PostHog
await b.goto(`/sites/${ids.demoSite}/recordings`);
t.check("recordings list loads", await b.waitFor(`document.querySelectorAll("tbody tr").length > 0`, 30000));
t.check("  ...rows say 'Play' and nothing links to PostHog", await b.eval(`document.body.innerText.includes("Play") && !document.body.innerHTML.toLowerCase().includes("posthog")`));

// The player
await b.goto(`/sites/${ids.demoSite}/recordings/${shortest.id}`);
t.check("the player appears", await b.waitFor(`!!document.querySelector(".rr-player")`, 90000));
await sleep(1000);
t.check("  ...it replays the visitor's page", await b.eval(`!!document.querySelector(".rr-player iframe")`));
t.check("  ...with a timeline and speed buttons", await b.eval(`(document.querySelector(".rr-controller")?.innerText ?? "").includes("1x")`));
await b.eval(`document.querySelector(".rr-controller__btns button")?.click()`);
await sleep(4000);
const seconds = await b.eval(`document.querySelector(".rr-timeline__time")?.innerText`);
t.check("pressing play moves the clock", /^00:0[1-9]/.test(seconds ?? ""), `clock shows ${seconds}`);
const pageText = await b.eval(`(() => { try { return document.querySelector(".rr-player iframe").contentDocument.body.innerText.length } catch { return -1 } })()`);
t.check("the replayed page has real content", pageText > 20, `${pageText} characters`);
const mentions = await b.eval(`(() => { const h = document.body.innerHTML, low = h.toLowerCase(), out = []; let i = low.indexOf("posthog");
  while (i >= 0 && out.length < 4) { out.push(h.slice(Math.max(0, i - 100), i + 60).replace(/\s+/g, " ")); i = low.indexOf("posthog", i + 7); } return out; })()`);
t.check("nothing on the page mentions PostHog", mentions.length === 0, mentions.length ? "found: " + JSON.stringify(mentions) : "");
await b.shot("player");

// Another client's recording id can't be fetched through this website
const missing = await b.apiStatus(`/api/websites/${ids.demoSite}/recordings/00000000-0000-0000-0000-000000000000`);
t.check("a made-up recording id answers 404 (not found)", missing === 404, `got ${missing}`);

t.finish(b);
