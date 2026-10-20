// Phase 7: plans, invoices, payments, plan features, overdue suspension, the client's Billing page.
// Plans have a recordings (videos) limit and a first-month price; the Billing page shows total / used / left; the price guide is PostHog's price + a commission.
import { creds, ids, launch, out, suite } from "../lib.mjs";

const t = suite("Plans, invoices and payments");
const admin = await launch({ out, name: "admin", height: 1100 });
const owner = await launch({ out, name: "owner" }); // the Demo Shop account owner
const otherOwner = await launch({ out, name: "other" }); // Other Co's owner (has an overdue invoice)
const phone = await launch({ out, name: "phone", width: 390, height: 800, mobile: true }); // the Demo Shop owner on a phone

await admin.login(...creds.admin);
await admin.waitForPath(`/sites/${ids.demoSite}`);
await owner.login(...creds.owner);
await owner.waitForPath(`/sites/${ids.demoSite}`);
await phone.login(...creds.owner);
await phone.waitForPath(`/sites/${ids.demoSite}`);

// 1. Plans
await admin.goto("/admin/plans");
t.check("the three example plans are there", await admin.waitFor(`["Starter", "Growth", "Pro"].every((n) => document.body.innerText.includes(n))`));
t.check("  ...Starter is what PostHog gives free: $30 (Rs 8,400) a month, 1,000,000 events, 5,000 recordings", await admin.eval(`(() => { const t = document.body.innerText; return t.includes("$30.00") && t.includes("Rs 8,400") && t.includes("1,000,000") && t.includes("Recordings (videos) per month") && t.includes("5,000"); })()`));
t.check("  ...with a first-month price of $20 (Rs 5,600)", await admin.eval(`document.body.innerText.includes("First month: Rs 5,600 or $20.00")`));
t.check("  ...and a price guide on each (PostHog's price + commission): Growth should cost $95", await admin.eval(`document.querySelectorAll("[data-price-guide]").length >= 3 && document.body.innerText.includes("Price guide: $95.00 or Rs 26,600 a month")`));

await admin.clickText("+ New plan");
await admin.fillLabel("Name", "E2E Special");
t.check("the plan form says what is needed before it can suggest a price", await admin.waitFor(`document.body.innerText.includes("Fill in both the events and the recordings")`));
await admin.fillLabel("Events per month", "2000000");
await admin.fillLabel("Recordings (videos) per month", "5000");
t.check("  ...then works it out: base price + PostHog's price + commission", await admin.waitFor(`document.body.innerText.includes("1,000,000 events and 5,000 recordings free") && document.body.innerText.includes("charge you $50.00") && document.body.innerText.includes("30% commission ($15.00) = suggested $95.00 or Rs 26,600 a month")`, 20000));
await admin.clickText("Use this price");
const filled = await admin.eval(`(() => { const v = (label) => [...document.querySelectorAll("label")].find((l) => l.innerText.trim().startsWith(label)).querySelector("input").value; return [v("Price per month (USD)"), v("Price per month (PKR)")]; })()`);
t.check("  ...and 'Use this price' fills both prices in", filled[0] === "95" && filled[1] === "26600", JSON.stringify(filled));
await admin.clickText("Use PostHog's free amounts");
const free = await admin.eval(`(() => { const v = (label) => [...document.querySelectorAll("label")].find((l) => l.innerText.trim().startsWith(label)).querySelector("input").value; return [v("Events per month"), v("Recordings (videos) per month")]; })()`);
t.check("  ...'Use PostHog's free amounts' fills 1,000,000 events and 5,000 recordings", free[0] === "1000000" && free[1] === "5000", JSON.stringify(free));
t.check("  ...so the suggested price falls back to the base price", await admin.waitFor(`document.body.innerText.includes("suggested $30.00 or Rs 8,400 a month")`, 20000));

// the plan the rest of this test uses: tiny limits, only Recordings switched on, and a cheaper first month
await admin.fillLabel("Price per month (PKR)", "1234");
await admin.fillLabel("Price per month (USD)", "5");
await admin.fillLabel("First month price (PKR)", "600");
await admin.fillLabel("First month price (USD)", "3");
await admin.fillLabel("Events per month", "2500");
await admin.fillLabel("Recordings (videos) per month", "100");
await admin.eval(`[...document.querySelectorAll("fieldset label")].find((l) => l.innerText.trim() === "Recordings").querySelector("input").click()`);
await admin.clickText("Create plan");
t.check("a new plan can be created", await admin.waitFor(`document.body.innerText.includes("E2E Special") && document.body.innerText.includes("Rs 1,234") && document.body.innerText.includes("First month: Rs 600")`));

// a first-month price above the normal price is refused with a clear message
await admin.clickText("+ New plan");
await admin.fillLabel("Name", "E2E Typo");
await admin.fillLabel("Price per month (USD)", "5");
await admin.fillLabel("First month price (USD)", "50");
await admin.clickText("Create plan");
t.check("a first-month price higher than the normal price is refused", await admin.waitForText("can't be higher than the normal monthly price", 20000));
await admin.clickText("Cancel");

// 2. Put Demo Shop on the new plan
await admin.goto(`/admin/clients/${ids.demoClient}`);
await admin.waitForText("Plan & billing");
await admin.selectLabel("Put on plan", "E2E Special");
await admin.clickText("Start plan");
t.check("a client can be put on a plan", await admin.waitFor(`document.body.innerText.includes("On E2E Special at $5.00 per month")`, 20000));
t.check("  ...and their first invoice is the first-month price", await admin.eval(`document.body.innerText.includes("Next invoice: $3.00") && document.body.innerText.includes("(first month price)")`));
t.check("  ...showing their events and recordings against the plan's limits (total, used, left)", await admin.waitFor(`(() => { const t = document.body.innerText; return t.includes("Events this month") && t.includes("Recordings (videos) this month") && t.includes("2,500") && t.includes("Total") && t.includes("Used"); })()`, 20000));
t.check("  ...and the extra-usage box, which says why nothing can be charged while the traffic is small or inside PostHog's free million", await admin.waitFor(`(() => { const box = document.querySelector("[data-extra-usage]"); return !!box && /Nothing above the E2E Special plan|still inside PostHog's free allowance/.test(box.innerText); })()`, 20000));

// 3. The owner now sees a plan-restricted dashboard
await owner.goto(`/sites/${ids.demoSite}`);
t.check("the owner's menu shows locks on what their plan doesn't include", await owner.waitFor(`document.querySelectorAll('nav[aria-label="Main"] [title="Not in your plan"]').length >= 4`, 20000));
await owner.goto(`/sites/${ids.demoSite}/sessions`);
t.check("opening a locked page explains it, without a scary error", await owner.waitFor(`document.body.innerText.includes("Not part of your plan") && document.body.innerText.includes("doesn't include Sessions")`, 20000));
t.check("  ...and the basic dashboard still works", (await owner.apiStatus(`/api/websites/${ids.demoSite}/overview`)) === 200 && (await owner.apiStatus(`/api/websites/${ids.demoSite}/sessions`)) === 403);

// 4. A one-off invoice: partial payment, then the rest
await admin.goto(`/admin/clients/${ids.demoClient}`);
await admin.waitForText("+ One-off invoice");
await admin.clickText("+ One-off invoice");
await admin.fillLabel("What is it for?", "E2E set-up fee");
await admin.fillLabel("Amount (USD)", "10");
await admin.clickText("Create invoice");
t.check("a one-off invoice appears in the client's list", await admin.waitFor(`/INV-\\d{4}-\\d{4}/.test(document.body.innerText) && document.body.innerText.includes("$10.00")`, 20000));
await admin.clickText("Mark as paid");
await admin.waitForText("Record a payment for");
await admin.fillLabel("Amount (USD)", "4");
await admin.fillLabel("Reference", "E2E-TX-1");
await admin.clickText("Record payment");
t.check("a part-payment leaves the invoice open with the rest still owed", await admin.waitFor(`document.body.innerText.includes("$6.00 left")`, 20000));
await admin.clickText("Mark as paid");
await admin.waitForText("Record a payment for");
await admin.clickText("Record payment");
t.check("paying the rest closes the invoice", await admin.waitFor(`[...document.querySelectorAll("span")].some((s) => s.innerText.trim().endsWith("Paid"))`, 20000));

// 5. The owner's Billing page
await owner.goto(`/sites/${ids.demoSite}/billing`);
t.check("the owner's billing page shows plan, usage and invoices", await owner.waitFor(`document.body.innerText.includes("Your plan") && document.body.innerText.includes("E2E Special") && document.body.innerText.includes("Invoices") && /INV-\\d{4}-\\d{4}/.test(document.body.innerText)`, 30000));
t.check("  ...what the plan includes (only Recordings, so the rest show crosses)", await owner.eval(`document.body.innerText.includes("✕") && document.body.innerText.includes("Recordings")`));
t.check("  ...the price, and what the next invoice costs (the first-month price, then the normal one)", await owner.eval(`(() => { const t = document.body.innerText; return t.includes("$5.00 per month") && /Next invoice: \\$3\\.00 on .*\\(first month price, then \\$5\\.00 a month\\)/.test(t); })()`));

// total / used / left, for events and for recordings (videos): what the page shows must match what the API says
const usage = (await owner.apiJson(`/api/clients/${ids.demoClient}/billing`)).usage;
const fmt = (n) => n.toLocaleString("en-US");
const meter = (label) => owner.eval(`(() => { const g = document.querySelector('[data-quota="${label}"]'); if (!g) return null; return [...g.querySelectorAll("dl > div")].map((d) => d.innerText.replace(/\\s+/g, " ").trim()); })()`);
const eventsMeter = await meter("Visitor events");
const videosMeter = await meter("Recordings (videos)");
const expectedFor = (limit, used, remaining, over) => [`Total ${fmt(limit)}`, `Used ${fmt(used)}`, over > 0 ? `Over by ${fmt(over)}` : `Left ${fmt(remaining)}`];
t.check("the usage card shows Visitor events: total, used and left (or how far over)", JSON.stringify(eventsMeter) === JSON.stringify(expectedFor(usage.event_limit, usage.events, usage.event_remaining, usage.event_over)), `${JSON.stringify(eventsMeter)} vs ${JSON.stringify(usage)}`);
t.check("  ...and Recordings (videos): total 100, used and left", JSON.stringify(videosMeter) === JSON.stringify(expectedFor(usage.recording_limit, usage.recordings, usage.recording_remaining, usage.recording_over)) && usage.recording_limit === 100, `${JSON.stringify(videosMeter)} vs ${JSON.stringify(usage)}`);
t.check("  ...with a progress bar for each, and when the numbers were last counted", await owner.eval(`document.querySelectorAll('[data-quota] [role="progressbar"]').length === 2 && (${Boolean(usage.updated_at)} ? /counted .+/.test(document.body.innerText) : true)`));
t.check("  ...going over a limit is stated in words, not only colour", await owner.eval(`(() => { const t = document.body.innerText; return ${usage.event_over > 0} ? t.includes("Over the limit") : true; })()`));
await owner.shot("billing-usage");
const pdf = await owner.eval(`(() => { const a = [...document.querySelectorAll("a")].find((x) => x.innerText.includes("PDF")); return fetch(a.href, { credentials: "include" }).then(async (r) => ({ status: r.status, type: r.headers.get("content-type"), start: new TextDecoder().decode((await r.arrayBuffer()).slice(0, 5)) })); })()`);
t.check("  ...and the invoice PDF downloads", pdf.status === 200 && pdf.type === "application/pdf" && pdf.start === "%PDF-", JSON.stringify(pdf));
t.check("  ...nothing mentions the analytics provider, a commission or a price guide", await owner.eval(`!/posthog|commission|price guide/i.test(document.body.innerText)`));
await owner.shot("billing");
await phone.goto(`/sites/${ids.demoSite}/billing`);
await phone.waitFor(`document.querySelectorAll("[data-quota]").length === 2`, 30000);
t.check("the billing page, with its total / used / left numbers, fits a phone", await phone.eval(`document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1`));
t.check("  ...and no number is cut off inside its box", await phone.eval(`[...document.querySelectorAll("[data-quota] dd")].every((d) => d.scrollWidth <= d.clientWidth + 1)`));
await phone.shot("billing-phone");

// the plans the client could choose from (what each includes), with their own plan marked
t.check("the billing page shows the plans on offer, with the owner's own plan marked", await owner.eval(`(() => { const cards = [...document.querySelectorAll("[data-plan]")].map((c) => c.getAttribute("data-plan")); const mine = document.querySelector('[data-plan="E2E Special"]'); return ["Starter", "Growth", "Pro", "E2E Special"].every((n) => cards.includes(n)) && !!mine && mine.innerText.includes("Your plan") && document.querySelectorAll("[data-plan]")[0] !== null; })()`));
t.check("  ...each with its price, first-month price, events, recordings (videos) and what is included", await owner.eval(`(() => { const t = document.querySelector('[data-plan="Starter"]').innerText.replace(/\\s+/g, " "); return t.includes("$30.00 per month") && t.includes("First month: $20.00") && t.includes("1,000,000 events a month") && t.includes("5,000 recordings (videos) a month") && t.includes("1 website") && t.includes("2 people with access") && t.includes("✓ Recordings") && t.includes("✓ Team members") && t.includes("✕ Weekly reports"); })()`));
t.check("  ...never the note that marks an example plan", await owner.eval(`!document.body.innerText.includes("EXAMPLE plan")`));
t.check("  ...and every amount on the client's billing page is in dollars, not rupees", await owner.eval(`document.body.innerText.includes("$") && !document.body.innerText.includes("Rs ")`));
await owner.shot("billing-plans");

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
await owner.goto(`/sites/${ids.demoSite}/billing`);
t.check("every plan but the owner's own has an 'Ask for this plan' button that opens a WhatsApp chat with the message written", await owner.waitFor(`(() => { const links = [...document.querySelectorAll("[data-plan] a")].filter((a) => a.innerText.trim() === "Ask for this plan"); const starter = document.querySelector('[data-plan="Starter"] a'); const own = document.querySelector('[data-plan="E2E Special"] a'); return links.length === 3 && !own && !!starter && starter.href.startsWith("https://wa.me/923001234567?text=") && decodeURIComponent(starter.href).includes("to the Starter plan"); })()`, 30000));

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

t.finish(admin, owner, otherOwner, viewer, phone);
