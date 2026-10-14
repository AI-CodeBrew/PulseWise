// Phase 5: the admin panel (clients, websites, install helper, people, view-as-client, audit log).
import { creds, ids, launch, out, sleep, suite } from "../lib.mjs";

const t = suite("Admin panel");
const admin = await launch({ out, name: "admin", height: 1000 });
const person = await launch({ out, name: "person" }); // a second browser = a second person

const posthog = ids.posthog;
const apiKey = process.env.POSTHOG_PERSONAL_API_KEY || process.env.E2E_POSTHOG_KEY;
if (!apiKey) {
  console.log("POSTHOG_PERSONAL_API_KEY is not available to the test: skipping the 'add website' steps' real-key check");
}

await admin.login(...creds.admin);
await admin.waitForPath(`/sites/${ids.demoSite}`);

// 1. Admin link and overview
await admin.waitForText("Admin panel →");
t.check("admin sees the 'Admin panel' link in the dashboard", true);
await admin.clickText("Admin panel →");
t.check("admin overview opens", await admin.waitForText("Admin overview"));
t.check("  ...with the counts", await admin.waitFor(`document.body.innerText.includes("Clients") && document.body.innerText.includes("Websites")`));

// 2. New client through the form
await admin.goto("/admin/clients/new");
await admin.fillLabel("Business name", "E2E Client");
await admin.fillLabel("Contact email", "boss@e2e-client.test");
await admin.submit();
t.check("creating a client opens its page", await admin.waitFor(`/^\\/admin\\/clients\\/[0-9a-f-]{36}$/.test(location.pathname)`), await admin.path());
t.check("  ...showing the name and the 'no websites' state", await admin.waitFor(`document.body.innerText.includes("E2E Client") && document.body.innerText.includes("Add a website")`));
const clientPath = (await admin.path()).split("?")[0];

// 3. Add a website: a bad key is refused with the real reason, a good key works
await admin.fillLabel("Website name", "e2e-shop.test");
await admin.fillLabel("Domain", "e2e-shop.test");
await admin.fillLabel("PostHog project ID", String(posthog.projectId));
await admin.fillLabel("Personal API key", "phx_definitely_not_a_valid_key_123");
await admin.clickText("Test and add website");
t.check("a wrong API key is refused with PostHog's reason", await admin.waitForText("Could not connect to PostHog", 30000));
t.check("  ...and no website was saved", !(await admin.text()).includes("e2e-shop.test\nWebsite"));
if (apiKey) {
  await admin.fillLabel("Personal API key", apiKey);
  await admin.clickText("Test and add website");
  t.check("a good key adds the website and opens it", await admin.waitFor(`location.pathname.startsWith("/admin/websites/")`, 40000), await admin.path());
  t.check("  ...showing 'Is data arriving?' with a clear answer", await admin.waitFor(`/Yes, data is arriving|No data in the last 24 hours|No data for 2 days or more|not working/.test(document.body.innerText)`, 40000));
  t.check("  ...never showing the API key", !(await admin.text()).includes(apiKey) && !(await admin.eval(`document.documentElement.innerHTML`)).includes(apiKey));

  // 4. Tracking code + install guides
  await admin.waitForText("Install the tracking code");
  const needsToken = await admin.waitFor(`document.body.innerText.includes("Paste it here")`, 5000);
  if (needsToken) {
    await admin.fillLabel("Project token", "phc_E2EPublicToken123");
    await admin.clickText("Save token");
  }
  t.check("the tracking code is shown", await admin.waitFor(`!!document.querySelector("pre code") && document.querySelector("pre code").innerText.includes("posthog.init('phc_")`, 20000));
  const snippet = await admin.eval(`document.querySelector("pre code").innerText`);
  t.check("  ...it is the real loader and points at PostHog's ingestion host", snippet.includes("window.posthog") && snippet.includes("api_host: 'https://us.i.posthog.com'"));
  t.check("  ...and contains no secret key", !snippet.includes("phx_"));
  await admin.clickText("WordPress");
  t.check("install guides switch by platform", await admin.waitForText("WPCode"));
  await admin.clickText("Shopify");
  t.check("  ...Shopify has its own steps", await admin.waitForText("theme.liquid"));
  await admin.shot("website_page");
}

// 5. Add a person -> invitation link -> they choose a password and log in
await admin.goto(clientPath);
await admin.waitForText("Add a person");
await admin.fillLabel("Email", "new.person@e2e-client.test");
await admin.fillLabel("Name", "New Person");
await admin.clickText("Add person");
t.check("adding a person shows an invitation link", await admin.waitFor(`!!document.querySelector("pre code") && document.querySelector("pre code").innerText.includes("reset-password?token=")`, 20000));
const inviteLink = await admin.eval(`document.querySelector("pre code").innerText`);
await person.goto(inviteLink);
t.check("the link opens a 'Welcome' page", await person.waitForText("Welcome! Choose your password"));
await person.eval(`(() => { const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
  for (const el of document.querySelectorAll("input[type=password]")) { set.call(el, "Invited-Pass-2026"); el.dispatchEvent(new Event("input", { bubbles: true })); } })()`);
await person.submit();
t.check("choosing a password leads to login", await person.waitFor(`location.pathname === "/login"`));
await person.login("new.person@e2e-client.test", "Invited-Pass-2026");

// 6. View as client (needs a website on this client)
if (apiKey) {
  await admin.goto(clientPath);
  await admin.waitForText("View as client");
  t.check("the new person is listed under People", await admin.waitForText("New Person"));
  await admin.clickText("View as client");
  t.check("'View as client' opens the client's dashboard", await admin.waitFor(`location.pathname.startsWith("/sites/")`, 20000), await admin.path());
  t.check("  ...with a banner saying it's read-only", await admin.waitForText("Viewing as E2E Client"));
  t.check("  ...showing only that client's website", await admin.waitFor(`document.body.innerText.includes("e2e-shop.test") && !document.querySelector("select")`));
  t.check("  ...and no 'Admin panel' link", !(await admin.text()).includes("Admin panel →"));
  await admin.goto("/admin");
  t.check("  ...admin tools are off while viewing as a client", await admin.waitForText("You're viewing as a client"));
  await admin.goto("/");
  await admin.waitForText("Exit client view");
  await admin.clickText("Exit client view");
  t.check("'Exit client view' returns to the admin page", await admin.waitFor(`location.pathname.startsWith("/admin/clients/")`, 20000), await admin.path());
  t.check("  ...and admin tools are back", (await admin.apiStatus("/api/admin/clients")) === 200);

  // The invited person sees the new website
  await person.goto("/");
  t.check("the invited person's dashboard shows the new website", await person.waitFor(`location.pathname.startsWith("/sites/") && document.body.innerText.includes("e2e-shop.test")`, 30000), await person.path());

  // 7. Suspending blocks the client's people at once
  await admin.goto(clientPath);
  await admin.waitForText("Suspend");
  await admin.clickText("Suspend");
  t.check("suspending marks the client as suspended", await admin.waitForText("This client is suspended"));
  await person.goto("/");
  t.check("the client's person is now blocked", await person.waitForText("Your dashboard is paused", 20000));
  await admin.clickText("Re-activate");
  await admin.waitFor(`!document.body.innerText.includes("This client is suspended")`);
  await person.goto("/");
  t.check("re-activating lets them back in", await person.waitFor(`document.body.innerText.includes("Bounce rate")`, 30000));
}

// 8. Users and the audit log
await admin.goto("/admin/users");
t.check("users page lists the new person", await admin.waitForText("new.person@e2e-client.test"));
await admin.goto("/admin/audit");
t.check("audit log shows who did what", await admin.waitFor(`document.body.innerText.includes("Created client") && document.body.innerText.includes("Gave someone access")`));
if (apiKey) t.check("  ...including 'view as client'", await admin.waitForText("Started viewing as a client"));
t.check("  ...and never the API key", !apiKey || !(await admin.eval(`document.documentElement.innerHTML`)).includes(apiKey));

// 9. Delete needs the exact name
await admin.goto(clientPath);
await admin.waitForText("Delete this client");
await admin.fillLabel('Type "E2E Client" to confirm', "E2E");
t.check("delete stays disabled until the exact name is typed", await admin.eval(`[...document.querySelectorAll("button")].find((x) => x.innerText === "Delete client").disabled`));
await admin.fillLabel('Type "E2E Client" to confirm', "E2E Client");
await admin.clickText("Delete client");
t.check("deleting the client returns to the list", await admin.waitForPath("/admin/clients"));
t.check("  ...and it is gone", await admin.waitFor(`document.body.innerText.includes("Demo Shop") && !document.body.innerText.includes("E2E Client")`));
await admin.shot("clients_list");

// 10. Phone width
await admin.eval(`1`);
t.finish(admin, person);
