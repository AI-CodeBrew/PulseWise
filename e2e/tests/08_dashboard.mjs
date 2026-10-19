// The Dashboard page (menu item right under Overview), with tiles chosen per person: asked first, then only the chosen tiles; each person has their own.
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
const tileTitles = (b) => b.eval(`[...document.querySelectorAll("[data-tile] h3")].map((h) => h.innerText.replace("ⓘ", "").trim())`);

// 1. Asked first
t.check("a first-time visitor is asked what they want to see", await owner.waitForText("Choose what you want to see on your dashboard", 40000));
t.check("  ...nothing is shown until they choose", (await tileTitles(owner)).length === 0);
t.check("  ...three common tiles are ticked for them", await owner.eval(`["Active users (last 30 days)", "Sessions (last 7 days)", "Pageviews (last 7 days)"].every((x) => { const l = [...document.querySelectorAll("label")].find((l) => l.innerText.includes(x)); return l && l.querySelector("input").checked; })`));
t.check("  ...grouped, with an explanation for each", await owner.eval(`["Traffic", "Engagement", "Content", "Audience", "Your tracked events"].every((g) => [...document.querySelectorAll("legend")].some((l) => l.innerText.trim().toLowerCase() === g.toLowerCase())) && document.body.innerText.includes("A session groups everything one person does")`));

// 2. Add one more tile, then show
await owner.eval(`[...document.querySelectorAll("label")].find((l) => l.innerText.includes("All events (last 7 days)")).querySelector("input").click()`);
t.check("the counter shows how many are chosen", await owner.waitForText("4 chosen"));
await owner.clickText("Show my dashboard");
t.check("only the chosen tiles are shown, in the chosen order", await owner.waitFor(`document.querySelectorAll("[data-tile]").length === 4`, 60000));
const titles = await tileTitles(owner);
t.check("  ...in the order they were chosen", JSON.stringify(titles) === JSON.stringify(["Active users (last 30 days)", "Sessions (last 7 days)", "Pageviews (last 7 days)", "All events (last 7 days)"]), JSON.stringify(titles));
t.check("  ...each with a number", await owner.eval(`[...document.querySelectorAll("[data-tile] p[aria-label]")].every((p) => /\\d/.test(p.innerText))`));
t.check("  ...and an explanation", await owner.eval(`document.body.innerText.includes("Unique people who used your website in the last 30 days")`));
await owner.shot("tiles");

// 3. It is remembered, and it is personal
await owner.goto(`/sites/${ids.demoSite}/dashboard`);
t.check("the choice is remembered after a reload (no question again)", await owner.waitFor(`document.querySelectorAll("[data-tile]").length === 4 && !document.body.innerText.includes("Choose what you want to see")`, 60000));
t.check("another person (a viewer) is asked for themselves", await viewer.waitForText("Choose what you want to see on your dashboard", 40000) && (await tileTitles(viewer)).length === 0);

// 4. Customize: tracked events and removing tiles
await owner.clickText("Customize");
t.check("Customize shows the choices again, with the current ones ticked", await owner.waitFor(`document.body.innerText.includes("Customize your dashboard") && [...document.querySelectorAll("label")].find((l) => l.innerText.includes("All events (last 7 days)"))?.querySelector("input").checked`, 20000));
t.check("  ...and the website's tracked events can be chosen (7 or 30 days)", await owner.waitFor(`document.body.innerText.toLowerCase().includes("your tracked events") && (document.querySelectorAll('input[aria-label$="last 7 days"]').length > 0 || document.body.innerText.includes("hasn't sent any events of its own yet"))`, 30000));
const hasEvents = await owner.eval(`document.querySelectorAll('input[aria-label$="last 7 days"]').length > 0`);
if (hasEvents) {
  await owner.eval(`document.querySelector('input[aria-label$="last 7 days"]').click()`);
}
await owner.eval(`[...document.querySelectorAll("label")].find((l) => l.innerText.includes("Pageviews (last 7 days)")).querySelector("input").click()`); // untick one
await owner.clickText("Save");
const expected = hasEvents ? 4 : 3;
t.check("saving changes the tiles", await owner.waitFor(`document.querySelectorAll("[data-tile]").length === ${expected} && !document.querySelector('[data-tile="pageviews_7d"]') && !document.body.innerText.includes("Customize your dashboard")`, 60000), `expected ${expected}: ` + JSON.stringify(await tileTitles(owner)));
t.check("  ...the unticked tile is gone", !(await tileTitles(owner)).includes("Pageviews (last 7 days)"), JSON.stringify(await tileTitles(owner)));
if (hasEvents) t.check("  ...a tracked event is now a tile with its own count", await owner.eval(`!![...document.querySelectorAll("[data-tile] h3")].find((h) => /\\(last 7 days\\)/.test(h.innerText) && !/(Active|Sessions|All events|Pageviews)/.test(h.innerText))`));

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

// 7. Phone
await phone.goto(`/sites/${ids.demoSite}/dashboard`);
await phone.waitFor(`document.body.innerText.includes("Choose what you want to see") || document.querySelectorAll("[data-tile]").length > 0`, 60000);
t.check("the dashboard (chooser or tiles) fits a phone", await phone.eval(`document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1`));

t.finish(owner, viewer, phone);
