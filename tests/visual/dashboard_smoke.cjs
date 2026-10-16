"use strict";
/**
 * Read-only browser acceptance on synthetic data. Never contacts production,
 * never sends a write to the dashboard, never uses customer data.
 */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { chromium } = require("playwright");

const ASSETS = path.resolve(__dirname, "../../deploy/cloud/assets");
const OUT = path.resolve(process.env.UI_ARTIFACT_DIR || "artifacts/visual");
const CASES = ["first-run", "empty-account", "backend-error"];
const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 390, height: 844 },
];
let writes = 0;
const sample = {
  account_initialized: true,
  as_of: "2026-10-15",
  values: { QQQ: "100000", TQQQ: "20000", QLD: "0", CASH: "30000" },
  total_value_cny: 150000,
  state_version: "state/synthetic-fixture.zip",
  recorded_at: "2026-10-15T12:00:00+00:00",
  note: "SYNTHETIC TEST DATA ONLY",
  trading_enabled: false,
};
const fakeHistory = {
  history: [
    { as_of: "2026-10-14", total_value_cny: 145000,
      values: { QQQ: "97000", TQQQ: "18000", QLD: "0", CASH: "30000" },
      note: "SYNTHETIC" },
    { as_of: "2026-10-15", total_value_cny: 150000,
      values: sample.values, note: "SYNTHETIC" },
  ],
};
function respond(res, status, obj) {
  const data = JSON.stringify(obj);
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store", "Content-Length": Buffer.byteLength(data) });
  res.end(data);
}
function handler(req, res) {
  const url = new URL(req.url, "http://localhost");
  const scenario = url.searchParams.get("fixture") || "first-run";
  if (req.method !== "GET") {
    writes += 1;
    return respond(res, 405, { error: "Synthetic UI test forbids writes" });
  }
  const files = {
    "/": "index.html", "/setup": "index.html",
    "/assets/app.css": "app.css", "/assets/decision.css": "decision.css",
    "/assets/app.js": "app.js",
  };
  if (Object.prototype.hasOwnProperty.call(files, url.pathname)) {
    const name = files[url.pathname];
    const bytes = fs.readFileSync(path.join(ASSETS, name));
    const type = name.endsWith(".html") ? "text/html; charset=utf-8" :
      name.endsWith(".css") ? "text/css; charset=utf-8" : "text/javascript; charset=utf-8";
    res.writeHead(200, { "Content-Type": type, "Content-Length": bytes.length });
    return res.end(bytes);
  }
  if (!url.pathname.startsWith("/api/")) return respond(res, 404, { status: "NOT_FOUND" });
  if (scenario === "backend-error") return respond(res, 503, { status: "STORAGE_ERROR" });
  const empty = scenario === "empty-account";
  const payloads = {
    "/api/account": empty ? { account_initialized: false } : sample,
    "/api/status": empty ?
      { status: "SETUP_REQUIRED", account_initialized: false, storage_verified: true,
        latest_run_exists: false, execution_enabled: false } :
      { status: "READY_FOR_FIRST_RUN", account_initialized: true, storage_verified: true,
        latest_run_exists: false, execution_enabled: false },
    "/api/history": empty ? { history: [] } : fakeHistory,
    "/api/brief": {
      status: empty ? "NEEDS_ACCOUNT" : "NEEDS_VERIFIED_RUN",
      headline: empty ? "尚未保存账户" : "等待首次真实行情核验",
      explanation: "本场景为合成测试数据，不产生交易建议。",
      next_step: empty ? "先保存账户估值。" : "人工检查并运行一次监控。",
      actionable: false, verified_run: false, steps: [], trading_enabled: false,
    },
  };
  if (url.pathname === "/api/latest") return respond(res, 404, { status: "NEEDS_FIRST_ONLINE_RUN" });
  if (Object.prototype.hasOwnProperty.call(payloads, url.pathname)) {
    return respond(res, 200, payloads[url.pathname]);
  }
  return respond(res, 404, { status: "NOT_FOUND" });
}
async function inspect(browser, base, scenario, vp) {
  const context = await browser.newContext({
    viewport: { width: vp.width, height: vp.height },
    deviceScaleFactor: 1, reducedMotion: "reduce", colorScheme: "light",
  });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", err => errors.push(String(err.message)));
  const label = scenario + "-" + vp.name;
  try {
    await page.goto(base + "/?fixture=" + scenario, { waitUntil: "load" });
    await page.locator("#app-loading").waitFor({ state: "hidden", timeout: 20000 });
    assert.match(await page.title(), /^InvestLab — /, label + " unexpected page title");
    assert.equal(await page.locator('[data-page="overview"]').isVisible(), true,
      label + " overview missing");
    assert.ok((await page.locator("#decision-headline").innerText()).trim().length > 4,
      label + " empty decision");
    const dims = await page.evaluate(() => ({
      vw: window.innerWidth, doc: document.documentElement.scrollWidth,
      body: document.body.scrollWidth,
    }));
    assert.ok(dims.doc <= dims.vw + 2 && dims.body <= dims.vw + 2,
      label + " horizontal page overflow " + JSON.stringify(dims));
    if (scenario === "backend-error") {
      assert.equal(await page.locator("#global-error").isVisible(), true,
        label + " lacks visible error");
    } else {
      assert.equal(await page.locator("#global-error").isVisible(), false,
        label + " unexpected account error");
      if (scenario === "first-run") {
        assert.match(await page.locator("#decision-proof-total").innerText(), /150,000/,
          label + " synthetic account not rendered");
        assert.equal(await page.locator('[data-open-run]').first().isDisabled(), false,
          label + " manual run not available");
      } else {
        assert.equal(await page.locator('[data-open-run]').first().isDisabled(), true,
          label + " manual run should be disabled");
      }
    }
    await page.screenshot({ path: path.join(OUT, label + "-overview.png"),
      fullPage: true, animations: "disabled" });
    if (scenario !== "backend-error") {
      if (vp.name === "mobile") {
        await page.locator("#mobile-menu").click();
      }
      await page.locator('.nav-item[data-route="portfolio"]').click();
      assert.equal(await page.locator('[data-page="portfolio"]').isVisible(), true,
        label + " portfolio nav failed");
      await page.screenshot({ path: path.join(OUT, label + "-portfolio.png"),
        fullPage: true, animations: "disabled" });
      if (scenario === "first-run") {
        if (vp.name === "mobile") await page.locator("#mobile-menu").click();
        await page.locator('.nav-item[data-route="runs"]').click();
        await page.locator('[data-page="runs"] [data-open-run]').click();
        assert.equal(await page.locator("#run-dialog").evaluate(el => el.open), true,
          label + " run confirmation did not open");
        await page.locator("#run-dialog [data-close-dialog]").first().click();
        assert.equal(await page.locator("#run-dialog").evaluate(el => el.open), false,
          label + " confirmation did not close");
      }
    }
    assert.deepEqual(errors, [], label + " JavaScript runtime exceptions");
    console.log("UI_VISUAL_PASS", label, "viewport", vp.width + "x" + vp.height);
  } catch (err) {
    await page.screenshot({ path: path.join(OUT, label + "-FAILED.png"),
      fullPage: true }).catch(() => {});
    throw err;
  } finally {
    await context.close();
  }
}
async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  const server = http.createServer(handler);
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const port = server.address().port;
  const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
  try {
    for (const scenario of CASES) for (const vp of VIEWPORTS) {
      await inspect(browser, "http://127.0.0.1:" + port, scenario, vp);
    }
    assert.equal(writes, 0, "UI browser checks must never write");
    console.log("UI_BROWSER_ACCEPTANCE_PASS", CASES.length * VIEWPORTS.length,
      "scenarios; writes=0; synthetic-only");
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
}
main().catch(err => { console.error("UI_BROWSER_ACCEPTANCE_FAIL", err); process.exitCode = 1; });
