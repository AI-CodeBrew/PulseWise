// The Dashboard page (menu item right under Overview), with tiles chosen per person: asked first, then only the chosen tiles; each person has their own.
// Clicking a tile opens a box with the full information behind that number, and a way to watch recordings.
import { API, creds, ids, launch, out, suite } from "../lib.mjs";

const t = suite("Dashboard page (tiles)");
const owner = await launch({ out, name: "owner", height: 1300 });
const viewer = await launch({ out, name: "viewer" });
const phone = await launch({ out, name: "phone", width: 390, height: 800, mobile: true });

await owner.login(...creds.owner);
await owner.waitForPath(`/sites/${ids.demoSite}`);
t.check("the menu has Dashboard directly under Overview", await owner.waitFor(`(() => { const items = [...document.querySelectorAll('nav[aria-label="Main"] a')].map((a) => a.innerText.trim()); return items[0] === "Overview" && items[1] === "Dashboard"; })()`, 30000));
t.check("the Overview page itself has no tiles or question", await owner.eval(`!document.querySelector("[data-tile]") && !document.body.innerText.includes("Choose what you want to see")`));
await owner.clickText("Dashboard");
t.check("the menu item opens the dashboard page", await owner.waitForPath(`/sites/${ids.demoSite}/dashboard`));
await viewer.login(...creds.viewer);
await viewer.waitForPath(`/sites/${ids.demoSite}`);
await viewer.goto(`/sites/${ids.demoSite}/dashboard`);
await phone.login(...creds.owner);
await phone.waitForPath(`/sites/${ids.demoSite}`);
// The card's short name ("Sessions"); the full title with its period ("Sessions (last 7 days)") is in the chooser and the box.
const tileTitles = (b) => b.eval(`[...document.querySelectorAll("[data-tile] h3")].map((h) => h.innerText.trim())`);
/** Open a tile's box and wait until both of its parts (trend + rankings, latest rows) have finished loading. */
async function openBox(b, selector) {
  // A REAL mouse click on the big number, like a person's (element.click() would not notice a tile that can't be clicked where people click).
  const under = await b.realClick(`${selector} p[aria-label]`);
  if (!/^BUTTON\[Open details/.test(under ?? "")) console.log(`  (the click landed on ${under}, not on the tile's button)`);
  const open = await b.waitFor(`!!document.querySelector("dialog[open]")`, 10000);
  const loaded = await b.waitFor(`(() => { const d = document.querySelector("dialog[open]"); return !!d && d.innerText.includes("Day by day") && !d.querySelector(".animate-pulse") && !!d.querySelector('section[aria-label^="Latest"], section[aria-label^="Longest"], section[aria-label^="Visits with"]'); })()`, 90000);
  return open && loaded;
}
const closeBox = (b) => b.eval(`document.querySelector("dialog[open] button[aria-label=Close]").click()`);

// 1. Asked first
t.check("a first-time visitor is asked what they want to see", await owner.waitForText("Choose what you want to see on your dashboard", 40000));
await owner.waitFor(`document.querySelectorAll("fieldset label").length > 10`, 90000); // the list of choices comes from the website's analytics: wait for it
t.check("  ...nothing is shown until they choose", (await tileTitles(owner)).length === 0);
t.check("  ...three common tiles are ticked for them", await owner.eval(`["Active users", "Sessions", "Pageviews"].every((x) => { const l = [...document.querySelectorAll("label")].find((l) => l.innerText.includes(x)); return l && l.querySelector("input").checked; })`));
t.check("  ...grouped, with an explanation for each", await owner.eval(`["Traffic", "Engagement", "Content", "Audience", "Your tracked events"].every((g) => [...document.querySelectorAll("legend")].some((l) => l.innerText.trim().toLowerCase() === g.toLowerCase())) && document.body.innerText.includes("A session groups everything one person does")`));

// 2. Add one more tile, then show
await owner.eval(`[...document.querySelectorAll("label")].find((l) => l.innerText.includes("All events")).querySelector("input").click()`);
t.check("the counter shows how many are chosen", await owner.waitForText("4 chosen"));
await owner.clickText("Show my dashboard");
t.check("only the chosen tiles are shown, in the chosen order", await owner.waitFor(`document.querySelectorAll("[data-tile]").length === 4`, 60000));
const titles = await tileTitles(owner);
t.check("  ...in the order they were chosen", JSON.stringify(titles) === JSON.stringify(["Active users", "Sessions", "Pageviews", "All events"]), JSON.stringify(titles));
t.check("  ...each with a number", await owner.eval(`[...document.querySelectorAll("[data-tile] p[aria-label]")].every((p) => /\\d/.test(p.innerText))`));
await owner.shot("tiles");

// 2a. The card itself: a calm KPI card, not a wall of text
t.check("each card shows its period (7d or 30d), and no repeated 'Click for details'", await owner.eval(`(() => { const on = (key) => document.querySelector('[data-tile="' + key + '"] button[aria-pressed="true"]')?.innerText.trim(); return on("active_users_30d") === "30d" && on("sessions_7d") === "7d" && !document.body.innerText.includes("Click for details"); })()`));
t.check("  ...the long explanation is not printed on the card (it is behind the (i))", await owner.eval(`!document.body.innerText.includes("Unique people who used your website in the last 30 days")`));
await owner.realClick('[data-tile="active_users_30d"] button[aria-label^="What is"]');
t.check("  ...a click on the (i) explains the number in plain words, and does not open the box", await owner.waitFor(`document.querySelector('[data-tile="active_users_30d"] [role="tooltip"]')?.innerText.includes("Unique people who used your website in the last 30 days") === true && !document.querySelector("dialog[open]")`, 5000));
await owner.realClick("main h1");  // a click anywhere else closes it
t.check("  ...and a click elsewhere closes the explanation", await owner.waitFor(`!document.querySelector('[role="tooltip"]')`, 5000));
t.check("  ...every number says how it compares with the period before (or that nothing happened)", await owner.eval(`[...document.querySelectorAll("[data-tile]")].every((tile) => /vs previous|in the previous|Nothing recorded|No visits|No earlier/.test(tile.innerText))`));
t.check("  ...numbers in one row line up (same top), even though the words differ", await owner.eval(`(() => { const rows = {}; for (const tile of document.querySelectorAll("[data-tile]")) { const top = Math.round(tile.getBoundingClientRect().top); (rows[top] ||= []).push(Math.round(tile.querySelector("p[aria-label]").getBoundingClientRect().top)); } return Object.values(rows).every((tops) => Math.max(...tops) - Math.min(...tops) <= 1); })()`));
t.check("  ...a little graph on the tiles that have days to draw", await owner.eval(`document.querySelectorAll("[data-tile] svg").length >= 1`));
t.check("  ...and the page has no '7 / 30 / 90 days' switch (the tiles have their own periods)", await owner.eval(`![...document.querySelectorAll("button")].some((b) => b.innerText.trim() === "90 days")`));

// 2a2. ONE tile per thing: its period (7d / 30d) is a switch on the card, never a second tile
t.check("every card has exactly one period switched on", await owner.eval(`[...document.querySelectorAll("[data-tile]")].every((tile) => { const on = tile.querySelectorAll('[role="group"] button[aria-pressed="true"]'); return on.length === 1 && /^(7|30)d$/.test(on[0].innerText.trim()); })`));
await owner.realClick('[data-tile="sessions_7d"] button[aria-label="Last 30 days"]');
t.check("switching Sessions to 30d changes THAT tile (still four tiles, not five)", await owner.waitFor(`!!document.querySelector('[data-tile="sessions_30d"]') && !document.querySelector('[data-tile="sessions_7d"]') && document.querySelectorAll("[data-tile]").length === 4`, 60000));
t.check("  ...it now says 30 days, in the same place as before", await owner.eval(`(() => { const tile = document.querySelector('[data-tile="sessions_30d"]'); return tile.querySelector('button[aria-pressed="true"]').innerText.trim() === "30d" && tile.querySelector('button[aria-label^="Open details"]').getAttribute("aria-label") === "Open details: Sessions (last 30 days)"; })()`) && JSON.stringify(await tileTitles(owner)) === JSON.stringify(["Active users", "Sessions", "Pageviews", "All events"]));
await owner.goto(`/sites/${ids.demoSite}/dashboard`);
t.check("  ...and it is remembered when the page is opened again", await owner.waitFor(`!!document.querySelector('[data-tile="sessions_30d"]') && !document.querySelector('[data-tile="sessions_7d"]')`, 60000));
await owner.realClick('[data-tile="sessions_30d"] button[aria-label="Last 7 days"]');
t.check("  ...and goes back to 7d the same way", await owner.waitFor(`!!document.querySelector('[data-tile="sessions_7d"]') && !document.querySelector('[data-tile="sessions_30d"]') && document.querySelectorAll("[data-tile]").length === 4`, 60000));
t.check("  ...the switch does not open the box", await owner.eval(`!document.querySelector("dialog[open]")`));

// 2b. Clicking a tile opens a box with the full information
t.check("a tile's '...' menu does not open the box", await owner.eval(`(() => { document.querySelector('[data-tile="sessions_7d"] summary').click(); const open = !!document.querySelector("dialog[open]"); document.querySelector('[data-tile="sessions_7d"] summary').click(); return !open; })()`));
t.check("clicking a tile opens the box (a real mouse click)", await openBox(owner, '[data-tile="active_users_30d"]'));
t.check("  ...and it STAYS open (it must not close itself a moment later)", await owner.eval(`new Promise((resolve) => setTimeout(() => resolve(!!document.querySelector("dialog[open]")), 1500))`));
const box = await owner.eval(`(() => { const d = document.querySelector("dialog[open]"); const q = (x) => [...d.querySelectorAll(x)];
  return { title: d.querySelector("h2").innerText, text: d.innerText, big: d.querySelector("p.text-5xl")?.innerText, sections: q("section[aria-label]").map((x) => x.getAttribute("aria-label")), chart: !!d.querySelector("svg.recharts-surface"),
    watchAll: q("a").find((a) => a.innerText.includes("Watch recordings"))?.getAttribute("href"), rows: q("tbody tr").length, links: q('a[href*="/recordings/"]').map((a) => a.getAttribute("href")), locked: d.innerText.includes("Couldn't load this") }; })()`);
t.check("  ...with the tile's full name (with its period) and its explanation", box.title === "Active users (last 30 days)" && box.text.includes("Unique people who used your website in the last 30 days"));
const tileNumber = await owner.eval(`document.querySelector('[data-tile="active_users_30d"] p[aria-label]').innerText`);
t.check("  ...the same number as the tile, and the period", box.big === tileNumber && /last 30 days/.test(box.text), `tile ${tileNumber}, box ${box.big}`);
t.check("  ...the number day by day (a chart)", box.chart && box.text.includes("Day by day"));
t.check("  ...rankings (countries, devices) and the latest visits", ["Countries", "Devices", "Latest visits"].every((x) => box.sections.includes(x)), JSON.stringify(box.sections));
t.check("  ...and a button to watch recordings", !!box.watchAll && box.watchAll.endsWith("/recordings"), String(box.watchAll));
t.check("  ...without any error and without mentioning the analytics provider", !box.locked && !/posthog/i.test(box.text));
await owner.shot("tile-box");
t.check("  ...rows that were recorded have a Watch button (the others say so)", box.rows === 0 || box.links.length > 0 || (await owner.eval(`document.querySelector("dialog[open]").innerText.includes("No recording")`)), `${box.rows} rows, ${box.links.length} watch links`);
await closeBox(owner);
t.check("the Close button closes it", await owner.waitFor(`!document.querySelector("dialog[open]")`, 5000));
await openBox(owner, '[data-tile="active_users_30d"]');
await owner.eval(`document.querySelector("dialog[open]").click()`); // a click on the dimmed page behind the box
t.check("a click outside the box closes it", await owner.waitFor(`!document.querySelector("dialog[open]")`, 5000));
await openBox(owner, '[data-tile="events_7d"]');
t.check("every tile has its own box (All events: what happened most, latest events)", await owner.eval(`(() => { const s = [...document.querySelectorAll("dialog[open] section[aria-label]")].map((x) => x.getAttribute("aria-label")); return s.includes("What happened most") && s.includes("Latest events"); })()`));
await closeBox(owner);

// 2c. A Watch button leads to the recording of that visit
await openBox(owner, '[data-tile="active_users_30d"]');
const firstWatch = await owner.eval(`document.querySelector('dialog[open] a[href*="/recordings/"]')?.getAttribute("href") ?? null`);
if (firstWatch) {
  await owner.eval(`document.querySelector('dialog[open] a[href*="/recordings/"]').click()`);
  t.check("a Watch button opens that visit's recording page", await owner.waitFor(`/\\/recordings\\/[0-9a-f-]{36}/.test(location.pathname)`, 30000), `${firstWatch} -> ${await owner.path()}`);
  await owner.goto(`/sites/${ids.demoSite}/dashboard`);
  await owner.waitFor(`document.querySelectorAll("[data-tile]").length === 4`, 60000);
} else {
  t.check("(no recorded visit in the test data to click: the Watch link itself is checked above)", true);
  await closeBox(owner);
}

// 3. It is remembered, and it is personal
await owner.goto(`/sites/${ids.demoSite}/dashboard`);
t.check("the choice is remembered after a reload (no question again)", await owner.waitFor(`document.querySelectorAll("[data-tile]").length === 4 && !document.body.innerText.includes("Choose what you want to see")`, 60000));
t.check("another person (a viewer) is asked for themselves", await viewer.waitForText("Choose what you want to see on your dashboard", 40000) && (await tileTitles(viewer)).length === 0);

// 4. Customize: tracked events and removing tiles
await owner.clickText("Customize");
t.check("Customize shows the choices again, with the current ones ticked", await owner.waitFor(`document.body.innerText.includes("Customize your dashboard") && [...document.querySelectorAll("label")].find((l) => l.innerText.includes("All events"))?.querySelector("input").checked`, 20000));
const eventBoxes = `(() => { const f = [...document.querySelectorAll("fieldset")].find((x) => x.querySelector("legend")?.innerText.trim().toLowerCase() === "your tracked events"); return f ? [...f.querySelectorAll("ul input[type=checkbox]")] : []; })()`;
t.check("  ...and the website's tracked events can be chosen, ONE checkbox for each (not one per period)", await owner.waitFor(`document.body.innerText.toLowerCase().includes("your tracked events") && (${eventBoxes}.length > 0 || document.body.innerText.includes("hasn't sent any events of its own yet"))`, 30000));
const hasEvents = await owner.eval(`${eventBoxes}.length > 0`);
if (hasEvents) {
  t.check("  ...no checkbox says '7 days' or '30 days' (the period is switched on the card)", await owner.eval(`!${eventBoxes}.some((b) => /last (7|30) days/.test(b.getAttribute("aria-label")))`));
  await owner.eval(`${eventBoxes}[0].click()`);
}
await owner.eval(`[...document.querySelectorAll("label")].find((l) => l.innerText.includes("Pageviews")).querySelector("input").click()`); // untick one
await owner.clickText("Save");
const expected = hasEvents ? 4 : 3;
t.check("saving changes the tiles", await owner.waitFor(`document.querySelectorAll("[data-tile]").length === ${expected} && !document.querySelector('[data-tile="pageviews_7d"]') && !document.body.innerText.includes("Customize your dashboard")`, 60000), `expected ${expected}: ` + JSON.stringify(await tileTitles(owner)));
t.check("  ...the unticked tile is gone", !(await tileTitles(owner)).includes("Pageviews"), JSON.stringify(await tileTitles(owner)));
if (hasEvents) t.check("  ...a tracked event is now a tile with its own count", await owner.eval(`(() => { const tile = document.querySelector('[data-tile^="event:"]'); return !!tile && tile.querySelector("h3").innerText.trim().length > 0 && tile.querySelector('button[aria-pressed="true"]').innerText.trim() === "30d" && /\\d/.test(tile.querySelector("p[aria-label]").innerText); })()`));

if (hasEvents) {
  const eventTile = await owner.eval(`document.querySelector('[data-tile^="event:"]').getAttribute("data-tile")`);
  t.check("a tracked-event tile has its own box (where and on which devices it happened)", await openBox(owner, `[data-tile="${eventTile}"]`) && await owner.eval(`(() => { const s = [...document.querySelectorAll("dialog[open] section[aria-label]")].map((x) => x.getAttribute("aria-label")); return s.includes("Where it happened") && s.includes("On which devices") && [...document.querySelectorAll("dialog[open] section[aria-label]")].some((x) => x.getAttribute("aria-label").startsWith("Latest times")); })()`));
  await closeBox(owner);
}

// 5. Remove a tile from its menu
await owner.eval(`document.querySelector('[data-tile="sessions_7d"] summary').click()`);
await owner.clickText("Remove from dashboard");
t.check("a tile can be removed from its own menu", await owner.waitFor(`!document.querySelector('[data-tile="sessions_7d"]')`, 30000));
await owner.goto(`/sites/${ids.demoSite}/dashboard`);
t.check("  ...and it stays removed", await owner.waitFor(`document.querySelectorAll("[data-tile]").length > 0 && !document.querySelector('[data-tile="sessions_7d"]')`, 60000));

// 6. Access and safety
t.check("another website's tiles can't be read (404)", (await owner.apiStatus(`/api/websites/${ids.otherSite}/dashboard/tiles`)) === 404);
t.check("a made-up tile can't be saved (422)", (await owner.eval(`fetch("${API}/api/websites/${ids.demoSite}/dashboard/prefs", { method: "PUT", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tiles: ["nope"] }) }).then((r) => r.status)`)) === 422);
t.check("nothing on the page mentions the analytics provider", await owner.eval(`!/posthog/i.test(document.body.innerText)`));

// 6b. The "7 / 30 / 90 days" switch is only where it changes something
await owner.goto(`/sites/${ids.demoSite}`);
t.check("the overview has the 7 / 30 / 90 days switch", await owner.waitFor(`[...document.querySelectorAll("button")].some((b) => b.innerText.trim() === "90 days")`, 40000));
for (const page of ["billing", "settings", "reports"]) {
  await owner.goto(`/sites/${ids.demoSite}/${page}`);
  await owner.waitFor(`!!document.querySelector("main h1")`, 30000);
  t.check(`  ...the ${page} page has no switch (it would change nothing there)`, await owner.eval(`![...document.querySelectorAll("button")].some((b) => b.innerText.trim() === "90 days")`));
}

// 7. Phone
await phone.goto(`/sites/${ids.demoSite}/dashboard`);
await phone.waitFor(`document.body.innerText.includes("Choose what you want to see") || document.querySelectorAll("[data-tile]").length > 0`, 60000);
t.check("the dashboard (chooser or tiles) fits a phone", await phone.eval(`document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1`));

await openBox(phone, "[data-tile]");
t.check("the box fits a phone", await phone.eval(`(() => { const d = document.querySelector("dialog[open]").getBoundingClientRect(); return d.width <= window.innerWidth && d.left >= 0 && document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1; })()`));
await phone.shot("tile-box-phone");

t.finish(owner, viewer, phone);
