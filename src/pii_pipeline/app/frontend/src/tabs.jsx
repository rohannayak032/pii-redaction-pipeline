import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import {
  Alert, BarChart, ClearedBadge, DataTable, Expander, Metric, MultiSelect,
  SearchInput, Select, StatusBadge, Tabs, pct,
} from "./ui";

const PLACEHOLDER_RE = /\[[A-Z][A-Z0-9_]*_\d+\]/g;

const sumValues = (o) => Object.values(o || {}).reduce((a, b) => a + b, 0);
const conf = (c) => (c != null ? `${(c * 100).toFixed(0)}%` : "-");

function addCounts(target, counts) {
  Object.entries(counts || {}).forEach(([k, v]) => { target[k] = (target[k] || 0) + v; });
  return target;
}

// ─── Redacted text renderer with highlighted placeholders ─────────────────────
function HighlightedText({ text }) {
  const parts = [];
  let pos = 0;
  PLACEHOLDER_RE.lastIndex = 0;
  let m;
  while ((m = PLACEHOLDER_RE.exec(text))) {
    if (m.index > pos) parts.push(text.slice(pos, m.index));
    parts.push(<mark key={m.index} className="placeholder-mark" title="PII placeholder">{m[0]}</mark>);
    pos = m.index + m[0].length;
  }
  parts.push(text.slice(pos));
  return <>{parts}</>;
}

// ─── Expandable detail panel for one detection (Entity.public_info + location) ─
function EntityDetail({ entity }) {
  const rows = [
    ["PII Type", entity.pii_type],
    ["Placeholder", <code key="ph">{entity.placeholder || "-"}</code>],
    ["Confidence", entity.confidence != null ? `${(entity.confidence * 100).toFixed(1)}%` : "-"],
    ["Detector", entity.detector],
    ["Source File", entity.file],
    ["Block index", entity.block_index],
    ["Page / Slide", entity.page ?? "-"],
    ["Location", entity.location || "-"],
    ["Char start", entity.start],
    ["Char end", entity.end],
  ];
  return (
    <div className="entity-detail">
      <div className="entity-detail-grid">
        {rows.map(([label, val]) => (
          <div className="entity-detail-row" key={label}>
            <span className="entity-detail-label">{label}</span>
            <span className="entity-detail-val">{val ?? "-"}</span>
          </div>
        ))}
      </div>
      <p className="entity-detail-note">
        Offsets refer to the original block text. The original value never leaves the server.
      </p>
    </div>
  );
}

function ExtractionWarnings({ warnings }) {
  if (!warnings.length) return null;
  const cols = [
    { key: "code", label: "Code", render: (w) => <code>{w.code}</code> },
    { key: "location", label: "Location", className: "wrap" },
    { key: "detail", label: "Detail", className: "wrap" },
  ];
  return <DataTable columns={cols} rows={warnings} />;
}

// ─────────────────────────────────────────────────────────────────────────────
// OVERVIEW TAB
// ─────────────────────────────────────────────────────────────────────────────
export function OverviewTab({ results }) {
  const byType = useMemo(() => results.reduce((t, r) => addCounts(t, r.report.summary.by_pii_type), {}), [results]);
  const byDetector = useMemo(() => results.reduce((t, r) => addCounts(t, r.detectors), {}), [results]);

  const cols = [
    { key: "filename", label: "File", className: "wrap", render: (r) => <span title={r.filename}>{r.filename}</span> },
    { key: "file_type", label: "Type", render: (r) => r.file_type?.toUpperCase() || "-" },
    { key: "status", label: "Status", render: (r) => <StatusBadge status={r.status} /> },
    { key: "pages", label: "Pages", render: (r) => r.pages.length, className: "num" },
    { key: "block_count", label: "Blocks", className: "num" },
    { key: "det", label: "Detections", render: (r) => r.entities.length, className: "num" },
    { key: "red", label: "Redactions", render: (r) => r.records.length, className: "num" },
    { key: "cats", label: "Redactions by type", className: "wrap",
      render: (r) => Object.entries(r.report.summary.by_pii_type).map(([k, v]) => `${k} ×${v}`).join(", ") || "—" },
    { key: "llm_ready", label: "LLM Ready", render: (r) => <ClearedBadge ready={r.llm_ready} /> },
    { key: "time", label: "Time (s)", className: "num", render: (r) => sumValues(r.timings).toFixed(2) },
  ];

  const expandRow = (r) => {
    if (r.status === "failed") {
      return <Alert kind="error"><b>{r.failed_stage} failed:</b> {r.error}</Alert>;
    }
    const x = r.extraction;
    return (
      <div style={{ padding: "12px 4px" }}>
        {r.leaks.map((l, i) => <Alert key={i} kind="error">{l}</Alert>)}
        {!x.warnings.length && !r.leaks.length && <Alert kind="success">No extraction warnings or residual leaks for this file.</Alert>}
        <ExtractionWarnings warnings={x.warnings} />
        <div className="metrics-grid metrics-grid--compact" style={{ marginTop: 12 }}>
          <Metric label="Characters" value={x.characters.toLocaleString()} />
          <Metric label="OCR blocks" value={x.ocr_blocks} />
          {x.lowest_ocr != null && <Metric label="Lowest OCR conf." value={pct(x.lowest_ocr)} />}
          <Metric label="Hidden blocks" value={x.hidden_blocks} />
          <Metric label="Placeholders" value={r.placeholders.length} />
        </div>
      </div>
    );
  };

  return (
    <div className="panel">
      <DataTable columns={cols} rows={results} expandRow={expandRow} empty="No results yet." />
      {Object.keys(byType).length > 0 && (
        <div className="chart-section">
          <h4 className="chart-title">Redactions by PII type</h4>
          <BarChart data={byType} />
        </div>
      )}
      {Object.keys(byDetector).length > 0 && (
        <div className="chart-section">
          <h4 className="chart-title">Detections by detector</h4>
          <BarChart data={byDetector} />
        </div>
      )}
      {!results.some((r) => r.entities.length > 0) && results.some((r) => r.status !== "failed") && (
        <Alert kind="success">No PII detected in any processed file.</Alert>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// FINDINGS TAB — searchable, filterable cross-file detections
// ─────────────────────────────────────────────────────────────────────────────
function DetectionsTable({ rows, showFile }) {
  const [search, setSearch] = useState("");
  const [types, setTypes] = useState([]);
  const [detectors, setDetectors] = useState([]);
  const [files, setFiles] = useState([]);
  const [pages, setPages] = useState([]);

  const options = (key) => [...new Set(rows.map((e) => e[key]))].filter((v) => v != null).sort((a, b) => (a > b ? 1 : -1));
  const q = search.toLowerCase();
  const filtered = rows.filter((e) =>
    (!types.length || types.includes(e.pii_type)) &&
    (!detectors.length || detectors.includes(e.detector)) &&
    (!files.length || files.includes(e.file)) &&
    (!pages.length || pages.includes(e.page)) &&
    (!q || [e.pii_type, e.placeholder, e.file, e.location, e.detector].some((v) => (v || "").toLowerCase().includes(q))));

  const cols = [
    { key: "n", label: "#", className: "num" },
    { key: "pii_type", label: "PII Type" },
    { key: "placeholder", label: "Placeholder", className: "nowrap", render: (e) => <code>{e.placeholder || "-"}</code> },
    { key: "confidence", label: "Confidence", className: "num", render: (e) => conf(e.confidence) },
    { key: "detector", label: "Detector" },
    ...(showFile ? [{ key: "file", label: "File", className: "wrap" }] : []),
    { key: "page", label: "Page", className: "num" },
    { key: "location", label: "Location", className: "wrap" },
  ];

  return (
    <>
      <div className="findings-toolbar">
        <SearchInput value={search} onChange={setSearch} placeholder="Search type, placeholder, detector, location…" />
        <div className="findings-filters">
          <MultiSelect label="PII Type" options={options("pii_type")} value={types} onChange={setTypes} />
          <MultiSelect label="Detector" options={options("detector")} value={detectors} onChange={setDetectors} />
          {showFile
            ? <MultiSelect label="File" options={options("file")} value={files} onChange={setFiles} />
            : <MultiSelect label="Page" options={options("page")} value={pages} onChange={setPages} />}
        </div>
      </div>
      <DataTable columns={cols} rows={filtered} expandRow={(e) => <EntityDetail entity={e} />}
        empty="No detections match the current filters." />
      <p className="findings-footer">
        {filtered.length} of {rows.length} detections shown · values stay on the server
      </p>
    </>
  );
}

export function FindingsTab({ results }) {
  const all = useMemo(() => results.flatMap((r) => r.entities), [results]);
  if (!all.length) {
    return <div className="panel"><Alert kind="success">No PII detected across the processed files.</Alert></div>;
  }
  return <div className="panel"><DetectionsTable rows={all} showFile /></div>;
}

// ─────────────────────────────────────────────────────────────────────────────
// FILE DETAILS TAB
// ─────────────────────────────────────────────────────────────────────────────
function RedactedPane({ r, runId }) {
  const pages = r.pages.length ? r.pages : [null];
  const [page, setPage] = useState(pages[0]);
  const [copied, setCopied] = useState(false);

  useEffect(() => setPage(pages[0]), [r]);   // eslint-disable-line react-hooks/exhaustive-deps

  const blocks = page == null ? r.redacted : r.redacted.filter((b) => b.page === page);
  const fullText = blocks.map((b) => b.text).join("\n");

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(fullText);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard not available
    }
  };

  return (
    <div className="panel">
      <div className="redacted-toolbar">
        {pages.length > 1 && (
          <div style={{ minWidth: 200 }}>
            <Select
              label="Page / slide"
              value={page}
              onChange={(v) => setPage(Number(v))}
              options={pages.map((p) => ({ value: p, label: `Page / Slide ${p}` }))}
            />
          </div>
        )}
        <div className="redacted-actions">
          <button className="btn btn--sm" onClick={handleCopy} disabled={!fullText}>
            {copied ? "Copied" : "Copy Redacted Text"}
          </button>
          {r.llm_ready && (
            <a className="btn btn--sm" href={`/api/runs/${runId}/files/${r.index}/redacted.txt`} download
              title="Download this file's redacted text">
              Download .txt
            </a>
          )}
        </div>
      </div>

      <div className="redacted-preview">
        {blocks.length === 0 && <span className="muted">No redacted content for this page.</span>}
        {blocks.map((b) => (
          <div key={b.block_index} className="redacted-block">
            <div className="redacted-location">{b.location}</div>
            <HighlightedText text={b.text} />
          </div>
        ))}
      </div>
      <p className="findings-footer">
        Output of redaction.redact_document: the only content intended for the LLM.
      </p>
    </div>
  );
}

function ExtractionPane({ r }) {
  const x = r.extraction;
  const countCols = (label) => [
    { key: "k", label },
    { key: "v", label: "Blocks", className: "num" },
  ];
  const rows = (o) => Object.entries(o).map(([k, v]) => ({ k, v }));
  return (
    <div className="panel">
      <div className="metrics-grid metrics-grid--compact">
        <Metric label="Blocks" value={r.block_count} />
        <Metric label="Pages / slides" value={r.pages.length} />
        <Metric label="Characters" value={x.characters.toLocaleString()} />
        <Metric label="Table rows" value={x.table_rows} />
        <Metric label="Hidden blocks" value={x.hidden_blocks} help="Hidden slides, hidden text and similar content" />
      </div>
      <div className="metrics-grid metrics-grid--compact">
        <Metric label="OCR blocks" value={x.ocr_blocks} />
        <Metric label="Mean OCR conf." value={pct(x.mean_ocr)} />
        <Metric label="Lowest OCR conf." value={pct(x.lowest_ocr)} />
        <Metric label={`Below ${pct(x.low_ocr_threshold)}`} value={x.low_ocr_blocks}
          help="OCR blocks the extraction module flags as unreliable" />
      </div>
      <div className="trace-section">
        <h4 className="section-label">Blocks by source</h4>
        <DataTable columns={countCols("Source")} rows={rows(x.sources)} noMax />
      </div>
      <div className="trace-section">
        <h4 className="section-label">Blocks by kind</h4>
        <DataTable columns={countCols("Kind")} rows={rows(x.kinds)} noMax />
      </div>
      <div className="trace-section">
        <h4 className="section-label">Extraction warnings</h4>
        {x.warnings.length
          ? <ExtractionWarnings warnings={x.warnings} />
          : <Alert kind="success">The extraction module raised no warnings for this file.</Alert>}
      </div>
    </div>
  );
}

function TracePane({ r }) {
  const plCols = [
    { key: "placeholder", label: "Placeholder", render: (x) => <code>{x.placeholder}</code> },
    { key: "pii_type", label: "PII Type" },
    { key: "occurrences", label: "Replacements", className: "num" },
    { key: "detections", label: "Detections merged", className: "num" },
    { key: "pages", label: "Pages / Slides", className: "wrap", render: (x) => x.pages.join(", ") || "-" },
  ];
  const recCols = [
    { key: "placeholder", label: "Placeholder", render: (x) => <code>{x.placeholder}</code> },
    { key: "pii_type", label: "PII Type" },
    { key: "page", label: "Page", className: "num" },
    { key: "location", label: "Location", className: "wrap" },
    { key: "start", label: "Start", className: "num" },
    { key: "end", label: "End", className: "num" },
    { key: "confidence", label: "Confidence", className: "num", render: (x) => conf(x.confidence) },
    { key: "detector", label: "Winning detector" },
    { key: "merged_entities", label: "Merged", className: "num" },
  ];
  const detCols = [
    { key: "k", label: "Detector" },
    { key: "v", label: "Detections", className: "num" },
  ];

  return (
    <div className="panel">
      <div className="trace-section">
        <h4 className="section-label">Verification</h4>
        <Alert kind="success">
          redaction.verify_redaction passed for all {r.block_count} blocks: text outside the replaced spans is unchanged,
          every placeholder is in place, and every detected span is covered.
        </Alert>
        {r.leaks.length > 0
          ? r.leaks.map((l, i) => <Alert key={i} kind="error">{l}</Alert>)
          : <Alert kind="success">Residual check: no detected value appears anywhere in the redacted text.</Alert>}
      </div>

      <div className="trace-section">
        <h4 className="section-label">Redactions by PII type</h4>
        <div className="category-grid">
          {Object.entries(r.report.summary.by_pii_type).map(([type, count]) => (
            <div key={type} className="category-card">
              <span className="category-type">{type}</span>
              <span className="category-count">{count}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="trace-section">
        <h4 className="section-label">Detections by detector</h4>
        <DataTable columns={detCols} rows={Object.entries(r.detectors).map(([k, v]) => ({ k, v }))} noMax />
      </div>

      {r.placeholders.length > 0 && (
        <div className="trace-section">
          <h4 className="section-label">Placeholder index</h4>
          <p className="trace-note">
            The same value gets the same placeholder throughout the file (PlaceholderManager). A placeholder cannot be
            reversed without the original value.
          </p>
          <DataTable columns={plCols} rows={r.placeholders} />
        </div>
      )}

      {r.records.length > 0 && (
        <div className="trace-section">
          <h4 className="section-label">Trace records <span className="muted">(one per replaced span)</span></h4>
          <DataTable columns={recCols} rows={r.records} />
        </div>
      )}

      <Expander title="Exposure report (redaction.build_report: type, location, confidence; no raw values)">
        <pre className="code-block">{JSON.stringify(r.report, null, 2)}</pre>
      </Expander>
    </div>
  );
}

export function FileTab({ runId, results }) {
  const [pick, setPick] = useState(0);
  const [inner, setInner] = useState("Detected PII");
  const idx = Math.min(pick, results.length - 1);
  const r = results[idx];
  const stageCols = [
    { key: "k", label: "Stage" },
    { key: "v", label: "Seconds", className: "num", render: (x) => x.v.toFixed(3) },
  ];

  return (
    <div className="panel">
      <div style={{ maxWidth: 520 }}>
        <Select
          label="Select file"
          value={idx}
          onChange={(v) => { setPick(Number(v)); setInner("Detected PII"); }}
          options={results.map((x, i) => ({ value: i, label: `${i + 1}. ${x.filename}` }))}
        />
      </div>

      {r.status === "failed" ? (
        <Alert kind="error"><strong>{r.failed_stage} failed</strong> — {r.error}</Alert>
      ) : (
        <>
          {r.llm_ready
            ? <Alert kind="success">Cleared for LLM — redaction was verified and no detected value remains in the output.</Alert>
            : <Alert kind="error">Not cleared for LLM — detected values remain in the redacted text. Do not forward it.</Alert>}

          <div className="metrics-grid metrics-grid--compact">
            <Metric label="Blocks" value={r.block_count} />
            <Metric label="Detections" value={r.entities.length} accent={r.entities.length > 0} />
            <Metric label="Redactions" value={r.records.length} />
            <Metric label="Placeholders" value={r.placeholders.length} />
            <Metric label="Residual leaks" value={r.leaks.length} />
          </div>

          <Tabs
            inner
            tabs={["Detected PII", "Redacted Text", "Extraction", "Traceability & Report"]}
            value={inner}
            onChange={setInner}
          />

          {inner === "Detected PII" && (
            <div className="panel">
              {r.entities.length
                ? <DetectionsTable key={r.filename} rows={r.entities} />
                : <Alert kind="success">No PII detected in this file.</Alert>}
            </div>
          )}
          {inner === "Redacted Text" && <RedactedPane r={r} runId={runId} />}
          {inner === "Extraction" && <ExtractionPane r={r} />}
          {inner === "Traceability & Report" && <TracePane r={r} />}
        </>
      )}

      <Expander title="Stage timings">
        <DataTable columns={stageCols} rows={Object.entries(r.timings).map(([k, v]) => ({ k, v }))} noMax />
      </Expander>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// EVALUATION TAB — evaluation.evaluate_redaction on this run
// ─────────────────────────────────────────────────────────────────────────────
export function EvalTab({ runId, results, cfg }) {
  const [gt, setGt] = useState(null);
  const [requireType, setRequireType] = useState(true);
  const [exact, setExact] = useState(false);
  const [out, setOut] = useState(null);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!gt) { setOut(null); setErr(""); return; }
    let live = true;
    setLoading(true);
    api.evaluate(runId, gt, requireType, exact)
      .then((d) => { if (live) { setOut(d); setErr(""); setLoading(false); } })
      .catch((e) => { if (live) { setOut(null); setErr(e.message); setLoading(false); } });
    return () => { live = false; };
  }, [gt, requireType, exact, runId, results]);

  const counts = ["tp", "fp", "fn"];
  const metricCols = [...counts, "precision", "recall", "f1", "accuracy"].map((k) => ({
    key: k, label: k.length <= 2 ? k.toUpperCase() : k[0].toUpperCase() + k.slice(1), className: "num",
    render: (x) => (counts.includes(k) ? x[k] : x[k].toFixed(3)),
  }));
  const fcols = [
    { key: "file", label: "File", className: "wrap" },
    { key: "support", label: "Labelled", className: "num" },
    ...metricCols,
    { key: "leaked", label: "Leaked", className: "num" },
    { key: "repeats", label: "Repeats", className: "num" },
  ];
  const tcols = [{ key: "type", label: "Type" }, { key: "support", label: "Labelled", className: "num" }, ...metricCols];

  return (
    <div className="panel">
      <div className="eval-intro">
        <p>
          Score this run with the team's evaluation module (<code>evaluate_redaction</code>) against a
          ground-truth CSV with columns {cfg.gt_columns.map((c, i) => <span key={c}>{i ? ", " : ""}<code>{c}</code></span>)}.
          A labelled value counts as found only if it was detected with the right type <em>and</em> is gone from the redacted text.
        </p>
        <p className="findings-note">
          Only metrics and counts come back from the server; missed and false-positive values are never sent to the browser.
        </p>
      </div>

      <div className="eval-controls">
        <label className="btn btn--ghost" style={{ cursor: "pointer" }}>
          Choose ground truth CSV
          <input type="file" accept=".csv" hidden onChange={(e) => setGt(e.target.files[0] || null)} />
        </label>
        <span className="muted small">{gt ? gt.name : "No file selected"}</span>
        {gt && <button className="icon-btn" title="Remove" onClick={() => setGt(null)}>✕</button>}
      </div>

      <div className="eval-options">
        <label className="toggle-check">
          <input type="checkbox" checked={requireType} onChange={(e) => setRequireType(e.target.checked)} />
          Require the PII type to match
        </label>
        <label className="toggle-check">
          <input type="checkbox" checked={exact} onChange={(e) => setExact(e.target.checked)} />
          Exact value match (otherwise ≥ 50% overlap of letters and digits)
        </label>
      </div>

      {loading && <Alert kind="info">Scoring…</Alert>}
      {err && <Alert kind="error">{err}</Alert>}

      {out && out.files.length === 0 && (
        <Alert kind="warning">No file in the ground truth matches the processed files ({out.unlabelled.join(", ")}).</Alert>
      )}
      {out && out.files.length > 0 && (
        <>
          <div className="metrics-grid metrics-grid--compact">
            <Metric label="Precision" value={pct(out.overall.precision)} help="TP / (TP + FP)" />
            <Metric label="Recall" value={pct(out.overall.recall)} help="TP / (TP + FN)" />
            <Metric label="F1" value={pct(out.overall.f1)} />
            <Metric label="Accuracy" value={pct(out.overall.accuracy)} help="TP / (TP + FP + FN)" />
          </div>
          <div className="metrics-grid metrics-grid--compact">
            <Metric label="Labelled PII" value={out.overall.support} />
            <Metric label="Missed" value={out.counts.missed} help="Labelled values not detected with the right type" />
            <Metric label="Leaked" value={out.counts.leaked} help="Detected, but still visible in the redacted text" />
            <Metric label="False positives" value={out.counts.false_positives} />
            <Metric label="Repeats (not FP)" value={out.counts.repeats} help="Further occurrences of a labelled value" />
          </div>
          {out.unlabelled.length > 0 && (
            <Alert kind="warning">Not scored (no ground-truth rows): {out.unlabelled.join(", ")}</Alert>
          )}
          {out.warnings.map((w, i) => <Alert key={i} kind="info">{w}</Alert>)}

          <h4 className="section-label">Per file</h4>
          <DataTable columns={fcols} rows={out.files} noMax />
          <h4 className="section-label" style={{ marginTop: 24 }}>Per PII type</h4>
          <DataTable columns={tcols} rows={out.per_type} noMax />
          <Expander title="Diagnosis (miss causes and value shapes, no values)">
            <pre className="code-block">{out.diagnosis}</pre>
          </Expander>
        </>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// EXPORTS TAB
// ─────────────────────────────────────────────────────────────────────────────
export function ExportsTab({ runId, results }) {
  const ok = results.filter((r) => r.status !== "failed" && r.index >= 0);
  const [one, setOne] = useState(0);
  const sel = ok[Math.min(one, ok.length - 1)];
  const hasFindings = ok.some((r) => r.records.length > 0);
  const cleared = results.some((r) => r.llm_ready);

  const link = (path, disabled) =>
    disabled
      ? { className: "btn btn--ghost btn--disabled", "aria-disabled": true }
      : { className: "btn btn--ghost", href: `/api/runs/${runId}/${path}` };

  return (
    <div className="panel">
      <Alert kind="info">
        All exports contain <strong>no raw PII values</strong>: only placeholders, types, offsets and metadata.
      </Alert>

      <div className="exports-section">
        <h4 className="section-label">Bulk Exports</h4>
        <div className="dl-row">
          <a {...link("report.json", false)}>Export Report (JSON)</a>
          <a {...link("findings.csv", !hasFindings)}>Export Trace Records (CSV)</a>
          <a {...link("redacted.zip", !cleared)}>Download Redacted (ZIP)</a>
        </div>
        {!cleared && <p className="findings-note">ZIP export disabled — no files are cleared for LLM.</p>}
      </div>

      {ok.length > 0 && (
        <div className="exports-section">
          <h4 className="section-label">Single File Download</h4>
          <div style={{ maxWidth: 480, marginBottom: 12 }}>
            <Select
              label="Select file"
              value={Math.min(one, ok.length - 1)}
              onChange={(v) => setOne(Number(v))}
              options={ok.map((r, i) => ({ value: i, label: r.filename }))}
            />
          </div>
          <div className="dl-row">
            <a {...link(`files/${sel.index}/redacted.txt`, !sel.llm_ready)}>Download Redacted .txt</a>
          </div>
          {!sel.llm_ready && (
            <p className="findings-note">Disabled: this file is not cleared for LLM (residual leaks detected).</p>
          )}
        </div>
      )}
    </div>
  );
}
