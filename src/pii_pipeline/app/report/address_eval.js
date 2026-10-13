// Runs the detection module's address evaluation (pii_pipeline.detection.address_eval) on the held-out
// test split of data/indian_address for the deployed fine-tuned TinyBERT and the fine-tuned ModernBERT it was
// compared with, and saves each result to data/outputs/address_model_eval/<name>.json for build_report.js.
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const ROOT = path.resolve(__dirname, "../../../..");
const OUT = path.join(ROOT, "data", "outputs", "address_model_eval");
const VENV = path.join(ROOT, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const PYTHON = process.env.PYTHON || (fs.existsSync(VENV) ? VENV : "python");
const py = (args) => execFileSync(PYTHON, args, { cwd: ROOT, env: { ...process.env, PYTHONPATH: "src" }, maxBuffer: 1 << 26 }).toString();

const deployed = py(["-c", "from pii_pipeline.detection.detector_address import MODEL; print(MODEL)"]).trim();
const models = { "tinybert-ft (deployed)": deployed, "modernbert-ft": "data/models/open-modernbert-indian-address-ner-ft" };
fs.mkdirSync(OUT, { recursive: true });
for (const [name, model] of Object.entries(models)) {
  if (!model.includes("/") || (model.startsWith("data/") && !fs.existsSync(path.join(ROOT, model)))) {
    console.log(`skip ${name}: ${model} not found`);
    continue;
  }
  const out = py(["-m", "pii_pipeline.detection.address_eval", model, "test"]);
  const result = { name, model, ...JSON.parse(out.slice(out.indexOf("{"))) };   // the module prints one JSON object
  fs.writeFileSync(path.join(OUT, `${name.split(" ")[0]}.json`), JSON.stringify(result, null, 2));
  console.log(name, JSON.stringify(result));
}
