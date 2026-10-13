// Builds data/outputs/PII_Shield_Report.docx. Every result number is read from the app's real API responses.
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell, WidthType, ShadingType,
  ImageRun, AlignmentType, LevelFormat, PageBreak, TableOfContents, Footer, PageNumber, BorderStyle,
} = require("docx");

const os = require("os");
const { execSync } = require("child_process");

const ROOT = path.resolve(__dirname, "../../../..");
const OUT = path.join(ROOT, "data", "outputs");
const API = path.join(OUT, "app_results");
const SHOTS = path.join(OUT, "screenshots");
const git = (args) => execSync(`git ${args}`, { cwd: ROOT }).toString().trim();
const GT_SOURCE = "src/pii_pipeline/evaluation/ground_truth_cadence_updated_with_addresses.csv";
const runAt = fs.statSync(path.join(API, "evaluation.json")).mtime;
const META = {
  date: runAt.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" }),
  branch: git("rev-parse --abbrev-ref HEAD"),
  commit: git("rev-parse --short HEAD"),
  machine: `${os.version()}, ${os.cpus()[0].model.trim()} (${os.cpus().length} threads), ${Math.round(os.totalmem() / 2 ** 30)} GB RAM`,
  gt_source: GT_SOURCE,
  gt_note: "The sample files are byte-identical (same SHA-256) to the three Cadence documents this ground truth labels, so capture.js copies its rows to data/outputs/ground_truth_samples.csv with only the file column renamed to sample.pdf / sample.docx / sample.pptx.",
};
const FILES = ["sample.pdf", "sample.docx", "sample.pptx"].map((f) => JSON.parse(fs.readFileSync(path.join(API, `${f}.json`), "utf8")));
const EVAL = JSON.parse(fs.readFileSync(path.join(API, "evaluation.json"), "utf8"));
const shots = fs.readdirSync(SHOTS).filter((f) => f.endsWith(".png"));

const W = 9026;           // A4 text width in DXA with 1" margins
const FONT = "Calibri";
const ACCENT = "0E7490";
const sum = (o) => Object.values(o || {}).reduce((a, b) => a + b, 0);
const pct = (x) => (x == null ? "n/a" : `${(x * 100).toFixed(1)}%`);
const f3 = (x) => x.toFixed(3);
const secs = (x) => `${x.toFixed(1)} s`;

// ---------- building blocks
const P = (text, opts = {}) => new Paragraph({ spacing: { after: 120 }, ...opts, children: runs(text) });
function runs(text) {
  // **bold** and `code` markup
  return String(text).split(/(\*\*[^*]+\*\*|`[^`]+`)/).filter(Boolean).map((t) =>
    t.startsWith("**") ? new TextRun({ text: t.slice(2, -2), bold: true })
      : t.startsWith("`") ? new TextRun({ text: t.slice(1, -1), font: "Consolas", size: 20 })
        : new TextRun(t));
}
const H1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: true, children: [new TextRun(t)] });
const H2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(t)] });
const H3 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun(t)] });
const bullet = (t, level = 0) => new Paragraph({ numbering: { reference: "bullets", level }, spacing: { after: 60 }, children: runs(t) });
const bullets = (items) => items.map((t) => bullet(t));
const caption = (t) => new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 240 }, children: [new TextRun({ text: t, italics: true, size: 18, color: "555555" })] });

function table(header, rows, widths) {
  const total = widths.reduce((a, b) => a + b, 0);
  const cols = widths.map((w) => Math.round((w / total) * W));
  cols[cols.length - 1] += W - cols.reduce((a, b) => a + b, 0);
  const border = { style: BorderStyle.SINGLE, size: 4, color: "BFCBD3" };
  const borders = { top: border, bottom: border, left: border, right: border };
  const cell = (text, i, head) => new TableCell({
    width: { size: cols[i], type: WidthType.DXA },
    borders,
    shading: head ? { type: ShadingType.CLEAR, fill: "E0F2F7", color: "auto" } : undefined,
    margins: { top: 60, bottom: 60, left: 100, right: 100 },
    children: [new Paragraph({ children: [new TextRun({ text: String(text ?? "-"), bold: head, size: 19 })] })],
  });
  return new Table({
    width: { size: W, type: WidthType.DXA },
    columnWidths: cols,
    rows: [new TableRow({ tableHeader: true, children: header.map((h, i) => cell(h, i, true)) }),
      ...rows.map((r) => new TableRow({ children: r.map((c, i) => cell(c, i, false)) }))],
  });
}
const spacer = () => new Paragraph({ spacing: { after: 120 }, children: [] });

function pngSize(file) {
  const b = fs.readFileSync(file);
  return { w: b.readUInt32BE(16), h: b.readUInt32BE(20), data: b };
}
function shot(name, text) {
  const files = shots.filter((f) => new RegExp(`^\\d+_${name}(_part\\d+)?\\.png$`).test(f)).sort();
  if (!files.length) throw new Error(`missing screenshot ${name}`);
  return files.flatMap((file, i) => {
    const { w, h, data } = pngSize(path.join(SHOTS, file));
    let width = 600;
    let height = Math.round((h / w) * width);
    if (height > 820) { width = Math.round((820 / height) * width); height = 820; }
    const part = files.length > 1 ? ` (part ${i + 1} of ${files.length})` : "";
    return [
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 120, after: 60 }, keepNext: true,
        children: [new ImageRun({ type: "png", data, transformation: { width, height } })] }),
      caption(`Screenshot ${file.slice(0, 2)}: ${text}${part}`),
    ];
  });
}

// ---------- derived real numbers
const ok = FILES.filter((f) => f.status !== "failed");
const totDet = sum(Object.fromEntries(FILES.map((f) => [f.filename, f.entities.length])));
const totRed = FILES.reduce((a, f) => a + f.records.length, 0);
const totBlocks = FILES.reduce((a, f) => a + f.block_count, 0);
const totTime = FILES.reduce((a, f) => a + sum(f.timings), 0);
const cleared = FILES.filter((f) => f.llm_ready).length;
const leaks = FILES.reduce((a, f) => a + f.leaks.length, 0);
const ov = EVAL.overall;
const typeRows = (o) => Object.entries(o).map(([k, v]) => `${k} ${v}`).join(", ") || "-";
const byName = Object.fromEntries(FILES.map((f) => [f.filename.split(".")[1], f]));
const evalOf = Object.fromEntries(EVAL.files.map((x) => [x.file.split(".")[1], x]));
// "MISSED by cause" lines of evaluation.diagnose: "  TYPE  cause  n"
const causes = {};
const typeCauses = {};
EVAL.diagnosis.split("MISSED value shapes")[0].split("\n").forEach((l) => {
  const m = l.match(/^\s+(\S+)\s+(.+?)\s+(\d+)$/);
  if (!m) return;
  causes[m[2]] = (causes[m[2]] || 0) + Number(m[3]);
  (typeCauses[m[1]] = typeCauses[m[1]] || []).push(`${m[2]} ${m[3]}`);
});
const fpTypes = (EVAL.diagnosis.match(/FALSE POSITIVES by type: (.*)/) || [])[1] || "";
const zeroRecall = EVAL.per_type.filter((t) => t.support > 0 && t.tp === 0)
  .map((t) => `${t.type} (${t.support} labelled; ${(typeCauses[t.type] || []).join(", ")})`);
const unlabelledTypes = EVAL.per_type.filter((t) => t.support === 0).map((t) => `${t.type} (${t.fp} detection)`);
const observed = [
  `sample.pdf was not cleared for the LLM: redaction verified all ${byName.pdf.block_count} blocks, but the residual check found ${byName.pdf.leaks.length} detected value(s) repeated in blocks where detection missed them: ${byName.pdf.leaks.join(" ")} This is the safety check working: the file's redacted text is withheld from the ZIP and .txt exports.`,
  `sample.pdf is a scanned document: ${byName.pdf.extraction.sources.ocr || 0} of ${byName.pdf.block_count} blocks come from OCR, and ${byName.pdf.extraction.low_ocr_blocks} OCR blocks are below the ${byName.pdf.extraction.low_ocr_threshold} confidence threshold. Extraction (${secs(byName.pdf.timings.extraction)}) dominates its processing time.`,
  `sample.docx is image-heavy: ${byName.docx.extraction.ocr_blocks} OCR blocks with mean confidence ${pct(byName.docx.extraction.mean_ocr)}, ${byName.docx.extraction.low_ocr_blocks} of them below ${byName.docx.extraction.low_ocr_threshold}. Its recall (${pct(evalOf.docx.recall)}) is the lowest of the three files. DOCX has no fixed pages, so its page count shows 0 and locations are paragraph/table positions.`,
  `Misses by cause (evaluation.diagnose): ${Object.entries(causes).map(([k, v]) => `${k} ${v}`).join(", ")}. "Not in extracted text" means the labelled value does not appear in the extracted text at all (for example text in an image that OCR skipped or misread); "found, wrong type or span" means a detection overlapped the value but with another type or a different span.`,
  `False positives by type: ${fpTypes.replace(/[{}']/g, "")}.`,
  `Labelled types never found: ${zeroRecall.join(", ") || "none"}.${unlabelledTypes.length ? ` Types detected but not labelled in the ground truth: ${unlabelledTypes.join(", ")}.` : ""}`,
  `Speed on the machine listed on the title page: ${FILES.map((f) => `${f.filename} ${secs(sum(f.timings))}`).join(", ")}. OCR and the transformer models (GLiNER, TinyBERT, spaCy) take almost all of it; redaction itself takes milliseconds.`,
];
const warnCodes = (f) => {
  const c = {};
  f.extraction.warnings.forEach((w) => { c[w.code] = (c[w.code] || 0) + 1; });
  return c;
};

// ---------- content
const children = [];
children.push(
  new Paragraph({ spacing: { before: 2400, after: 200 }, children: [new TextRun({ text: "PII Shield", bold: true, size: 72, color: ACCENT })] }),
  new Paragraph({ spacing: { after: 200 }, children: [new TextRun({ text: "PII Redaction Pipeline: features, implementation, evaluation and limitations", size: 34 })] }),
  new Paragraph({ spacing: { after: 600 }, children: [new TextRun({ text: `Results of a real run of the web application on sample.pdf, sample.docx and sample.pptx (${META.date})`, size: 24, color: "555555" })] }),
  table(["Item", "Value"], [
    ["Branch / commit", `${META.branch} @ ${META.commit}`],
    ["Run", "Web UI (React) -> FastAPI -> extraction -> detection -> redaction -> verification -> evaluation"],
    ["Documents", FILES.map((f) => f.filename).join(", ")],
    ["Ground truth", `${ov.support} labelled PII occurrences (${META.gt_source})`],
    ["Machine", META.machine],
  ], [1, 3]),
  new Paragraph({ children: [new PageBreak()] }),
  new Paragraph({ spacing: { after: 160 }, children: [new TextRun({ text: "Contents", bold: true, size: 34, color: ACCENT })] }),
  new TableOfContents("Contents", { hyperlink: true, headingStyleRange: "1-2" }),
  P("Right-click the table and choose Update Field if page numbers are missing."),
);

// 1. Summary
children.push(H1("1. Summary"));
children.push(P(`All three sample documents were uploaded through the web application and processed by the team's real modules. No value in this document is typed by hand: every number comes from the API responses saved in data/outputs/app_results (one JSON per document, evaluation.json, exposure_report.json and findings.csv).`));
children.push(table(["Result", "Value"], [
  ["Files processed", `${ok.length}/${FILES.length}`],
  ["Text blocks extracted", totBlocks.toLocaleString()],
  ["PII detections (detection.detect)", totDet.toLocaleString()],
  ["Redactions applied (merged spans)", totRed.toLocaleString()],
  ["Files cleared for LLM", `${cleared}/${FILES.length}`],
  ["Residual leaks found by the app check", leaks],
  ["Total processing time", secs(totTime)],
  ["Precision / Recall / F1 (all 3 files)", `${pct(ov.precision)} / ${pct(ov.recall)} / ${pct(ov.f1)}`],
  ["Labelled PII: found / missed / leaked", `${ov.tp} / ${EVAL.counts.missed} / ${EVAL.counts.leaked}`],
  ["False positives", ov.fp],
], [2, 2]));
children.push(spacer());
children.push(table(["File", "Status", "Pages", "Blocks", "Detections", "Redactions", "Leaks", "LLM ready", "Time"],
  FILES.map((f) => [f.filename, f.status, f.pages.length, f.block_count, f.entities.length, f.records.length, f.leaks.length,
    f.llm_ready ? "yes" : "no", secs(sum(f.timings))]), [2.2, 1.2, 1, 1, 1.3, 1.3, 0.9, 1.1, 1.1]));
children.push(...shot("results_overview", "results dashboard after the run: summary cards and per-file table"));

// 2. Architecture
children.push(H1("2. Architecture and data flow"));
children.push(P("The pipeline has four modules that share the data classes in schemas.py (TextBlock, Entity, RedactedBlock), plus the application layer that connects them to a browser."));
children.push(table(["Stage", "Module call", "Output"], [
  ["Upload + validation", "app backend (server.py, pipeline.py)", "file type allowed by extraction, not empty, at most 25 MB"],
  ["Extraction", "extraction.extract_document_detailed(path)", "TextBlocks in reading order + BlockMeta + coded warnings"],
  ["Detection", "detection.detector.detect(blocks)", "Entities with block offsets, type, confidence, detector"],
  ["Redaction", "redaction.redact_document(blocks, entities)", "RedactedBlocks + TraceRecords; every block verified"],
  ["Report", "redaction.build_report(records)", "exposure report: findings + counts, no values"],
  ["Residual check", "app: residual_leaks()", "a detected value still present anywhere -> not cleared"],
  ["Evaluation", "evaluation.evaluate_redaction + diagnose", "precision, recall, F1 per file and per type"],
], [1.3, 2.4, 2.6]));
children.push(spacer());
children.push(P("**Privacy rule across all stages:** the raw value of a detection (Entity.value) and the original block text stay inside the server process. API responses, the UI, the exports and this document contain only types, placeholders, offsets, locations, confidences and redacted text."));

// 3. Application layer
children.push(H1("3. Application layer (web app)"));
children.push(H2("3.1 What was integrated"));
children.push(P("The application branch (React front-end + FastAPI back-end) was merged with the latest pipeline code (detection-tuning, built on main). Its committed node_modules folder was left out of the merge and is now ignored by git."));
children.push(P("Before the integration the back-end fell back to stand-ins whenever it could not guess the team's function names, and the front-end carried demo values. All of these were removed:"));
children.push(...bullets([
  "**Removed** `mock_modules.py` (regex mock detector, pypdf/python-docx mock extractor, the \"[MOCK DATA] Jane Smith\" sample text) and `make_samples.py` (fake sample files).",
  "**Removed** the built-in fallback redactor and the name-guessing loader (`backend_config.py`): the back-end now imports and calls the real functions directly, so a missing module fails loudly instead of silently showing mock output.",
  "**Removed** hard-coded front-end values: the format list (including .txt, which extraction does not support), MIME types, the 25 MB constant, and the file-type labels. Supported formats and the size limit now come from `/api/config`, which reads the extraction module's own extension list.",
  "**Removed** the invented High/Medium/Low severity and risk levels (a fixed type list not produced by the pipeline), the \"Non-PII preserved\" demo proxy metric and the client-side \"show original value\" feature.",
  "**Replaced** the app's own scoring with the team's evaluation module (`evaluate_redaction`, `diagnose`).",
  "**Fixed** the per-file \"Download .txt\" link, which used an undefined run id.",
]));
children.push(H2("3.2 What the UI shows (all real pipeline outputs)"));
children.push(table(["View", "Content", "Source"], [
  ["Summary cards", "files processed, detections, redactions, cleared files, residual leaks, time", "process responses"],
  ["Overview", "per-file status, pages, blocks, detections, redactions by type, timing; charts by type and detector", "build_report summary, detect"],
  ["Findings", "every detection: type, placeholder, confidence, detector, file, page, location, offsets; search + filters", "Entity.public_info + BlockMeta.page"],
  ["File details / Detected PII", "the same per file, filter by type, detector, page", "detect"],
  ["File details / Redacted Text", "redacted blocks per page/slide with highlighted placeholders, copy, download", "RedactedBlock"],
  ["File details / Extraction", "blocks by source and kind, OCR confidence, hidden blocks, table rows, coded warnings", "ExtractionResult meta + warnings"],
  ["File details / Traceability", "verification result, redactions by type, detections by detector, placeholder index, trace records, exposure report", "TraceRecord, build_report"],
  ["Evaluation", "precision, recall, F1, accuracy, missed, leaked, false positives, per file and per type, diagnosis", "evaluate_redaction, diagnose"],
  ["Exports", "exposure_report.json, findings.csv (trace records), redacted ZIP, per-file .txt", "server exports"],
], [1.5, 3.2, 1.6]));
children.push(H2("3.3 API"));
children.push(table(["Endpoint", "Purpose"], [
  ["GET /api/config", "supported extensions (from extraction), upload limit, ground-truth columns (from evaluation)"],
  ["POST /api/runs", "start a run (results kept in memory, max 20 runs)"],
  ["POST /api/runs/{id}/process", "run the full pipeline on one uploaded file, return the view-model"],
  ["POST /api/runs/{id}/evaluate", "score the run against an uploaded ground-truth CSV (metrics and counts only)"],
  ["GET /api/runs/{id}/report.json | findings.csv | redacted.zip | files/{n}/redacted.txt", "exports; ZIP and .txt only for files cleared for LLM"],
  ["DELETE /api/runs/{id}", "Clear all: forget the run"],
], [2.6, 3.4]));
children.push(H2("3.4 Test run in the browser"));
children.push(P("The run was driven in headless Chrome against the real server: the three samples were added to the queue, Run Analysis was pressed, and each view was captured."));
children.push(...shot("home", "landing page; formats and limit come from the server"));
children.push(...shot("file_queue", "the three samples queued and validated"));
children.push(...shot("processing", "processing in progress"));
children.push(...shot("overview_panel", "Overview tab with redactions by PII type and detections by detector"));

// 4. Extraction
children.push(H1("4. Extraction"));
children.push(H2("4.1 How it works"));
children.push(...bullets([
  "File type is decided from the content (magic bytes / package layout), not the extension; legacy .doc/.ppt, password-protected and ZIP-bomb-sized files are rejected with safe messages.",
  "PDF: the text layer is used when it holds real text, otherwise the page is rendered at 300 DPI and OCR'd with Tesseract. Images on text pages are OCR'd as well. Annotations, form fields, link targets and document properties are extracted.",
  "OCR chain: orientation detection, deskew, upscaling, CLAHE contrast + denoise, ruled-table detection with cell-by-cell OCR, then full-page OCR; low-confidence pages are retried with other thresholds. Each OCR block carries its mean word confidence.",
  "DOCX: body in document order, tables, text boxes, images (OCR + alt text), charts, SmartArt, headers/footers of every section, footnotes, endnotes, comments, properties, plus a safety-net sweep for any text node no extractor used.",
  "PPTX: titles first, then shapes in visual order (XY-cut), groups, tables, pictures, charts, speaker notes, comments, hidden slides, master/layout text, properties, plus the sweep.",
  "Tables become one block per row with the header as context (\"Name: ... | Email: ...\"). Reading order on pages uses a recursive XY-cut.",
  "Nothing extracted is printed or logged; warnings carry a code, a location and a reason, never text.",
]));
children.push(H2("4.2 Results on the samples"));
children.push(table(["File", "Blocks", "Pages", "Characters", "Sources", "OCR blocks", "Mean / lowest OCR conf.", `Below ${pct(FILES[0].extraction.low_ocr_threshold)}`, "Hidden", "Table rows"],
  FILES.map((f) => { const x = f.extraction; return [f.filename, f.block_count, f.pages.length, x.characters.toLocaleString(), typeRows(x.sources), x.ocr_blocks,
    `${pct(x.mean_ocr)} / ${pct(x.lowest_ocr)}`, x.low_ocr_blocks, x.hidden_blocks, x.table_rows]; }),
  [1.5, 0.8, 0.7, 1, 1.5, 0.8, 1.3, 0.8, 0.7, 0.8]));
children.push(spacer());
children.push(table(["File", "Block kinds (count)"], FILES.map((f) => [f.filename, typeRows(f.extraction.kinds)]), [1, 4]));
children.push(spacer());
children.push(table(["File", "Extraction warnings by code"], FILES.map((f) => [f.filename, typeRows(warnCodes(f))]), [1, 4]));
children.push(spacer());
children.push(P("Warning codes: LOW_OCR_CONFIDENCE = OCR block below 0.6 mean confidence; SKIPPED_IMAGE = images not OCR'd (EMF/WMF, tiny, linked); PAGE_NO_TEXT = page produced no block; LOW_COVERAGE = scanned page with ink but few characters; UNCLAIMED_TEXT = text found only by the sweep; UNSUPPORTED_OBJECT = embedded OLE objects; EXTENSION_MISMATCH = content differs from the extension."));
for (const [name, label] of [["pdf", "sample.pdf"], ["docx", "sample.docx"], ["pptx", "sample.pptx"]]) {
  children.push(...shot(`${name}_extraction`, `Extraction view for ${label}`));
}

// 5. Detection
children.push(H1("5. Detection"));
children.push(H2("5.1 Detectors"));
children.push(table(["Detector", "Finds", "How"], [
  ["A: rules (regex.*)", "EMAIL, EMPLOYEE_ID, DIRECTOR_ID, VENDOR_ID, SSN, PAN, PASSPORT, US ADDRESS, CREDIT_CARD, DOB", "regular expressions; cards need a valid Luhn checksum; DOB needs a birth-date label nearby"],
  ["A: regex.last_digits", "CREDIT_CARD, ACCOUNT, SSN (last 4 digits)", "\"card ending 2218\", \"account ending in 0042\": the last digits still identify the number"],
  ["A: libphonenumber / regex.phone", "PHONE", "phonenumbers matcher with numbering-plan validation"],
  ["A: presidio", "PERSON, AADHAAR, PASSPORT (IN), IP", "Presidio + spaCy NER; Aadhaar checksum-validated; all-caps text also scanned title-cased"],
  ["B: gliner", "PERSON", "GLiNER small v2.1, threshold 0.5; address, organization and job-title labels act as sinks so they are not called people"],
  ["C: address_ner", "ADDRESS (Indian)", "TinyBERT fine-tuned on Indian addresses; components merged into one span, kept only with a PIN code or Indian place signal"],
  ["propagated", "PERSON repeats", "every further occurrence in the file of a multi-word name found elsewhere"],
], [1.5, 2.2, 3]));
children.push(spacer());
children.push(P("After the detectors, detect() cleans model spans: it ignores model names in OCR blocks the extraction flags as unreliable, cuts a name where it runs into an e-mail, phone or ID, splits run-together names, trims role/table words, keeps one-word names only when two detectors agree, drops model addresses that contain a date, and removes exact duplicates."));
children.push(H2("5.2 Results on the samples"));
children.push(table(["File", "Detections", "By type", "By detector"],
  FILES.map((f) => [f.filename, f.entities.length, typeRows(f.detected_types), typeRows(f.detectors)]), [1.1, 0.9, 2.2, 2.6]));
children.push(...shot("findings", "Findings tab: every detection across the three files, searchable and filterable"));
children.push(...shot("finding_detail", "one detection expanded: type, placeholder, confidence, detector, block, page, offsets (no value)"));
for (const [name, label] of [["pdf", "sample.pdf"], ["docx", "sample.docx"], ["pptx", "sample.pptx"]]) {
  children.push(...shot(`${name}_detected`, `Detected PII for ${label}`));
}

// 6. Redaction
children.push(H1("6. Redaction and traceability"));
children.push(H2("6.1 How it works"));
children.push(...bullets([
  "Every detected span is replaced by a placeholder `[TYPE_n]`, numbered per type and per file. The same value in the same file always gets the same placeholder (PlaceholderManager keeps only a salted hash of the value).",
  "Overlapping detections are grouped. The winner (higher confidence, then longer span, then earlier start) gives the label; the replaced span is the union of the group, so no part of any detected value can survive.",
  "The output is built left to right from slices of the original text; offsets are never applied to the changed text.",
  "verify_redaction then walks the original and the output in parallel: text outside replacements must be identical, every placeholder must be in place and every detected span must lie inside a replacement. If anything fails, the block raises RedactionVerificationError and nothing is returned (fail closed).",
  "Invalid detector output (bad offsets, value not matching the text, unknown block, bad type or confidence) raises instead of being skipped, because a skipped entity is PII that would reach the LLM.",
  "Each replacement produces a TraceRecord (file, block, location, offsets, type, confidence, detector, placeholder, merged_entities) with no value field at all; build_report turns them into the exposure report.",
  "The application adds a residual check: if a detected value still appears anywhere in the redacted text of the file (for example an undetected repeat in another block), the file is not cleared for the LLM.",
]));
children.push(H2("6.2 Results on the samples"));
children.push(table(["File", "Detections", "Redactions", "Merged away", "Placeholders", "Redactions by type", "Verified blocks", "Residual leaks"],
  FILES.map((f) => [f.filename, f.entities.length, f.records.length, f.entities.length - f.records.length, f.placeholders.length,
    typeRows(f.report.summary.by_pii_type), f.status === "failed" ? "-" : `${f.block_count}/${f.block_count}`, f.leaks.length]),
  [1.2, 0.9, 0.9, 0.8, 0.9, 2.2, 0.9, 0.7]));
children.push(spacer());
children.push(P("\"Merged away\" is the number of detections that overlapped another detection and were folded into a single replacement. \"Verified blocks\" counts blocks that passed verify_redaction; redact_document returns output only if every block passes."));
for (const [name, label] of [["pdf", "sample.pdf"], ["docx", "sample.docx"], ["pptx", "sample.pptx"]]) {
  children.push(...shot(`${name}_redacted`, `redacted text of ${label}, placeholders highlighted`));
  children.push(...shot(`${name}_trace`, `traceability for ${label}: verification, placeholder index, trace records`));
}

// 7. Evaluation
children.push(H1("7. Evaluation metrics"));
children.push(H2("7.1 Method"));
children.push(...bullets([
  `Ground truth: ${ov.support} labelled PII occurrences (${META.gt_source}). ${META.gt_note}`,
  "A labelled value is a true positive only if it was detected with the right type AND it no longer appears in the redacted text. A detected value that is still visible counts as leaked (a miss).",
  "Matching is by file and value: letters and digits, lower-cased, at least 50% overlap; one OCR-misread letter is tolerated for values without digits. Offsets are not compared because the ground truth has no block index.",
  "Overlapping predictions are merged the way redaction merges them before scoring. A further occurrence of a labelled value is counted as a repeat, not as a false positive.",
  "Precision = TP / (TP + FP), Recall = TP / (TP + FN), F1 = 2PR / (P + R), Accuracy = TP / (TP + FP + FN).",
]));
children.push(H2("7.2 Overall"));
children.push(table(["Precision", "Recall", "F1", "Accuracy", "TP", "FP", "FN", "Missed", "Leaked", "Repeats"],
  [[f3(ov.precision), f3(ov.recall), f3(ov.f1), f3(ov.accuracy), ov.tp, ov.fp, ov.fn, EVAL.counts.missed, EVAL.counts.leaked, EVAL.counts.repeats]],
  [1, 1, 1, 1, 0.8, 0.8, 0.8, 0.9, 0.9, 0.9]));
children.push(H2("7.3 Per file"));
children.push(table(["File", "Labelled", "TP", "FP", "FN", "Precision", "Recall", "F1", "Leaked"],
  EVAL.files.map((x) => [x.file, x.support, x.tp, x.fp, x.fn, f3(x.precision), f3(x.recall), f3(x.f1), x.leaked]),
  [1.5, 0.9, 0.7, 0.7, 0.7, 0.9, 0.9, 0.8, 0.8]));
children.push(H2("7.4 Per PII type"));
children.push(table(["Type", "Labelled", "TP", "FP", "FN", "Precision", "Recall", "F1"],
  EVAL.per_type.map((x) => [x.type, x.support, x.tp, x.fp, x.fn, f3(x.precision), f3(x.recall), f3(x.f1)]),
  [1.6, 0.9, 0.7, 0.7, 0.7, 0.9, 0.9, 0.8]));
children.push(spacer());
children.push(P("A type with 0 labelled rows and only false positives (precision and recall 0) is a type the ground truth does not label in these documents."));
children.push(H2("7.5 Diagnosis (no values)"));
children.push(P("Output of evaluation.diagnose: why labelled values were missed and the format (shape) of misses and false positives, with letters shown as A/a and digits as 9."));
EVAL.diagnosis.split("\n").forEach((line) => children.push(new Paragraph({ spacing: { after: 0 }, children: [new TextRun({ text: line, font: "Consolas", size: 16 })] })));
children.push(...shot("evaluation", "Evaluation tab: overall metrics, per file and per type"));
children.push(...shot("exports", "Exports tab"));

// 8. Limitations
children.push(H1("8. Limitations"));
children.push(H2("8.1 Observed in this run"));
children.push(...bullets(observed));
children.push(H2("8.2 Design limitations"));
children.push(...bullets([
  "Extraction: borderless tables inside images lose their cell structure; EMF/WMF images and embedded OLE objects are reported but not read; handwriting and poor scans depend on Tesseract; DOCX has no fixed page numbers, so DOCX locations are section/paragraph positions.",
  "Detection: rule formats do not cover every ID format; DOB needs a birth-date label; phone validation depends on numbering-plan metadata; person names come from statistical models and can be missed or over-detected; the Indian address model keeps only spans with a PIN code or Indian place name, so foreign addresses rely on the US address rule.",
  "Redaction: placeholders match values exactly (case- and whitespace-sensitive), so \"Rahul Sharma\" and \"RAHUL SHARMA\" get different placeholders. Redaction removes what detection found; it cannot remove PII that detection missed.",
  "Residual check: compares detected values only; it cannot find PII that no detector found anywhere in the file.",
  "Evaluation: the ground truth has no block index, so matching is by value; values that extraction never produced (image-only content) count as misses of the whole pipeline.",
  "Application: results are kept in server memory (lost on restart, max 20 runs); files are processed one at a time; the first file is slow while the models load; there is no login, so the server should run on a trusted machine only (it binds to 127.0.0.1).",
]));

// 9. Reproduce
children.push(H1("9. How to run and reproduce"));
children.push(...bullets([
  "Install: `pip install -r requirements.txt` (repo root) and Tesseract OCR; the app also needs `src/pii_pipeline/app/backend/requirements.txt` (FastAPI, uvicorn, python-multipart) and Node.js to build the UI once.",
  "Start: `src/pii_pipeline/app/start.bat` (Windows) or `start.sh`, then open http://localhost:8000.",
  "Upload sample.pdf, sample.docx and sample.pptx, press Run Analysis, then on the Evaluation tab upload `data/outputs/ground_truth_samples.csv`.",
  "Same numbers from the command line: `python -m pii_pipeline.evaluation.evaluate_redaction --gt src/pii_pipeline/evaluation/ground_truth_cadence_updated_with_addresses.csv --docs <the three Cadence files>`.",
  "Tests: `python -m pytest` (includes tests/test_app_backend.py for the web workflow layer).",
]));
children.push(P("Files produced by this run (all in data/outputs, git-ignored): app_results/*.json (API responses, no raw values), app_results/evaluation.json, app_results/exposure_report.json, app_results/findings.csv, app_results/redacted_for_llm.zip, screenshots/*.png, ground_truth_samples.csv and this report."));

const doc = new Document({
  creator: "PII Shield team",
  title: "PII Shield - pipeline report",
  styles: {
    default: { document: { run: { font: FONT, size: 22 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 34, bold: true, color: ACCENT, font: FONT }, paragraph: { spacing: { before: 240, after: 160 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 27, bold: true, color: "1F2937", font: FONT }, paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 23, bold: true, font: FONT }, paragraph: { spacing: { before: 180, after: 80 }, outlineLevel: 2 } },
    ],
  },
  numbering: { config: [{ reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
    style: { paragraph: { indent: { left: 540, hanging: 270 } } } }] }] },
  features: { updateFields: true },
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1440, bottom: 1440, left: 1440, right: 1440 } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "PII Shield report - page ", size: 16, color: "777777" }), new TextRun({ children: [PageNumber.CURRENT], size: 16, color: "777777" })] })] }) },
    children,
  }],
});
Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(path.join(OUT, "PII_Shield_Report.docx"), buf);
  console.log("written", buf.length);
});
