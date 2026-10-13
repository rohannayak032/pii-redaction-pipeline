import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import {
  Alert, BarChart, DataTable, Expander, Metric, MultiSelect, Select, SeverityBadge, StatusBadge, Tabs, pct,
} from "./ui";

const PLACEHOLDER_RE = /\[[A-Z][A-Z_]*_\d+\]/g;

function Highlighted({ text }) {
  const parts = [];
  let pos = 0, m;
  PLACEHOLDER_RE.lastIndex = 0;
  while ((m = PLACEHOLDER_RE.exec(text))) {
    parts.push(text.slice(pos, m.index));
    parts.push(<mark key={m.index}>{m[0]}</mark>);
    pos = m.index + m[0].length;
  }
  parts.push(text.slice(pos));
  return <>{parts}</>;
}

// =============================================================== Overview
export function OverviewTab({ results }) {
  const totals = useMemo(() => {
    const t = {};
    results.forEach((r) => Object.entries(r.categories).forEach(([k, v]) => { t[k] = (t[k] || 0) + v; }));
    return t;
  }, [results]);
  const rows = results.map((r) => ({
    ...r,
    cats: Object.entries(r.categories).map(([k, v]) => `${k}×${v}`).join(", ") || "-",
    time: Math.round(Object.values(r.timings).reduce((a, b) => a + b, 0) * 100) / 100,
    issue: r.error || (r.warnings.length ? r.warnings.join("; ").slice(0, 140) : ""),
  }));
  const cols = [
    { key: "filename", label: "File", className: "wrap" },
    { key: "file_type", label: "Type", render: (r) => r.file_type || "-" },
    { key: "status", label: "Status", render: (r) => <StatusBadge status={r.status} /> },
    { key: "risk", label: "AI-exposure risk" },
    { key: "pages", label: "Pages/Slides", render: (r) => r.pages.length, className: "num" },
    { key: "block_count", label: "Blocks", className: "num" },
    { key: "pii", label: "PII found", render: (r) => r.entities.length, className: "num" },
    { key: "cats", label: "Categories", className: "wrap" },
    { key: "cleared", label: "Cleared for LLM", render: (r) => (r.llm_ready ? "Yes" : "No") },
    { key: "time", label: "Time (s)", className: "num" },
    { key: "issue", label: "Issue", className: "wrap" },
  ];
  return (
    <div className="panel">
      <DataTable columns={cols} rows={rows} />
      {Object.keys(totals).length ? (
        <>
          <p className="caption" style={{ marginTop: 22 }}>PII by category (all files)</p>
          <BarChart data={totals} />
        </>
      ) : (
        <Alert kind="success">No PII detected in the processed files.</Alert>
      )}
    </div>
  );
}

// =============================================================== File details
const STAGE_HINT = {
  validation: "Check the file type/size or re-export the document.",
  extraction: "The file may be encrypted, corrupt, or scanned - needs OCR in the extraction module.",
  detection: "The detection module raised an error - see the log below.",
  redaction: "The redaction module raised an error - see the log below.",
};

function EntitiesPane({ r, pick }) {
  const [cats, setCats] = useState([]);
  const [pgs, setPgs] = useState([]);
  const [sev, setSev] = useState([]);
  useEffect(() => { setCats([]); setPgs([]); setSev([]); }, [pick]);
  const all = r.entities;
  const view = all.filter((e) => (!cats.length || cats.includes(e.entity_type)) &&
    (!pgs.length || pgs.includes(e.page)) && (!sev.length || sev.includes(e.severity)));
  const cols = [
    { key: "n", label: "#", className: "num" },
    { key: "entity_type", label: "Type" },
    { key: "severity", label: "Severity", render: (e) => <SeverityBadge s={e.severity} /> },
    { key: "page", label: "Page/Slide", className: "num" },
    { key: "location", label: "Location", className: "wrap" },
    { key: "block", label: "Block", className: "num" },
    { key: "start", label: "Start", className: "num" },
    { key: "end", label: "End", className: "num" },
    { key: "confidence", label: "Confidence", className: "num" },
    { key: "detector", label: "Detector" },
    { key: "placeholder", label: "Placeholder", className: "nowrap" },
  ];
  return (
    <div className="panel">
      {all.length === 0 ? (
        <Alert kind="info">No PII found in this file.</Alert>
      ) : (
        <>
          <div className="grid3">
            <MultiSelect label="Type" options={[...new Set(all.map((e) => e.entity_type))].sort()} value={cats} onChange={setCats} />
            <MultiSelect label="Page/Slide" options={[...new Set(all.map((e) => e.page))].sort((a, b) => a - b)} value={pgs} onChange={setPgs} />
            <MultiSelect label="Severity" options={["High", "Medium", "Low"]} value={sev} onChange={setSev} />
          </div>
          <DataTable columns={cols} rows={view} empty="No findings match the filters." />
          <p className="caption">{view.length} of {all.length} findings shown · values are intentionally not displayed</p>
        </>
      )}
      {r.skipped_entities.length > 0 && (
        <Expander title={`${r.skipped_entities.length} low-confidence finding(s) NOT redacted`}>
          <DataTable columns={cols.filter((c) => c.key !== "n")} rows={r.skipped_entities} noMax />
        </Expander>
      )}
    </div>
  );
}

function RedactedPane({ r, pick }) {
  const pages = r.pages;
  const [page, setPage] = useState(pages[0]);
  useEffect(() => setPage(r.pages[0]), [pick]); // eslint-disable-line react-hooks/exhaustive-deps
  const blocks = r.aligned ? r.redacted.filter((b) => b.page === page) : r.redacted;
  return (
    <div className="panel">
      {r.aligned && pages.length > 1 && (
        <div style={{ maxWidth: 260 }}>
          <Select label="Page / slide" value={page} onChange={(v) => setPage(Number(v))}
                  options={pages.map((p) => ({ value: p, label: String(p) }))} />
        </div>
      )}
      <div className="redacted">
        {blocks.map((b, i) => (
          <div key={i}>
            {r.aligned && <div className="loc">{b.location}</div>}
            <Highlighted text={b.text} />
          </div>
        ))}
      </div>
      <p className="caption">This redacted text is the only content intended for the LLM.</p>
    </div>
  );
}

function TracePane({ r }) {
  const cols = [
    { key: "Placeholder", label: "Placeholder" }, { key: "Type", label: "Type" },
    { key: "Occurrences", label: "Occurrences", className: "num" }, { key: "Pages/Slides", label: "Pages/Slides" },
  ];
  return (
    <div className="panel">
      {r.placeholders.length > 0 && (
        <>
          <b>Placeholders</b> <span className="muted">(same value → same token within the file)</span>
          <DataTable columns={cols} rows={r.placeholders} />
        </>
      )}
      <p style={{ marginTop: 22 }}><b>Exposure report</b> <span className="muted">(type, location, confidence - no raw values)</span></p>
      <pre className="code">{JSON.stringify(r.report, null, 2)}</pre>
      {r.teammate_report_note ? (
        <Alert kind="warning">{r.teammate_report_note}</Alert>
      ) : r.teammate_report != null ? (
        <Expander title="Report returned by the redaction module">
          <pre className="code">{typeof r.teammate_report === "string" ? r.teammate_report : JSON.stringify(r.teammate_report, null, 2)}</pre>
        </Expander>
      ) : null}
    </div>
  );
}

export function FileTab({ results }) {
  const [pick, setPick] = useState(0);
  const [inner, setInner] = useState("Detected PII");
  const idx = Math.min(pick, results.length - 1);
  const r = results[idx];
  return (
    <div className="panel">
      <div style={{ maxWidth: 480 }}>
        <Select label="File" value={idx} onChange={(v) => setPick(Number(v))}
                options={results.map((x, i) => ({ value: i, label: `${i + 1}. ${x.filename}` }))} />
      </div>
      {r.status === "failed" ? (
        <>
          <Alert kind="error"><b>{r.failed_stage || "processing"} failed</b> - {r.error}</Alert>
          <p className="caption">{STAGE_HINT[r.failed_stage] || ""}</p>
        </>
      ) : (
        <>
          {r.llm_ready
            ? <Alert kind="success">Cleared for LLM: detected PII was replaced and the verification pass found nothing left.</Alert>
            : <Alert kind="error">NOT cleared for LLM - possible PII leak(s) remain. Do not forward this text.</Alert>}
          {r.warnings.map((w, i) => <Alert key={"w" + i} kind="warning">{w}</Alert>)}
          {r.leaks.map((l, i) => <Alert key={"l" + i} kind="error">{l}</Alert>)}
          <div className="metrics">
            <Metric label="Blocks" value={r.block_count} />
            <Metric label="PII entities" value={r.entities.length} />
            <Metric label="Non-PII text preserved" value={pct(r.non_pii_preserved)}
                    help="Demo proxy. The official structure-retention metric is defined by the Evaluation role." />
            <Metric label="Lowest OCR confidence" value={r.lowest_ocr == null ? "n/a" : r.lowest_ocr.toFixed(2)} />
          </div>
          <Tabs inner tabs={["Detected PII", "Redacted text", "Traceability & report"]} value={inner} onChange={setInner} />
          {inner === "Detected PII" && <EntitiesPane r={r} pick={idx} />}
          {inner === "Redacted text" && <RedactedPane r={r} pick={idx} />}
          {inner === "Traceability & report" && <TracePane r={r} />}
        </>
      )}
      <Expander title="Processing log"><pre className="code">{r.log.join("\n") || "-"}</pre></Expander>
    </div>
  );
}

// =============================================================== Evaluation
export function EvalTab({ runId, results }) {
  const [gt, setGt] = useState(null);
  const [partial, setPartial] = useState(false);
  const [mtype, setMtype] = useState(false);
  const [out, setOut] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    if (!gt) { setOut(null); setErr(""); return; }
    let live = true;
    api.evaluate(runId, gt, partial, mtype)
      .then((d) => { if (live) { setOut(d); setErr(""); } })
      .catch((e) => { if (live) { setOut(null); setErr(e.message); } });
    return () => { live = false; };
  }, [gt, partial, mtype, runId, results]);

  const fcols = ["File", "Ground truth", "Detected", "Hits", "False positives", "Missed (false negatives)", "Precision", "Recall"]
    .map((k, i) => ({ key: k, label: k, className: i ? "num" : "wrap" }));
  const tcols = ["Type", "Ground truth", "Found", "Recall"].map((k, i) => ({ key: k, label: k, className: i ? "num" : "" }));
  return (
    <div className="panel">
      <p style={{ margin: 0 }}>
        Score detection against <b>ground truth</b> (CSV/JSON with <code>filename</code>, <code>text</code>, optional <code>entity_type</code>).
        Ground truth stays in memory only - never commit it. The team's offline evaluation command remains the source of the official numbers.
      </p>
      <div className="filepick">
        <label className="btn" style={{ padding: "0.4rem 1rem" }}>
          Choose ground truth file
          <input type="file" accept=".csv,.json" hidden onChange={(e) => setGt(e.target.files[0] || null)} />
        </label>
        <span className="muted small">{gt ? gt.name : "No file selected (.csv or .json)"}</span>
        {gt && <button className="icon-btn" title="Remove" onClick={() => setGt(null)}>✕</button>}
      </div>
      <div className="grid3">
        <label className="check"><input type="checkbox" checked={partial} onChange={(e) => setPartial(e.target.checked)} />Count partial / overlapping matches as hits</label>
        <label className="check"><input type="checkbox" checked={mtype} onChange={(e) => setMtype(e.target.checked)} />Also require the PII type to match</label>
      </div>
      {err && <Alert kind="error">{err}</Alert>}
      {out && (out.files.length === 0
        ? <Alert kind="warning">No filenames in the ground truth match the processed files.</Alert>
        : (
          <>
            <DataTable columns={fcols} rows={out.files} />
            <div className="metrics">
              <Metric label="Overall recall (coverage)" value={pct(out.summary.recall)} />
              <Metric label="Overall precision" value={pct(out.summary.precision)} />
              <Metric label="Missed items" value={out.summary.missed} />
            </div>
            {out.types.length > 0 && (
              <>
                <p style={{ marginTop: 22 }}><b>Recall by PII type</b></p>
                <DataTable columns={tcols} rows={out.types} />
              </>
            )}
          </>
        ))}
    </div>
  );
}

// =============================================================== Exports
export function ExportsTab({ runId, results }) {
  const ok = results.filter((r) => r.status !== "failed" && r.index >= 0);
  const [one, setOne] = useState(0);
  const sel = ok[Math.min(one, ok.length - 1)];
  const hasFindings = ok.some((r) => r.entities.length > 0);
  const cleared = results.some((r) => r.llm_ready);
  const link = (path, disabled) => (disabled ? { className: "btn disabled", "aria-disabled": true } : { className: "btn", href: api.url(runId, path) });
  return (
    <div className="panel">
      <p style={{ margin: 0 }}>Exports contain no raw PII values.</p>
      <div className="dl-row">
        <a {...link("report.json", false)}>⬇ Exposure report (JSON)</a>
        <a {...link("findings.csv", !hasFindings)}>⬇ Findings (CSV)</a>
        <a {...link("redacted.zip", !cleared)}>⬇ Redacted text, cleared files (ZIP)</a>
      </div>
      {ok.length > 0 && (
        <>
          <hr />
          <div style={{ maxWidth: 480 }}>
            <Select label="Single redacted file" value={Math.min(one, ok.length - 1)} onChange={(v) => setOne(Number(v))}
                    options={ok.map((r, i) => ({ value: i, label: r.filename }))} />
          </div>
          <div className="dl-row">
            <a {...link(`files/${sel.index}/redacted.txt`, !sel.llm_ready)}>⬇ Download redacted .txt</a>
          </div>
          {!sel.llm_ready && <p className="caption">Disabled: this file is not cleared for LLM.</p>}
        </>
      )}
    </div>
  );
}
