// Phase 9: the client's Sales page and the admin's Shopify connection card.
// The browser tests can't talk to the real Shopify, so the orders are seeded straight into the throwaway database
// (e2e/seed.py). What the browser checks here is everything AFTER the sync: the numbers, the pages, the access rules.
import { creds, ids, launch, out, suite } from "../lib.mjs";

const t = suite("Shopify sales");
const owner = await launch({ out, name: "owner", height: 1200 });
const viewer = await launch({ out, name: "viewer" });
const otherOwner = await launch({ out, name: "other" });
const admin = await launch({ out, name: "admin", height: 1200 });
const phone = await launch({ out, name: "phone", width: 390, height: 800, mobile: true });

for (const [b, who, home] of [[owner, creds.owner, ids.demoSite], [viewer, creds.viewer, ids.demoSite], [otherOwner, creds.other, ids.otherSite], [phone, creds.owner, ids.demoSite]]) {
  await b.login(...who);
  await b.waitForPath(`/sites/${home}`);
}
await admin.login(...creds.admin);
await admin.waitForPath("/admin");

// 1. The client's Sales page
await owner.goto(`/sites/${ids.demoSite}/sales`);
t.check("the menu has a Sales entry", await owner.waitFor(`[...document.querySelectorAll('nav[aria-label="Main"] a')].some((a) => a.innerText.trim().startsWith("Sales"))`, 30000));
t.check("the page shows sales, orders and the average order", await owner.waitFor(`["Sales", "Orders", "Average order"].every((x) => document.body.innerText.includes(x)) && /PKR\\s?[\\d,]+/.test(document.body.innerText)`, 40000));
t.check("  ...the store and when it was last updated", await owner.eval(`document.body.innerText.includes("E2E Shop") && /updated .+ ago/.test(document.body.innerText)`));
t.check("  ...visitor-based numbers next to the website traffic", await owner.waitFor(`document.body.innerText.includes("Visitors who buy") && document.body.innerText.includes("Sales per website visit")`, 30000));
t.check("  ...best sellers, biggest first", await owner.waitFor(`(() => { const t = document.body.innerText; return t.includes("Best sellers") && t.indexOf("E2E Hoodie") > -1 && t.indexOf("E2E Cap") > t.indexOf("E2E Hoodie"); })()`, 20000));
t.check("  ...the latest orders with their status", await owner.waitFor(`document.body.innerText.includes("#1001") && document.body.innerText.includes("Paid")`, 20000));
t.check("  ...nothing about the analytics provider, nor any Shopify secret", await owner.eval(`!/posthog/i.test(document.body.innerText) && !/shpat/.test(document.documentElement.innerHTML)`));
await owner.clickText("Table");
t.check("the chart has a table view with orders per day", await owner.waitFor(`document.body.innerText.includes("Website visits") && document.querySelectorAll("table tbody tr").length > 20`, 20000));
await owner.clickText("Chart");
await owner.shot("sales");

// 2. The 7-day view changes the numbers
await owner.goto(`/sites/${ids.demoSite}/sales?days=7`);
t.check("the date range applies (7 days)", await owner.waitForText("in the last 7 days", 30000));

// 3. More orders
await owner.goto(`/sites/${ids.demoSite}/sales`);
await owner.waitForText("Latest orders", 30000);
const before = await owner.eval(`document.querySelectorAll("section:last-of-type tbody tr").length`);
t.check("'Load more' shows older orders", (await owner.waitFor(`[...document.querySelectorAll("button")].some((b) => b.innerText.trim() === "Load more")`, 20000)) && before >= 20, `rows before: ${before}`);
await owner.clickText("Load more");
t.check("  ...and they appear", await owner.waitFor(`document.body.innerText.includes("#1030") || document.body.innerText.includes("#1025")`, 20000));

// 4. Access rules
t.check("a viewer can look at sales too", (await viewer.apiStatus(`/api/websites/${ids.demoSite}/sales`)) === 200);
t.check("another client can't (404, like a website that doesn't exist)", (await otherOwner.apiStatus(`/api/websites/${ids.demoSite}/sales`)) === 404 && (await otherOwner.apiStatus(`/api/websites/${ids.demoSite}/sales/orders`)) === 404);
await otherOwner.goto(`/sites/${ids.otherSite}/sales`);
t.check("a client with no store connected is invited to ask for one", await otherOwner.waitForText("Your store isn't connected yet", 30000));
t.check("the admin-only Shopify API is closed to clients", (await owner.apiStatus(`/api/admin/websites/${ids.demoSite}/shopify`)) === 403);

// 5. The admin's Shopify card
await admin.goto(`/admin/websites/${ids.demoSite}`);
t.check("the admin sees the connected store", await admin.waitFor(`document.body.innerText.includes("Shopify store") && document.body.innerText.includes("e2e-shop.myshopify.com") && document.body.innerText.includes("30 orders stored")`, 40000));
t.check("  ...without any secret on the page", await admin.eval(`!document.documentElement.innerHTML.includes("shpat_e2e")`));
await admin.goto(`/admin/websites/${ids.otherSite}`);
t.check("a website without a store offers to connect one", await admin.waitFor(`document.body.innerText.includes("No store connected.")`, 30000));
await admin.clickText("Connect Shopify store");
await admin.fillLabel("Store address", "evil.example.com");
await admin.fillLabel("Admin API access token", "shpat_dummy_token_value");
await admin.clickText("Test and connect");
t.check("something that isn't a Shopify store address is refused", await admin.waitForText("doesn't look like a Shopify store address", 20000));
await admin.eval(`1`);

// 6. Phone
await phone.goto(`/sites/${ids.demoSite}/sales`);
await phone.waitForText("Best sellers", 40000);
t.check("the sales page fits a phone", await phone.eval(`document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1`));

t.finish(owner, viewer, otherOwner, admin, phone);
