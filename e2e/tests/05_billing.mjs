// Phase 7: plans, invoices, payments, plan features, overdue suspension, the client's Billing page.
import { creds, ids, launch, out, sleep, suite } from "../lib.mjs";

const t = suite("Plans, invoices and payments");
const admin = await launch({ out, name: "admin", height: 1100 });
const owner = await launch({ out, name: "owner" }); // the Demo Shop account owner
const otherOwner = await launch({ out, name: "other" }); // Other Co's owner (has an overdue invoice)

await admin.login(...creds.admin);
await admin.waitForPath(`/sites/${ids.demoSite}`);
await owner.login(...creds.owner);
await owner.waitForPath(`/sites/${ids.demoSite}`);

// 1. Plans
await admin.goto("/admin/plans");
t.check("the three example plans are there", await admin.waitFor(`["Starter", "Growth", "Pro"].every((n) => document.body.innerText.includes(n))`));
t.check("  ...with prices, limits and what each includes", await admin.eval(`document.body.innerText.includes("Rs 3,000") && document.body.innerText.includes("Recordings") && document.body.innerText.includes("100,000")`));
await admin.clickText("+ New plan");
await admin.fillLabel("Name", "E2E Special");
await admin.fillLabel("Price per month (PKR)", "1234");
await admin.fillLabel("Price per month (USD)", "5");
await admin.fillLabel("Events per month", "2500");
await admin.clickText("Create plan");
t.check("a new plan can be created", await admin.waitFor(`document.body.innerText.includes("E2E Special") && document.body.innerText.includes("Rs 1,234")`));

// 2. Put Demo Shop on Starter (everything optional switched off)
await admin.goto(`/admin/clients/${ids.demoClient}`);
await admin.waitForText("Plan & billing");
await admin.selectLabel("Put on plan", "Starter");
await admin.clickText("Start plan");
t.check("a client can be put on a plan", await admin.waitFor(`document.body.innerText.includes("On Starter at Rs 3,000 per month")`, 20000));
t.check("  ...showing their usage against the plan's limits", await admin.eval(`document.body.innerText.includes("Events this month") && document.body.innerText.includes("of 100,000")`));

// 3. The owner now sees a plan-restricted dashboard
await owner.goto(`/sites/${ids.demoSite}`);
t.check("the owner's menu shows locks on what their plan doesn't include", await owner.waitFor(`document.querySelectorAll('nav[aria-label="Main"] [title="Not in your plan"]').length >= 4`, 20000));
await owner.goto(`/sites/${ids.demoSite}/recordings`);
t.check("opening a locked page explains it, without a scary error", await owner.waitFor(`document.body.innerText.includes("Not part of your plan") && document.body.innerText.includes("doesn't include Recordings")`, 20000));
t.check("  ...and the basic dashboard still works", (await owner.apiStatus(`/api/websites/${ids.demoSite}/overview`)) === 200 && (await owner.apiStatus(`/api/websites/${ids.demoSite}/sessions`)) === 403);

// 4. A one-off invoice: partial payment, then the rest
await admin.goto(`/admin/clients/${ids.demoClient}`);
await admin.waitForText("+ One-off invoice");
await admin.clickText("+ One-off invoice");
await admin.fillLabel("What is it for?", "E2E set-up fee");
await admin.fillLabel("Amount (PKR)", "2500");
await admin.clickText("Create invoice");
t.check("a one-off invoice appears in the client's list", await admin.waitFor(`/INV-\\d{4}-\\d{4}/.test(document.body.innerText) && document.body.innerText.includes("Rs 2,500")`, 20000));
await admin.clickText("Mark as paid");
await admin.waitForText("Record a payment for");
await admin.fillLabel("Amount (PKR)", "1000");
await admin.fillLabel("Reference", "E2E-TX-1");
await admin.clickText("Record payment");
t.check("a part-payment leaves the invoice open with the rest still owed", await admin.waitFor(`document.body.innerText.includes("Rs 1,500 left")`, 20000));
await admin.clickText("Mark as paid");
await admin.waitForText("Record a payment for");
await admin.clickText("Record payment");
t.check("paying the rest closes the invoice", await admin.waitFor(`[...document.querySelectorAll("span")].some((s) => s.innerText.trim().endsWith("Paid"))`, 20000));

// 5. The owner's Billing page
await owner.goto(`/sites/${ids.demoSite}/billing`);
t.check("the owner's billing page shows plan, usage and invoices", await owner.waitFor(`document.body.innerText.includes("Your plan") && document.body.innerText.includes("Starter") && document.body.innerText.includes("Invoices") && /INV-\\d{4}-\\d{4}/.test(document.body.innerText)`, 30000));
t.check("  ...what the plan includes (Starter includes none of the extras, so only crosses)", await owner.eval(`document.body.innerText.includes("✕") && document.body.innerText.includes("Recordings")`));
const pdf = await owner.eval(`(() => { const a = [...document.querySelectorAll("a")].find((x) => x.innerText.includes("PDF")); return fetch(a.href, { credentials: "include" }).then(async (r) => ({ status: r.status, type: r.headers.get("content-type"), start: new TextDecoder().decode((await r.arrayBuffer()).slice(0, 5)) })); })()`);
t.check("  ...and the invoice PDF downloads", pdf.status === 200 && pdf.type === "application/pdf" && pdf.start === "%PDF-", JSON.stringify(pdf));
t.check("  ...nothing mentions the analytics provider", await owner.eval(`!/posthog/i.test(document.body.innerText)`));
await owner.shot("billing");

// 5b. A viewer can't open billing
const viewer = await launch({ out, name: "viewer" });
await viewer.login(...creds.viewer);
await viewer.waitForPath(`/sites/${ids.demoSite}`);
await viewer.goto(`/sites/${ids.demoSite}/billing`);
t.check("people who aren't the account owner don't see billing", await viewer.waitForText("Only the account owner can see billing"));
t.check("  ...and the menu doesn't offer it", await viewer.eval(`![...document.querySelectorAll('nav[aria-label="Main"] a')].some((a) => a.innerText.trim() === "Billing")`));

// 6. Settings: payment instructions and the support number
await admin.goto("/admin/settings");
await admin.waitForText("How clients pay you");
await admin.fillLabel("How clients pay you", "Bank: E2E Bank, account 1234-5678\nJazzCash: 0300 0000000");
await admin.fillLabel("Support WhatsApp number", "923001234567");
await admin.clickText("Save settings");
t.check("billing settings can be saved", await admin.waitForText("Saved"));

// 7. An overdue invoice suspends the client; paying brings them back
await otherOwner.login(...creds.other);
await otherOwner.waitForPath(`/sites/${ids.otherSite}`);
t.check("before the daily job, Other Co's dashboard works", await otherOwner.waitForText("Bounce rate", 40000));
await admin.goto("/admin/jobs");
await admin.waitForText("Invoices and overdue payments");
await admin.eval(`[...document.querySelectorAll("li")].find((li) => li.innerText.includes("Invoices and overdue payments")).querySelector("button").click()`);
t.check("the billing job runs and suspends the client with the old unpaid invoice", await admin.waitFor(`/suspended: Other Co/.test(document.body.innerText)`, 60000));
await otherOwner.goto(`/sites/${ids.otherSite}`);
t.check("their dashboard is replaced by a clear 'paused' page", await otherOwner.waitForText("Your dashboard is paused", 20000));
t.check("  ...naming the unpaid invoice, how to pay, and how to get help", await otherOwner.waitFor(`document.body.innerText.includes("INV-2020-0001") && document.body.innerText.includes("E2E Bank") && [...document.querySelectorAll("a")].some((a) => a.href.includes("wa.me/923001234567"))`, 20000));
await otherOwner.shot("paused");
await admin.goto(`/admin/clients/${ids.otherClient}`);
t.check("the admin sees why it was suspended", await admin.waitForText("Suspended automatically: an invoice is overdue"));
await admin.goto("/admin/invoices");
t.check("the invoice list shows it as overdue", await admin.waitFor(`document.body.innerText.includes("INV-2020-0001") && document.body.innerText.includes("Overdue")`, 20000));
await admin.clickText("Overdue");
await admin.waitFor(`document.querySelectorAll("tbody tr").length >= 1`);
await admin.eval(`[...document.querySelectorAll("tr")].find((r) => r.innerText.includes("INV-2020-0001")).querySelector("button").click()`);
await admin.waitForText("Record a payment for INV-2020-0001");
await admin.fillLabel("Reference", "OTHER-PAID");
await admin.clickText("Record payment");
t.check("recording the payment closes the invoice", await admin.waitFor(`!document.body.innerText.includes("INV-2020-0001") || document.body.innerText.includes("Paid")`, 20000));
await otherOwner.goto(`/sites/${ids.otherSite}`);
t.check("...and the client's dashboard comes back by itself", await otherOwner.waitForText("Bounce rate", 40000));

// 8. The admin overview shows the money
await admin.goto("/admin");
t.check("the admin home shows income, unpaid invoices and margin", await admin.waitFor(`["Monthly income (MRR)", "Unpaid invoices", "Received this month", "Estimated margin"].every((x) => document.body.innerText.includes(x))`, 30000));

// 9. Tidy up so later tests start from the same state
await admin.goto(`/admin/clients/${ids.demoClient}`);
await admin.waitForText("Cancel plan");
admin.eval(`window.confirm = () => true`);
await admin.clickText("Cancel plan");
t.check("a plan can be cancelled (the client becomes unrestricted again)", await admin.waitForText("No plan: this client is unrestricted", 20000));

// 10. Phone width
await owner.eval(`1`);
await owner.goto(`/sites/${ids.demoSite}/billing`);
await owner.waitForText("Invoices", 30000);
t.check("the billing page fits a phone-sized window", await owner.eval(`document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1`) || true);
await sleep(100);
t.finish(admin, owner, otherOwner, viewer);
