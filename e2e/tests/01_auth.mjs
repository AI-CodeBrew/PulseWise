// Phase 4: login, logout, website access, password reset, phone layout.
import { readFileSync } from "node:fs";

import { BASE, creds, ids, launch, out, sleep, suite } from "../lib.mjs";

const t = suite("Login and access");
const b = await launch({ out, name: "main" });
const [adminEmail, adminPass] = creds.admin;
const [ownerEmail, ownerPass] = creds.owner;
const [resetEmail] = creds.resetme; // the password-reset test changes this user's password, so it has its own

// 1. Logged out -> sent to /login, and brought back afterwards
await b.goto(`/sites/${ids.demoSite}/sessions?days=7`);
t.check("logged-out visitor is sent to /login", await b.waitForPath("/login"), await b.path());
t.check("  ...remembering the page they wanted", (await b.path()).includes("next=%2Fsites%2F"));

// 2. Wrong password
await b.fill("input[type=email]", adminEmail);
await b.fill("input[type=password]", "wrong-password");
await b.submit();
t.check("wrong password shows a friendly error", await b.waitForText("Wrong email or password"));

// 3. Admin logs in and returns to the wanted page, with data
await b.fill("input[type=password]", adminPass);
await b.submit();
t.check("admin login returns to the requested page", await b.waitForPath(`/sites/${ids.demoSite}/sessions`), await b.path());
t.check("  ...keeping ?days=7", (await b.path()).includes("days=7"));
// (The test project only gets traffic now and then, so "the last 7 days" can be empty: an empty list is fine, an error is not.)
t.check("sessions page loads (rows, or a plain 'no sessions' message)", await b.waitFor(`document.querySelectorAll("tbody tr").length > 0 || document.body.innerText.includes("No sessions in this period")`, 40000));
t.check("  ...without an error", await b.eval(`!document.body.innerText.includes("Couldn't load this")`));
await b.goto(`/sites/${ids.demoSite}`);
t.check("overview shows KPI data", await b.waitFor(`document.body.innerText.includes("Bounce rate") && !document.body.innerText.includes("Couldn't load")`, 40000));
const groups = await b.eval(`[...document.querySelectorAll("select optgroup")].map((g) => g.label)`);
t.check("admin's switcher groups both clients", groups.length === 2, JSON.stringify(groups));

// 4. Switch website, staying in the same section
await b.goto(`/sites/${ids.demoSite}/pages`);
await b.waitFor(`!!document.querySelector("select")`);
await b.fill("select", ids.otherSite);
t.check("switcher opens the same section of the other website", await b.waitForPath(`/sites/${ids.otherSite}/pages`), await b.path());

// 5. Logout really ends the session
await b.goto(`/sites/${ids.demoSite}`);
await b.waitForText("Log out");
await b.clickText("Log out");
t.check("log out goes to /login", await b.waitForPath("/login"));
t.check("  ...and the API says 401 afterwards", (await b.apiStatus("/api/auth/me")) === 401);

// 6. A client owner sees only their own website
await b.login(ownerEmail, ownerPass);
t.check("client lands on their only website", await b.waitForPath(`/sites/${ids.demoSite}`), await b.path());
t.check("  ...with no switcher, just the name", await b.waitFor(`!document.querySelector("select") && document.body.innerText.includes("demo-shop.pk")`));
await b.goto(`/sites/${ids.otherSite}`);
t.check("another client's website says 'Website not found'", await b.waitForText("Website not found"));
t.check("  ...and the API answers 404", (await b.apiStatus(`/api/websites/${ids.otherSite}/overview`)) === 404);
await b.goto("/admin");
t.check("a client can't open the admin area", await b.waitForText("Admins only"));
t.check("  ...and the admin API says 403", (await b.apiStatus("/api/admin/clients")) === 403);

// 7. Forgot password: link from the backend log, new password, link works once
await b.clickText("Go to my dashboard");
await b.waitForText("Log out");
await b.clickText("Log out");
await b.waitForPath("/login");
await b.goto("/forgot-password");
await b.fill("input[type=email]", resetEmail);
await b.submit();
t.check("forgot-password shows the neutral confirmation", await b.waitForText("If an account exists"));
await sleep(1500);
const links = [...readFileSync(process.env.E2E_BACKEND_LOG, "utf8").matchAll(new RegExp(BASE.replace(/[.*+?^${}()|[\]\\\/]/g, "\\$&") + "/reset-password\\?token=\\S+", "g"))].map((m) => m[0]);
t.check("the reset email (printed in the backend log) has a link", links.length > 0);
async function setPassword(link, password) {
  await b.goto(link);
  await b.waitFor(`document.querySelectorAll("input[type=password]").length === 2`);
  await b.eval(`(() => { const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    for (const el of document.querySelectorAll("input[type=password]")) { set.call(el, ${JSON.stringify(password)}); el.dispatchEvent(new Event("input", { bubbles: true })); } })()`);
  await b.submit();
}
await setPassword(links.at(-1), "Brand-New-Pass-2026");
t.check("reset sends you to login with a success note", await b.waitFor(`location.search.includes("reset=1") && document.body.innerText.includes("Please log in")`));
await b.login(resetEmail, "Brand-New-Pass-2026");
t.check("login with the NEW password works", await b.waitForPath(`/sites/${ids.demoSite}`));
await setPassword(links.at(-1), "Another-Pass-2026");
t.check("the reset link works only once", await b.waitForText("invalid or has expired"));

// 8. Phone width
await b.goto(`/sites/${ids.demoSite}`);
await b.waitForText("Bounce rate", 40000);
t.check("phone-sized window: no sideways scrolling", await b.eval(`document.documentElement.scrollWidth <= document.documentElement.clientWidth`));

t.finish(b);
