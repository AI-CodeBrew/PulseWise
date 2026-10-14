// Phase 6: usage and cost, alerts, background jobs, settings.
import { creds, ids, launch, out, sleep, suite } from "../lib.mjs";

const t = suite("Usage, alerts, jobs, settings");
const admin = await launch({ out, name: "admin", height: 1000 });
await admin.login(...creds.admin);
await admin.waitForPath(`/sites/${ids.demoSite}`);

// 1. Background jobs: run the usage count by hand
await admin.goto("/admin/jobs");
t.check("jobs page lists both jobs", await admin.waitFor(`document.body.innerText.includes("Count events per website") && document.body.innerText.includes("Check that data is still arriving")`));
t.check("  ...with their schedules", await admin.waitForText("Every hour"));
await admin.eval(`[...document.querySelectorAll("li")].find((li) => li.innerText.includes("Count events per website")).querySelector("button").click()`);
t.check("'Run now' starts the job and shows its result", await admin.waitFor(`document.body.innerText.includes("Synced 2 of 2 websites")`, 90000));
t.check("  ...marked as worked, started by the admin", await admin.eval(`document.body.innerText.includes("Worked") && document.body.innerText.includes("started by admin")`));

// 2. Usage and cost
await admin.goto("/admin/usage");
t.check("usage page shows the month and the cost estimate", await admin.waitFor(`document.body.innerText.includes("Cost so far (estimate)") && document.body.innerText.includes("first 1,000,000 events are free")`, 30000));
t.check("  ...counts both test websites, with PostHog's shared free allowance explained", await admin.waitFor(`document.body.innerText.includes("demo-shop.pk") && document.body.innerText.includes("other.example") && document.body.innerText.includes("shared by ALL your clients")`));
t.check("  ...says when the numbers were last updated", await admin.waitFor(`/Counts updated/.test(document.body.innerText)`));
const events = await admin.eval(`document.body.innerText`);
t.check("  ...an earlier month can be looked at", await admin.waitFor(`!!document.querySelector('[aria-label="Previous month"]')`));
await admin.eval(`document.querySelector('[aria-label="Previous month"]').click()`);
t.check("  ...going back a month changes the heading", await admin.waitFor(`!document.body.innerText.includes("Projected for the month")`, 20000));
await admin.shot("usage");

// 3. A website's own page has an events-per-day chart
await admin.goto(`/admin/websites/${ids.demoSite}`);
t.check("website page has the 'Events per day' card with a chart", await admin.waitFor(`document.body.innerText.includes("Events per day") && !!document.querySelector(".recharts-surface")`, 30000));
await admin.clickText("Table");
t.check("  ...and a table view of the same numbers", await admin.waitFor(`document.body.innerText.includes("Pageviews") && document.body.innerText.includes("Recordings")`));

// 4. Run the daily health check: silent websites become alerts
await admin.goto("/admin/jobs");
await admin.waitForText("Check that data is still arriving");
await admin.eval(`[...document.querySelectorAll("li")].find((li) => li.innerText.includes("Check that data is still arriving")).querySelector("button").click()`);
t.check("the health job runs and reports", await admin.waitFor(`/Checked 2 websites/.test(document.body.innerText)`, 90000));
const silent = /(\d) silent/.exec(await admin.text())?.[1];
await admin.goto("/admin/alerts");
await admin.waitForText("Alerts");
if (silent && silent !== "0") {
  t.check("silent websites appear on the Alerts page", await admin.waitFor(`document.body.innerText.includes("has sent no events for")`, 20000));
  t.check("  ...with a severity label and a link to the website", await admin.eval(`document.body.innerText.includes("Warning") && !![...document.querySelectorAll("a")].find((a) => a.href.includes("/admin/websites/"))`));
  t.check("the sidebar shows how many alerts are open", await admin.eval(`!!document.querySelector('nav[aria-label="Admin"] span.bg-bad')`));
  const before = await admin.eval(`document.querySelectorAll("ul > li").length`);
  await admin.clickText("Mark as dealt with");
  t.check("an alert can be marked as dealt with", await admin.waitFor(`document.querySelectorAll("ul > li").length === ${before - 1} || document.body.innerText.includes("Nothing needs your attention")`));
  t.check("  ...and the number in the menu goes down", await admin.waitFor(`(document.querySelector('nav[aria-label="Admin"] span.bg-bad')?.innerText ?? "0") === "${before - 1}" || ${before - 1} === 0`));
  await admin.clickText("Resolved", { exact: false });
  t.check("  ...it moves to the 'Resolved' tab", await admin.waitFor(`document.body.innerText.includes("resolved ")`));
} else {
  console.log("(PostHog data is recent, so no website is silent: skipping the alert steps)");
  t.check("with data arriving, there is nothing to alert about", await admin.waitForText("Nothing needs your attention"));
}

// 5. Settings
await admin.goto("/admin/settings");
t.check("settings page shows the settings with their defaults", await admin.waitFor(`document.body.innerText.includes("Alert when a website sends no events for") && document.body.innerText.includes("Default: 48")`));
await admin.fillLabel("Alert when a website sends no events for", "36");
await admin.clickText("Save settings");
t.check("saving shows a confirmation", await admin.waitForText("Saved"));
await admin.goto("/admin/settings");
t.check("the new value is remembered", await admin.waitFor(`[...document.querySelectorAll("label")].find((l) => l.innerText.startsWith("Alert when a website sends no events for")).querySelector("input").value === "36"`));
await admin.fillLabel("Alert when a website sends no events for", "1");
await admin.clickText("Save settings");
await sleep(500);
t.check("a value that is too small is blocked by the form (the backend refuses it too)", await admin.eval(`[...document.querySelectorAll("label")].find((l) => l.innerText.startsWith("Alert when a website sends no events for")).querySelector("input").validity.rangeUnderflow`));
t.check("  ...and nothing was saved", !(await admin.text()).includes("Saved"));
await admin.fillLabel("Alert when a website sends no events for", "48");
await admin.clickText("Save settings");
t.check("the default can be restored", await admin.waitForText("Saved"));

// 6. The overview ties it together
await admin.goto("/admin");
t.check("the admin overview shows open alerts and this month's PostHog cost", await admin.waitFor(`document.body.innerText.includes("Open alerts") && document.body.innerText.includes("This month at PostHog") && /events so far/.test(document.body.innerText)`, 30000));

// 7. A client can't see any of it
const client = await launch({ out, name: "client" });
await client.login(...creds.owner);
await client.waitForPath(`/sites/${ids.demoSite}`);
for (const path of ["/api/admin/usage", "/api/admin/alerts", "/api/admin/jobs", "/api/admin/settings"]) {
  t.check(`a client gets 403 from ${path}`, (await client.apiStatus(path)) === 403);
}
t.check("the client's dashboard never mentions costs or alerts", await client.eval(`!/estimate|PostHog|alert/i.test(document.body.innerText)`));

await sleep(200);
t.finish(admin, client);
