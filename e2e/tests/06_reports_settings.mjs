// Phase 8: weekly reports (made by the admin here, normally by the Monday job), the client's Settings page
// (business details, logo, team) and the pieces of the admin panel that go with them.
import { API, creds, ids, launch, out, suite } from "../lib.mjs";

const t = suite("Weekly reports, settings and team");
const admin = await launch({ out, name: "admin", height: 1100 });
const owner = await launch({ out, name: "owner", height: 1100 });
const viewer = await launch({ out, name: "viewer" });
const otherOwner = await launch({ out, name: "other" });
const phone = await launch({ out, name: "phone", width: 390, height: 800, mobile: true });

await admin.login(...creds.admin);
await admin.waitForPath("/admin");
for (const [b, who, home] of [[owner, creds.owner, ids.demoSite], [viewer, creds.viewer, ids.demoSite], [otherOwner, creds.other, ids.otherSite], [phone, creds.owner, ids.demoSite]]) {
  await b.login(...who);
  await b.waitForPath(`/sites/${home}`);
}
const json = (b, path) => b.eval(`fetch(${JSON.stringify(API + path)}, { credentials: "include" }).then((r) => r.json())`);

// 1. The admin makes last week's report
await admin.goto("/admin/jobs");
t.check("the weekly job is listed with the other background jobs", await admin.waitFor(`document.body.innerText.includes("Weekly reports")`, 20000));
await admin.goto("/admin/settings");
t.check("the admin Settings page has the AI switch and model", await admin.waitFor(`document.body.innerText.includes("Let AI write the report summaries") && document.body.innerText.includes("AI model for report summaries")`, 20000));

await admin.goto(`/admin/websites/${ids.demoSite}`);
await admin.waitForText("Weekly report");
await admin.clickText("Make report");
t.check("the admin can make a report now (real numbers from the analytics)", await admin.waitForText("Report made.", 120000));

// 2. The client reads it
await owner.goto(`/sites/${ids.demoSite}/reports`);
t.check("the owner's menu has Weekly reports and Settings", await owner.waitFor(`["Weekly reports", "Settings"].every((x) => [...document.querySelectorAll('nav[aria-label="Main"] a')].some((a) => a.innerText.trim().startsWith(x)))`, 30000));
t.check("the list shows the week", await owner.waitFor(`/[A-Z][a-z]{2} \\d+ – [A-Z][a-z]{2} \\d+/.test(document.body.innerText) && document.body.innerText.includes("Not sent")`, 30000));
await owner.eval(`document.querySelector("tbody tr a").click()`);
t.check("opening it shows the written summary and what to do this week", await owner.waitFor(`document.body.innerText.includes("This week:") && /Week of/.test(document.body.innerText)`, 30000));
t.check("  ...the numbers behind it", await owner.eval(`["Visitors", "Pageviews", "Bounce rate", "Top pages", "Countries", "Devices"].every((x) => document.body.innerText.includes(x))`));
t.check("  ...and says how it was written", await owner.eval(`document.body.innerText.includes("Automatic summary") || document.body.innerText.includes("Written by AI")`));
t.check("  ...without mentioning the analytics provider", await owner.eval(`!/posthog/i.test(document.body.innerText)`));
const pdf = await owner.eval(`(() => { const a = [...document.querySelectorAll("a")].find((x) => x.innerText.includes("Download PDF")); return fetch(a.href, { credentials: "include" }).then(async (r) => ({ status: r.status, type: r.headers.get("content-type"), start: new TextDecoder().decode((await r.arrayBuffer()).slice(0, 5)) })); })()`);
t.check("  ...and the PDF downloads", pdf.status === 200 && pdf.type === "application/pdf" && pdf.start === "%PDF-", JSON.stringify(pdf));
await owner.shot("report");

t.check("a viewer can read the reports too", await viewer.eval(`1`) && (await viewer.apiStatus(`/api/websites/${ids.demoSite}/reports`)) === 200);
t.check("another client's owner cannot", (await otherOwner.apiStatus(`/api/websites/${ids.demoSite}/reports`)) === 404);

// 3. Settings: who may open the page
await viewer.goto(`/sites/${ids.demoSite}/settings`);
t.check("a viewer is told only the owner can change settings", await viewer.waitForText("Only the account owner can change settings"));
t.check("  ...and their menu doesn't offer it", await viewer.eval(`![...document.querySelectorAll('nav[aria-label="Main"] a')].some((a) => a.innerText.trim() === "Settings")`));
t.check("  ...and the server refuses them too", (await viewer.apiStatus(`/api/clients/${ids.demoClient}/settings`)) === 403);

// 4. Settings: business details
await owner.goto(`/sites/${ids.demoSite}/settings`);
await owner.waitForText("Your business");
await owner.waitFor(`!!document.querySelector("form input[type=text], form input:not([type])")`);
t.check("the page has no time zone, report language or logo settings", await owner.eval(`!document.body.innerText.includes("Time zone") && !document.body.innerText.includes("Report language") && !document.body.innerText.includes("Your logo") && !document.querySelector("input[type=file]")`));
await owner.fillLabel("Business name", "Demo Shop E2E");
await owner.clickText("Save changes");
t.check("business details can be saved", await owner.waitForText("Saved."));
const saved = await json(owner, `/api/clients/${ids.demoClient}/settings`);
t.check("  ...and are stored", saved.name === "Demo Shop E2E" && saved.timezone === "Asia/Karachi" && saved.report_language === "en", JSON.stringify(saved));
await owner.fillLabel("Business name", "Demo Shop");
await owner.clickText("Save changes");
await owner.waitFor(`!!document.body.innerText.match(/Saved\\./)`);
t.check("  ...and can be put back", (await json(owner, `/api/clients/${ids.demoClient}/settings`)).name === "Demo Shop");

// 4b. Settings: WhatsApp (the fields only exist when the server has WhatsApp set up; the test server has fake keys)
await owner.fillLabel("WhatsApp number", "0300 1234567");
await owner.clickText("Save changes");
t.check("a WhatsApp number without a country code is refused", await owner.waitForText("with its country code"));
await owner.fillLabel("WhatsApp number", "+92 300 1234567");
await owner.eval(`(() => { const box = [...document.querySelectorAll("label")].find((l) => l.innerText.includes("Also send me the weekly report on WhatsApp")).querySelector("input"); box.click(); })()`);
await owner.clickText("Save changes");
t.check("a number with a country code is saved and the opt-in is on", await owner.waitForText("Saved."));
const wa = await json(owner, `/api/clients/${ids.demoClient}/settings`);
t.check("  ...stored in plain international form", wa.whatsapp_number === "923001234567" && wa.whatsapp_reports_enabled === true, JSON.stringify(wa));
await owner.fillLabel("WhatsApp number", "");
await owner.clickText("Save changes");
await owner.waitFor(`!!document.body.innerText.match(/Saved\./)`);
t.check("  ...and clearing the number switches it off", await owner.waitFor(`true`) && (await json(owner, `/api/clients/${ids.demoClient}/settings`)).whatsapp_reports_enabled === false);

// 6. Settings: team
await owner.eval(`window.confirm = () => true`);
await owner.fillLabel("Email", "newbie@demo.test");
await owner.fillLabel("Name (optional)", "Newbie");
await owner.clickText("Add person");
t.check("an owner can give a new person access", await owner.waitForText("newbie@demo.test now has access."));
t.check("  ...and gets a one-time link to hand over", await owner.eval(`document.body.innerText.includes("/reset-password?token=")`));
t.check("  ...the person is listed", await owner.waitFor(`!!document.querySelector('select[aria-label="Role of newbie@demo.test"]')`, 20000));

await owner.fillLabel("Email", "other@other.test");
await owner.clickText("Add person");
t.check("adding someone who already has an account makes NO link (nobody can take over their account)", await owner.waitFor(`document.body.innerText.includes("other@other.test now has access.") && document.body.innerText.includes("They already have an account") && !document.body.innerText.includes("/reset-password?token=")`, 20000));

// A login created by the owner, with a password (no email, no link)
await owner.fillLabel("Email", "gmailuser@demo.test");
await owner.fillLabel("Password for them (optional)", "Gmail-User-Pass-1");
await owner.clickText("Add person");
t.check("with a password, the owner gets the login details to hand over (no link)", await owner.waitFor(`document.body.innerText.includes("gmailuser@demo.test now has access.") && document.body.innerText.includes("Password: Gmail-User-Pass-1") && !document.body.innerText.includes("/reset-password?token=")`, 20000));
const person = await launch({ out, name: "person" });
await person.login("gmailuser@demo.test", "Gmail-User-Pass-1");
t.check("that person can log in with the password and sees the dashboard", await person.waitForPath(`/sites/${ids.demoSite}`));

await owner.eval(`document.querySelector('button[aria-label="Suspend gmailuser@demo.test"]').click()`);
t.check("suspending marks them as suspended on the list", await owner.waitFor(`document.body.innerText.includes("Suspended") && !!document.querySelector('button[aria-label="Activate gmailuser@demo.test"]')`, 20000));
t.check("  ...and they are locked out at once (no websites, no data)", (await json(person, "/api/auth/me")).websites.length === 0 && (await person.apiStatus(`/api/websites/${ids.demoSite}/overview`)) === 404);
await owner.eval(`document.querySelector('button[aria-label="Activate gmailuser@demo.test"]').click()`);
t.check("activating lets them back in", await owner.waitFor(`!document.body.innerText.includes("Suspended")`, 20000) && (await json(person, "/api/auth/me")).websites.length === 1);

await owner.eval(`document.querySelector('button[aria-label="Set a new password for gmailuser@demo.test"]').click()`);
await owner.fillLabel("New password", "Changed-Pass-2");
await owner.clickText("Save password");
t.check("the owner can set a new password for them", await owner.waitForText("New password set for gmailuser@demo.test"));
t.check("  ...which logs the old session out", (await person.apiStatus("/api/auth/me")) === 401);
await person.login("gmailuser@demo.test", "Changed-Pass-2");
t.check("  ...and the new password works", await person.waitForPath(`/sites/${ids.demoSite}`));
await owner.eval(`document.querySelector('button[aria-label="Remove gmailuser@demo.test"]').click()`);
t.check("they can be removed", await owner.waitFor(`!document.querySelector('select[aria-label="Role of gmailuser@demo.test"]')`, 20000));
t.check("  ...and then have no access", (await json(person, "/api/auth/me")).websites.length === 0);

// The only owner can't step down (an account always keeps an owner)...
await owner.fill('select[aria-label="Role of owner@demo.test"]', "viewer");
t.check("the only owner can't step down", await owner.waitForText("An account needs at least one active owner."));
// ...but another person can be promoted, and everyone can be removed again.
await owner.fill('select[aria-label="Role of newbie@demo.test"]', "owner");
t.check("a role can be changed", await owner.waitFor(`document.querySelector('select[aria-label="Role of newbie@demo.test"]').value === "owner"`, 20000));
await owner.eval(`document.querySelector('button[aria-label="Remove newbie@demo.test"]').click()`);
await owner.eval(`document.querySelector('button[aria-label="Remove other@other.test"]').click()`);
t.check("people can be removed again", await owner.waitFor(`!document.querySelector('select[aria-label="Role of newbie@demo.test"]') && !document.querySelector('select[aria-label="Role of other@other.test"]')`, 20000));
const team = await json(owner, `/api/clients/${ids.demoClient}/team`);
t.check("  ...leaving the original team", team.members.map((m) => m.email).sort().join() === "owner@demo.test,resetme@demo.test,viewer@demo.test", JSON.stringify(team.members.map((m) => m.email)));

// 7. Phone width
await phone.goto(`/sites/${ids.demoSite}/reports`);
await phone.waitFor(`document.body.innerText.includes("Weekly reports")`, 30000);
t.check("the reports list fits a phone", await phone.eval(`document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1`));
await phone.goto(`/sites/${ids.demoSite}/settings`);
await phone.waitFor(`document.body.innerText.includes("People with access")`, 30000);
t.check("the settings page fits a phone", await phone.eval(`document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1`));

t.finish(admin, owner, viewer, otherOwner, phone, person);
