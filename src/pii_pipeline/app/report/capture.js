// Drives the real PII Shield UI on data/sample.{pdf,docx,pptx}: run, screenshot every view, score, save exports.
// Start the server first (see ../README.md). Output: data/outputs/screenshots and data/outputs/app_results.
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");
const puppeteer = require("puppeteer-core");

const ROOT = path.resolve(__dirname, "../../../..");
const DATA = path.join(ROOT, "data");
const OUT = path.join(DATA, "outputs");
const SHOTS = path.join(OUT, "screenshots");
const API = path.join(OUT, "app_results");
const URL = process.env.PII_SHIELD_URL || "http://127.0.0.1:8000";
const CHROME = process.env.CHROME_PATH || "C:/Program Files/Google/Chrome/Application/chrome.exe";
fs.rmSync(SHOTS, { recursive: true, force: true });
fs.rmSync(API, { recursive: true, force: true });
fs.mkdirSync(SHOTS, { recursive: true });
fs.mkdirSync(API, { recursive: true });
// The three team samples plus a synthetic Indian-address document written by make_address_demo.py.
const VENV = path.join(ROOT, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
execFileSync(process.env.PYTHON || (fs.existsSync(VENV) ? VENV : "python"), [path.join(__dirname, "make_address_demo.py")]);
const SAMPLES = ["sample.pdf", "sample.docx", "sample.pptx", "sample_addresses.docx"].map((f) => path.join(DATA, f));
const SLUGS = ["pdf", "docx", "pptx", "addresses"];   // screenshot names, in SAMPLES order

// The samples are byte-identical copies of the Cadence documents the team's ground truth labels,
// so the ground truth is reused with only its file column renamed to the sample names.
const GT = path.join(OUT, "ground_truth_samples.csv");
const RENAME = {
  "Cadence_Group_Risk_Management_Policy__v6_0.pdf": "sample.pdf",
  "Cadence_TPRM_Training.docx": "sample.docx",
  "Cadence_Financial_Group_Organizational_Pack.pptx": "sample.pptx",
};
const gtSource = fs.readFileSync(path.join(ROOT, "src/pii_pipeline/evaluation/ground_truth_cadence_updated_with_addresses.csv"), "utf8");
fs.writeFileSync(GT, gtSource.replace(/^([^,\r\n]+),/gm, (m, file) => (RENAME[file] ? `${RENAME[file]},` : m)));

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let n = 0;

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: true,
    protocolTimeout: 0,
    defaultViewport: { width: 1440, height: 1000, deviceScaleFactor: 1.5 },
  });
  const page = await browser.newPage();
  page.setDefaultTimeout(0);
  page.on("pageerror", (e) => { console.log("Error in page:", e.message); process.exit(1); });
  page.on("response", async (r) => {
    const u = r.url();
    try {
      if (u.endsWith("/process")) {
        const v = await r.json();
        fs.writeFileSync(path.join(API, `${v.filename}.json`), JSON.stringify(v, null, 2));
        console.log("processed", v.filename, v.status, JSON.stringify(v.timings));
      } else if (u.endsWith("/evaluate")) {
        fs.writeFileSync(path.join(API, `evaluation.json`), JSON.stringify(await r.json(), null, 2));
      }
    } catch (e) { console.log("response capture failed", u, e.message); }
  });

  const shot = async (name, selector) => {
    await sleep(600);
    const file = path.join(SHOTS, `${String(++n).padStart(2, "0")}_${name}.png`);
    if (selector) {
      const el = await page.$(selector);
      const box = await el.boundingBox();
      const CHUNK = 1300;   // CSS px per image so long panels stay readable in the report
      if (box.height <= CHUNK * 1.15) {
        await el.screenshot({ path: file });
      } else {
        const parts = Math.ceil(box.height / CHUNK);
        for (let i = 0; i < parts; i++) {
          const y = i * CHUNK;
          const part = file.replace(".png", `_part${i + 1}.png`);
          await el.screenshot({ path: part, clip: { x: 0, y, width: box.width, height: Math.min(CHUNK, box.height - y) } });
        }      }
    } else {
      await page.screenshot({ path: file });
    }
    console.log("shot", path.basename(file));
  };
  const clickText = async (selector, text) => {
    const ok = await page.$$eval(selector, (els, t) => {
      const el = els.find((e) => e.textContent.trim().startsWith(t));
      if (el) el.click();
      return !!el;
    }, text);
    if (!ok) throw new Error(`no ${selector} with text ${text}`);
    await sleep(500);
  };
  const scrollTo = (selector) => page.$eval(selector, (e) => e.scrollIntoView({ block: "start" }));

  await page.evaluateOnNewDocument(() => localStorage.setItem("pii-theme", "light"));
  await page.goto(URL, { waitUntil: "networkidle0" });
  await shot("home");

  const input = await page.$('input[type=file][multiple]');
  await input.uploadFile(...SAMPLES);
  await page.waitForSelector(".file-row");
  await scrollTo(".upload-section");
  await shot("file_queue");

  const t0 = Date.now();
  await clickText("button", "Run Analysis");
  await page.waitForSelector(".analysis-progress");
  await shot("processing");
  await page.waitForSelector(".results-section", { timeout: 0 });
  console.log("run seconds", Math.round((Date.now() - t0) / 1000));

  await scrollTo(".results-section");
  await shot("results_overview");
  await shot("overview_panel", ".results-section");

  await clickText("button[role=tab]", "Findings");
  await shot("findings", ".tab-panel");
  await page.$$eval("tr.row-clickable", (rows) => rows[0].click());
  await shot("finding_detail", ".tab-panel");

  await clickText("button[role=tab]", "File Details");
  for (let i = 0; i < SAMPLES.length; i++) {
    await page.select(".tab-panel select.select", String(i));
    await sleep(500);
    for (const [tab, slug] of [["Detected PII", "detected"], ["Redacted Text", "redacted"], ["Extraction", "extraction"], ["Traceability", "trace"]]) {
      await clickText(".tabs--inner button[role=tab]", tab);
      await scrollTo(".tab-panel");
      await shot(`${SLUGS[i]}_${slug}`, ".tab-panel");
    }
  }

  await clickText("button[role=tab]", "Evaluation");
  const gt = await page.$('input[type=file][accept=".csv"]');
  await gt.uploadFile(GT);
  await page.waitForFunction(() => document.body.textContent.includes("Per PII type"), { timeout: 0 });
  await shot("evaluation", ".tab-panel");
  await clickText("summary", "Diagnosis");
  await shot("evaluation_diagnosis", ".tab-panel");

  await clickText("button[role=tab]", "Exports");
  await shot("exports", ".tab-panel");

  const runId = await page.$eval(".results-run-id code", (e) => e.textContent);
  console.log("run id prefix", runId);
  const saved = await page.evaluate(async () => {
    const id = [...document.querySelectorAll("a")].map((a) => a.getAttribute("href") || "")
      .find((h) => h.includes("/report.json")).split("/")[3];
    const get = (p) => fetch(`/api/runs/${id}/${p}`);
    const zip = new Uint8Array(await (await get("redacted.zip")).arrayBuffer());
    let bin = "";
    zip.forEach((b) => { bin += String.fromCharCode(b); });
    return { report: await (await get("report.json")).text(), csv: await (await get("findings.csv")).text(), zip: btoa(bin) };
  });
  fs.writeFileSync(path.join(API, "exposure_report.json"), saved.report);
  fs.writeFileSync(path.join(API, "findings.csv"), saved.csv);
  fs.writeFileSync(path.join(API, "redacted_for_llm.zip"), Buffer.from(saved.zip, "base64"));
  console.log("exports saved");
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
