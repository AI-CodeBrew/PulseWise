// A tiny browser-test toolkit with no dependencies: drives headless Microsoft Edge (or Chrome)
// through the Chrome DevTools Protocol. Used by the files in e2e/tests/.
//
//   const b = await launch({ out, width: 1300, height: 900 });
//   await b.login("admin@e2e.test", "Admin-E2E-Pass-1");
//   check("something", await b.waitFor(`document.body.innerText.includes("Hello")`));

import { spawn } from "node:child_process";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";

export const BASE = process.env.E2E_FRONTEND_URL || "http://localhost:3000";
export const API = process.env.E2E_API_URL || "http://localhost:8000";

const BROWSERS = [
  process.env.E2E_BROWSER,
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
].filter(Boolean);

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function freePort() {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.listen(0, () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
    server.on("error", reject);
  });
}

/** Start a browser with its own empty profile (its own cookies: like a separate person). */
export async function launch({ out, width = 1300, height = 900, mobile = false, name = "browser" } = {}) {
  const exe = BROWSERS.find((p) => existsSync(p));
  if (!exe) throw new Error("No Edge/Chrome found. Set E2E_BROWSER to its path.");
  mkdirSync(out, { recursive: true });
  const port = await freePort();
  const proc = spawn(exe, ["--headless=new", "--disable-gpu", `--remote-debugging-port=${port}`, `--user-data-dir=${out}\\profile-${name}-${port}`, "about:blank"], { stdio: "ignore" });

  let target;
  for (let i = 0; i < 60 && !target; i++) {
    await sleep(250);
    try { target = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" })).json(); } catch { /* not up yet */ }
  }
  if (!target) throw new Error("Browser did not start");
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener("open", r));

  let id = 0;
  const pending = new Map();
  const problems = [];
  ws.addEventListener("message", (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
    if (m.method === "Runtime.exceptionThrown") problems.push("EXCEPTION " + (m.params.exceptionDetails.exception?.description ?? m.params.exceptionDetails.text).slice(0, 300));
    if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") {
      const text = m.params.args.map((a) => a.value ?? a.description ?? "").join(" ");
      if (!/Failed to load resource/.test(text)) problems.push("CONSOLE " + text.slice(0, 300)); // 4xx answers are expected in some tests
    }
  });
  const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
  await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile });

  const evaluate = async (expression) => {
    const r = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (r.result.exceptionDetails) throw new Error("page script failed: " + JSON.stringify(r.result.exceptionDetails).slice(0, 300));
    return r.result.result.value;
  };

  let lastPassword = "";
  let loggedInAsAdmin = false;
  const b = {
    problems,
    eval: evaluate,
    /** The admin panel asks an admin for the password once more. While this is true, goto("/admin...") answers it with the password this browser logged in with. */
    autoUnlock: true,
    async goto(path) {
      await send("Page.navigate", { url: path.startsWith("http") ? path : BASE + path });
      await sleep(300);
      if (b.autoUnlock && loggedInAsAdmin && path.startsWith("/admin")) await b.unlockAdminIfAsked();
    },
    /** If the page is asking for the admin password, type it and wait for the panel to open. */
    async unlockAdminIfAsked() {
      await b.waitFor(`!!document.querySelector("[data-admin-unlock]") || !!document.querySelector('nav[aria-label="Admin"]')`, 30000);
      if (!(await evaluate(`!!document.querySelector("[data-admin-unlock]")`))) return;
      await b.fill("[data-admin-unlock] input[type=password]", lastPassword);
      await evaluate(`document.querySelector("[data-admin-unlock] button[type=submit]").click()`);
      await b.waitFor(`!!document.querySelector('nav[aria-label="Admin"]')`, 30000);
    },
    path: () => evaluate("location.pathname + location.search"),
    text: () => evaluate("document.body.innerText"),
    async waitFor(expression, ms = 20000) {
      for (const end = Date.now() + ms; Date.now() < end; await sleep(250)) {
        try { if (await evaluate(expression)) return true; } catch { /* page is navigating */ }
      }
      return false;
    },
    waitForText: (t, ms) => b.waitFor(`document.body.innerText.includes(${JSON.stringify(t)})`, ms),
    waitForPath: (p, ms) => b.waitFor(`location.pathname === ${JSON.stringify(p)}`, ms),
    /** Type into an input the way a person does (works with React-controlled inputs). */
    async fill(selector, value) {
      await b.waitFor(`!!document.querySelector(${JSON.stringify(selector)})`, 10000);
      await evaluate(`(() => { const el = document.querySelector(${JSON.stringify(selector)});
        const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : el.tagName === "SELECT" ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(proto, "value").set.call(el, ${JSON.stringify(value)});
        el.dispatchEvent(new Event(el.tagName === "SELECT" ? "change" : "input", { bubbles: true })); })()`);
    },
    /** Fill an input found by its visible label text. */
    async fillLabel(label, value) {
      const marked = await evaluate(`(() => { const l = [...document.querySelectorAll("label")].find((x) => x.innerText.trim().startsWith(${JSON.stringify(label)}));
        const el = l && l.querySelector("input, textarea, select"); if (!el) return false; el.setAttribute("data-e2e", "target"); return true; })()`);
      if (!marked) throw new Error(`No field labelled "${label}" (page: ${(await b.text()).slice(0, 200)})`);
      await b.fill('[data-e2e="target"]', value);
      await evaluate(`document.querySelector('[data-e2e="target"]').removeAttribute("data-e2e")`);
    },
    /** Pick an option (by its visible text) in the dropdown found by its label text. */
    async selectLabel(label, optionText) {
      const value = await evaluate(`(() => { const l = [...document.querySelectorAll("label")].find((x) => x.innerText.trim().startsWith(${JSON.stringify(label)}));
        const sel = l && l.querySelector("select"); if (!sel) return null;
        const opt = [...sel.options].find((o) => o.text.includes(${JSON.stringify(optionText)})); return opt ? opt.value : null; })()`);
      if (value === null) throw new Error(`No dropdown "${label}" with an option "${optionText}"`);
      await b.fillLabel(label, value);
    },
    /** Click the first button/link whose visible text equals (or starts with) `text`. */
    async clickText(text, { exact = true } = {}) {
      const ok = await evaluate(`(() => { const t = ${JSON.stringify(text)};
        const el = [...document.querySelectorAll("button, a, [role=tab]")].find((x) => { const s = x.innerText.trim(); return ${exact ? "s === t" : "s.startsWith(t)"}; });
        if (!el) return false; el.click(); return true; })()`);
      if (!ok) throw new Error(`No button/link "${text}" (page: ${(await b.text()).slice(0, 200)})`);
    },
    /**
     * A REAL mouse click (move, press, release) in the middle of the element, like a person's: it lands on whatever is on top
     * at that spot, so a covered or non-clickable area is noticed (element.click() would not notice). Returns what was under the mouse.
     */
    async realClick(selector) {
      const spot = await evaluate(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); if (!el) return null;
        el.scrollIntoView({ block: "center" }); const r = el.getBoundingClientRect(); const x = r.left + r.width / 2, y = r.top + r.height / 2;
        const top = document.elementFromPoint(x, y); return { x, y, top: top ? top.tagName + (top.getAttribute("aria-label") ? "[" + top.getAttribute("aria-label") + "]" : "") : null }; })()`);
      if (!spot) throw new Error(`Nothing to click: ${selector}`);
      for (const type of ["mouseMoved", "mousePressed", "mouseReleased"]) {
        await send("Input.dispatchMouseEvent", { type, x: spot.x, y: spot.y, button: type === "mouseMoved" ? "none" : "left", clickCount: type === "mouseMoved" ? 0 : 1 });
      }
      return spot.top;
    },
    submit: () => evaluate(`document.querySelector("form button[type=submit]").click()`),
    async login(email, password) {
      lastPassword = password;
      loggedInAsAdmin = email === creds.admin[0];
      await b.goto("/login");
      await b.fill("input[type=email]", email);
      await b.fill("input[type=password]", password);
      await b.submit();
    },
    async shot(name) {
      const s = await send("Page.captureScreenshot", { format: "png" });
      writeFileSync(`${out}\\${name}.png`, Buffer.from(s.result.data, "base64"));
    },
    async apiStatus(path) {  // a request from inside the page, with its login cookie
      return evaluate(`fetch(${JSON.stringify(API + path)}, { credentials: "include" }).then((r) => r.status)`);
    },
    async apiJson(path) {  // the JSON answer of a request from inside the page, with its login cookie
      return evaluate(`fetch(${JSON.stringify(API + path)}, { credentials: "include" }).then((r) => r.json())`);
    },
    close() { try { ws.close(); } catch { /* ignore */ } proc.kill(); },
  };
  return b;
}

/** Collect PASS/FAIL results and print a summary. */
export function suite(title) {
  let failures = 0;
  let total = 0;
  console.log(`\n=== ${title}`);
  return {
    check(name, ok, extra = "") {
      total++;
      if (!ok) failures++;
      console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${extra ? "  " + extra : ""}`);
    },
    finish(...browsers) {
      for (const b of browsers) {
        if (b.problems.length) {
          failures++;
          console.log("[FAIL] browser errors:\n    " + b.problems.join("\n    "));
        }
      }
      console.log(failures === 0 ? `--- ${title}: all ${total} checks passed` : `--- ${title}: ${failures} PROBLEM(S)`);
      for (const b of browsers) b.close();
      process.exit(failures ? 1 : 0);
    },
  };
}

export const ids = JSON.parse(process.env.E2E_IDS || "{}");
export const out = process.env.E2E_OUT || ".";
export const creds = { admin: ["admin@e2e.test", "Admin-E2E-Pass-1"], owner: ["owner@demo.test", "Owner-E2E-Pass-1"], viewer: ["viewer@demo.test", "Viewer-E2E-Pass-1"], other: ["other@other.test", "Other-E2E-Pass-1"], resetme: ["resetme@demo.test", "Reset-E2E-Pass-1"] };
