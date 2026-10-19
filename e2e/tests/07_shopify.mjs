// Phase 9: the admin's Shopify connection card and the access rules around the store's data.
// The browser tests can't talk to the real Shopify, so a pretend store and its orders are seeded straight into the
// throwaway database (e2e/seed.py). (The client-facing Sales page was removed from the dashboard on request.)
import { creds, ids, launch, out, suite } from "../lib.mjs";

const t = suite("Shopify connection");
const owner = await launch({ out, name: "owner", height: 1200 });
const viewer = await launch({ out, name: "viewer" });
const otherOwner = await launch({ out, name: "other" });
const admin = await launch({ out, name: "admin", height: 1200 });

for (const [b, who, home] of [[owner, creds.owner, ids.demoSite], [viewer, creds.viewer, ids.demoSite], [otherOwner, creds.other, ids.otherSite]]) {
  await b.login(...who);
  await b.waitForPath(`/sites/${home}`);
}
await admin.login(...creds.admin);
await admin.waitForPath("/admin");

// 1. There is no Sales page for clients any more
t.check("the client menu has no Sales entry", await owner.waitFor(`document.querySelectorAll('nav[aria-label="Main"] a').length > 5 && ![...document.querySelectorAll('nav[aria-label="Main"] a')].some((a) => a.innerText.trim().startsWith("Sales"))`, 30000));
await owner.goto(`/sites/${ids.demoSite}/sales`);
t.check("/sales is just a 'page not found'", await owner.waitFor(`document.body.innerText.includes("404") || document.body.innerText.toLowerCase().includes("could not be found") || document.body.innerText.toLowerCase().includes("not found")`, 30000));

// 2. Access rules of the store's data (the API is still there)
t.check("a viewer can read the store data", (await viewer.apiStatus(`/api/websites/${ids.demoSite}/sales`)) === 200);
t.check("another client can't (404, like a website that doesn't exist)", (await otherOwner.apiStatus(`/api/websites/${ids.demoSite}/sales`)) === 404 && (await otherOwner.apiStatus(`/api/websites/${ids.demoSite}/sales/orders`)) === 404);
t.check("the admin-only Shopify API is closed to clients", (await owner.apiStatus(`/api/admin/websites/${ids.demoSite}/shopify`)) === 403);

// 3. The admin's Shopify card
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

t.finish(owner, viewer, otherOwner, admin);
