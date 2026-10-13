import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import {
  Alert, BarChart, ClearedBadge, DataTable, Expander, Metric, MultiSelect,
  RiskBadge, SearchInput, Select, SensitiveValue, SeverityBadge, StatusBadge,
  Tabs, pct,
} from "./ui";

const PLACEHOLDER_RE = /\[[A-Z][A-Z_]*_\d+\]/g;

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

// ─── Get original value from ephemeral in-memory map ─────────────────────────
function getOriginal(entity, result, corrMap) {
  if (!corrMap) return null;
  const key = `${result.filename}::${entity.n || entity.placeholder || `${entity.block}_${entity.start}`}`;
  if (corrMap.entityMap?.has(key)) return corrMap.entityMap.get(key);
  if (entity.placeholder && corrMap.placeholderMap?.has(entity.placeholder)) {
    return corrMap.placeholderMap.get(entity.placeholder);
  }
  return null;
}

// ─── Expandable detail panel for a single entity ─────────────────────────────
function EntityDetail({ entity, result, corrMap }) {
  const original = getOriginal(entity, result, corrMap);
  const available = corrMap?.isClientExtracted === true || !!original;
  const rows = [
    ["PII Type", entity.entity_type],
    ["Severity", <SeverityBadge key="s" s={entity.severity} />],
    ["Placeholder", <code key="ph">{entity.placeholder || "-"}</code>],
    ["Confidence", entity.confidence != null ? `${(entity.confidence * 100).toFixed(1)}%` : "-"],
    ["Detector", entity.detector || "-"],
    ["Source File", result.filename],
    ["Block #", entity.block != null ? entity.block : "-"],
    ["Page / Slide", entity.page || "-"],
    ["Location", entity.location || "-"],
    ["Char start", entity.start != null ? entity.start : "-"],
    ["Char end", entity.end != null ? entity.end : "-"],
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
        <div className="entity-detail-row">
          <span className="entity-detail-label">
            Original Value
            <span className="badge badge--warn" style={{ marginLeft: 6, fontSize: "0.65rem" }}>Sensitive</span>
          </span>
          <span className="entity-detail-val">
            <SensitiveValue value={original} available={available} />
          </span>
        </div>
      </div>
      {!available && (
        <p className="entity-detail-note">
          ℹ Original value is available only for plain text files (.txt) during the current session.
          For PDF, DOCX, and PPTX the raw PII stays inside the server process (by design) and is never sent to the browser.
        </p>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// OVERVIEW TAB
// ─────────────────────────────────────────────────────────────────────────────
export function OverviewTab({ results }) {
  const totals = useMemo(() => {
    const t = {};
    results.forEach((r) => Object.entries(r.categories).forEach(([k, v]) => { t[k] = (t[k] || 0) + v; }));
    return t;
  }, [results]);

  const cols = [
    { key: "filename", label: "File", className: "wrap", render: (r) => <span title={r.filename}>{r.filename}</span> },
    { key: "file_type", label: "Type", render: (r) => r.file_type?.toUpperCase() || "-" },
    { key: "status", label: "Status", render: (r) => <StatusBadge status={r.status} /> },
    { key: "risk", label: "Risk", render: (r) => <RiskBadge risk={r.risk} /> },
    { key: "pages", label: "Pages", render: (r) => r.pages.length, className: "num" },
    { key: "pii", label: "PII Found", render: (r) => r.entities.length, className: "num" },
    { key: "cats", label: "Categories", className: "wrap",
      render: (r) => Object.entries(r.categories).map(([k, v]) => `${k} ×${v}`).join(", ") || "—" },
    { key: "llm_ready", label: "LLM Ready", render: (r) => <ClearedBadge ready={r.llm_ready} /> },
    { key: "time", label: "Time (s)", className: "num",
      render: (r) => (Object.values(r.timings || {}).reduce((a, b) => a + b, 0) * 1).toFixed(2) },
  ];

  const rows = results.map((r) => ({ ...r }));

  const expandRow = (r) => {
    if (r.status === "failed") {
      return <Alert kind="error"><b>{r.failed_stage || "processing"} failed:</b> {r.error}</Alert>;
    }
    return (
      <div style={{ padding: "12px 4px" }}>
        {r.warnings.length > 0 && r.warnings.map((w, i) => <Alert key={i} kind="warning">{w}</Alert>)}
        {r.leaks.length > 0 && r.leaks.map((l, i) => <Alert key={i} kind="error">{l}</Alert>)}
        {!r.warnings.length && !r.leaks.length && (
          <Alert kind="success">No warnings or leaks for this file.</Alert>
        )}
        <div className="metrics-grid metrics-grid--compact" style={{ marginTop: 12 }}>
          <Metric label="Blocks" value={r.block_count} />
          <Metric label="Non-PII preserved" value={pct(r.non_pii_preserved)} help="Demo proxy metric" />
          {r.lowest_ocr != null && <Metric label="Lowest OCR" value={r.lowest_ocr.toFixed(2)} />}
        </div>
      </div>
    );
  };

  return (
    <div className="panel">
      <DataTable columns={cols} rows={rows} expandRow={expandRow} empty="No results yet." />
      {Object.keys(totals).length > 0 && (
        <div className="chart-section">
          <h4 className="chart-title">PII Distribution by Category</h4>
          <BarChart data={totals} />
        </div>
      )}
      {!results.some((r) => r.entities.length > 0) && results.length > 0 && (
        <Alert kind="success">No PII detected in any processed file.</Alert>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// FINDINGS TAB — searchable, filterable cross-file findings table
// ─────────────────────────────────────────────────────────────────────────────
export function FindingsTab({ results, originalValueMaps = [] }) {
  const [search, setSearch] = useState("");
  const [filterType, setFilterType] = useState([]);
  const [filterFile, setFilterFile] = useState([]);
  const [filterSev, setFilterSev] = useState([]);
  const [showOriginal, setShowOriginal] = useState(false);

  const allFindings = useMemo(() => {
    const out = [];
    results.forEach((r, ri) => {
      const corrMap = originalValueMaps[ri];
      r.entities.forEach((e) => {
        const original = getOriginal(e, r, corrMap);
        const available = corrMap?.isClientExtracted === true || !!original;
        out.push({ ...e, filename: r.filename, _result: r, _corrMap: corrMap, _original: original, _origAvailable: available });
      });
    });
    return out;
  }, [results, originalValueMaps]);

  const allTypes = useMemo(() => [...new Set(allFindings.map((e) => e.entity_type))].sort(), [allFindings]);
  const allFiles = useMemo(() => [...new Set(results.map((r) => r.filename))], [results]);

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return allFindings.filter((e) => {
      if (filterType.length && !filterType.includes(e.entity_type)) return false;
      if (filterFile.length && !filterFile.includes(e.filename)) return false;
      if (filterSev.length && !filterSev.includes(e.severity)) return false;
      if (q && !e.entity_type.toLowerCase().includes(q) &&
          !e.placeholder.toLowerCase().includes(q) &&
          !e.filename.toLowerCase().includes(q) &&
          !(e._original || "").toLowerCase().includes(q)) return false;
      return true;
    });
  }, [allFindings, filterType, filterFile, filterSev, search]);

  const cols = [
    { key: "n", label: "#", className: "num" },
    { key: "entity_type", label: "PII Type" },
    { key: "severity", label: "Severity", render: (e) => <SeverityBadge s={e.severity} /> },
    ...(showOriginal ? [{
      key: "original", label: "Original Value",
      render: (e) => <SensitiveValue value={e._original} available={e._origAvailable} />,
    }] : []),
    { key: "placeholder", label: "Placeholder", className: "nowrap", render: (e) => <code>{e.placeholder || "-"}</code> },
    { key: "confidence", label: "Confidence", className: "num",
      render: (e) => e.confidence != null ? `${(e.confidence * 100).toFixed(0)}%` : "-" },
    { key: "filename", label: "File", className: "wrap", render: (e) => <span title={e.filename}>{e.filename}</span> },
    { key: "page", label: "Page", className: "num" },
    { key: "detector", label: "Detector" },
  ];

  const expandRow = (e) => (
    <EntityDetail entity={e} result={e._result} corrMap={e._corrMap} />
  );

  if (!allFindings.length) {
    return (
      <div className="panel">
        <Alert kind="success">No PII entities detected across all processed files.</Alert>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="findings-toolbar">
        <SearchInput value={search} onChange={setSearch} placeholder="Search type, placeholder, file…" />
        <div className="findings-filters">
          <MultiSelect label="PII Type" options={allTypes} value={filterType} onChange={setFilterType} />
          <MultiSelect label="File" options={allFiles} value={filterFile} onChange={setFilterFile} />
          <MultiSelect label="Severity" options={["High", "Medium", "Low"]} value={filterSev} onChange={setFilterSev} />
        </div>
        <label className="toggle-check">
          <input type="checkbox" checked={showOriginal} onChange={(e) => setShowOriginal(e.target.checked)} />
          Show original values
          <span className="badge badge--warn" style={{ marginLeft: 6, fontSize: "0.65rem" }}>Sensitive</span>
        </label>
      </div>

      <DataTable
        columns={cols}
        rows={filtered}
        expandRow={expandRow}
        empty="No findings match the current filters."
      />

      <p className="findings-footer">
        {filtered.length} of {allFindings.length} findings shown
        {showOriginal && originalValueMaps.some((m) => !m?.isClientExtracted) && (
          <span className="findings-note">
            · Original values available for .txt files in this session only. Binary documents are protected server-side.
          </span>
        )}
      </p>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// FILE DETAILS TAB
// ─────────────────────────────────────────────────────────────────────────────
const STAGE_HINTS = {
  validation: "Check the file type/size or re-export the document.",
  extraction: "The file may be encrypted, corrupt, or scanned — OCR is required by the extraction module.",
  detection: "The detection module raised an error — see the processing log below.",
  redaction: "The redaction module raised an error — see the processing log below.",
};

function EntitiesPane({ r, corrMap }) {
  const [cats, setCats] = useState([]);
  const [pgs, setPgs] = useState([]);
  const [sev, setSev] = useState([]);
  const [search, setSearch] = useState("");
  const [showOriginal, setShowOriginal] = useState(false);

  const all = r.entities;
  const filtered = all.filter((e) => {
    if (cats.length && !cats.includes(e.entity_type)) return false;
    if (pgs.length && !pgs.includes(e.page)) return false;
    if (sev.length && !sev.includes(e.severity)) return false;
    if (search) {
      const q = search.toLowerCase();
      if (!e.entity_type.toLowerCase().includes(q) && !e.placeholder.toLowerCase().includes(q)) return false;
    }
    return true;
  });

  const cols = [
    { key: "n", label: "#", className: "num" },
    { key: "entity_type", label: "Type" },
    { key: "severity", label: "Severity", render: (e) => <SeverityBadge s={e.severity} /> },
    ...(showOriginal ? [{
      key: "original", label: "Original Value",
      render: (e) => <SensitiveValue value={getOriginal(e, r, corrMap)} available={corrMap?.isClientExtracted || !!getOriginal(e, r, corrMap)} />,
    }] : []),
    { key: "placeholder", label: "Placeholder", className: "nowrap", render: (e) => <code>{e.placeholder || "-"}</code> },
    { key: "confidence", label: "Conf.", className: "num",
      render: (e) => e.confidence != null ? `${(e.confidence * 100).toFixed(0)}%` : "-" },
    { key: "page", label: "Page", className: "num" },
    { key: "location", label: "Location", className: "wrap" },
    { key: "detector", label: "Detector" },
  ];

  const expandRow = (e) => <EntityDetail entity={e} result={r} corrMap={corrMap} />;

  if (all.length === 0) {
    return (
      <div className="panel">
        <Alert kind="success">No PII entities detected in this file.</Alert>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="findings-toolbar">
        <SearchInput value={search} onChange={setSearch} placeholder="Filter by type or placeholder…" />
        <div className="findings-filters">
          <MultiSelect label="PII Type" options={[...new Set(all.map((e) => e.entity_type))].sort()} value={cats} onChange={setCats} />
          <MultiSelect label="Page" options={[...new Set(all.map((e) => e.page))].sort((a, b) => a - b)} value={pgs} onChange={setPgs} />
          <MultiSelect label="Severity" options={["High", "Medium", "Low"]} value={sev} onChange={setSev} />
        </div>
        <label className="toggle-check">
          <input type="checkbox" checked={showOriginal} onChange={(e) => setShowOriginal(e.target.checked)} />
          Show originals
          <span className="badge badge--warn" style={{ marginLeft: 6, fontSize: "0.65rem" }}>Sensitive</span>
        </label>
      </div>
      <DataTable columns={cols} rows={filtered} expandRow={expandRow} empty="No findings match the filters." />
      <p className="findings-footer">
        {filtered.length} of {all.length} findings shown · Values are protected
        {corrMap?.isClientExtracted
          ? " · Original values derived from in-memory file text this session"
          : " · Original values for binary files remain server-side only"}
      </p>
      {r.skipped_entities.length > 0 && (
        <Expander title={`${r.skipped_entities.length} low-confidence finding(s) not redacted`}>
          <DataTable
            columns={cols.filter((c) => c.key !== "n" && c.key !== "original")}
            rows={r.skipped_entities}
            noMax
          />
        </Expander>
      )}
    </div>
  );
}

function RedactedPane({ r }) {
  const pages = r.pages;
  const [page, setPage] = useState(pages[0]);
  const [copied, setCopied] = useState(false);

  useEffect(() => setPage(r.pages[0]), [r]);

  const blocks = r.aligned ? r.redacted.filter((b) => b.page === page) : r.redacted;
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
        {r.aligned && pages.length > 1 && (
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
            <a
              className="btn btn--sm"
              href={`/api/runs/${r._runId}/files/${r.index}/redacted.txt`}
              download
              title="Download this file's redacted text"
            >
              Download .txt
            </a>
          )}
        </div>
      </div>

      <div className="redacted-preview">
        {blocks.length === 0 && <span className="muted">No redacted content for this page.</span>}
        {blocks.map((b, i) => (
          <div key={i} className="redacted-block">
            {r.aligned && b.location && <div className="redacted-location">{b.location}</div>}
            <HighlightedText text={b.text} />
          </div>
        ))}
      </div>
      <p className="findings-footer">
        Redacted text is the only content intended for the LLM.
        Sensitive original values are intentionally excluded from this view.
      </p>
    </div>
  );
}

function TracePane({ r }) {
  const plCols = [
    { key: "Placeholder", label: "Placeholder", render: (x) => <code>{x.Placeholder}</code> },
    { key: "Type", label: "PII Type" },
    { key: "Occurrences", label: "Occurrences", className: "num" },
    { key: "Pages/Slides", label: "Pages / Slides" },
  ];

  // Category summary
  const catSummary = Object.entries(r.categories || {}).map(([type, count]) => ({ type, count }));

  return (
    <div className="panel">
      {/* Category breakdown */}
      {catSummary.length > 0 && (
        <div className="trace-section">
          <h4 className="section-label">Detection Summary by Category</h4>
          <div className="category-grid">
            {catSummary.map(({ type, count }) => (
              <div key={type} className="category-card">
                <span className="category-type">{type}</span>
                <span className="category-count">{count}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Placeholder table */}
      {r.placeholders.length > 0 && (
        <div className="trace-section">
          <h4 className="section-label">Placeholder Index</h4>
          <p className="trace-note">
            Same original value → same placeholder within the file. A placeholder cannot be reversed without the original value.
          </p>
          <DataTable columns={plCols} rows={r.placeholders} />
        </div>
      )}

      {/* Exposure report */}
      <div className="trace-section">
        <h4 className="section-label">Exposure Report <span className="muted">(type, location, confidence — no raw values)</span></h4>
        <pre className="code-block">{JSON.stringify(r.report, null, 2)}</pre>
      </div>

      {/* Verification status */}
      <div className="trace-section">
        <h4 className="section-label">Verification</h4>
        {r.leaks.length > 0
          ? r.leaks.map((l, i) => <Alert key={i} kind="error">{l}</Alert>)
          : <Alert kind="success">Verification pass found no residual PII in the redacted output.</Alert>
        }
      </div>

      {/* Teammate redaction report */}
      {r.teammate_report_note && (
        <Alert kind="warning">{r.teammate_report_note}</Alert>
      )}
      {!r.teammate_report_note && r.teammate_report != null && (
        <Expander title="Report returned by the redaction module">
          <pre className="code-block">
            {typeof r.teammate_report === "string"
              ? r.teammate_report
              : JSON.stringify(r.teammate_report, null, 2)}
          </pre>
        </Expander>
      )}
    </div>
  );
}

export function FileTab({ results, originalValueMaps = [] }) {
  const [pick, setPick] = useState(0);
  const [inner, setInner] = useState("Detected PII");
  const idx = Math.min(pick, results.length - 1);
  const r = results[idx];
  const corrMap = originalValueMaps[idx];

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

      {/* File status banner */}
      {r.status === "failed" ? (
        <>
          <Alert kind="error">
            <strong>{r.failed_stage || "processing"} failed</strong> — {r.error}
          </Alert>
          {STAGE_HINTS[r.failed_stage] && (
            <p className="findings-note">{STAGE_HINTS[r.failed_stage]}</p>
          )}
        </>
      ) : (
        <>
          {r.llm_ready
            ? <Alert kind="success">Cleared for LLM — PII was replaced and the verification pass found nothing left.</Alert>
            : <Alert kind="error">Not cleared for LLM — possible PII leak(s) remain. Do not forward this text.</Alert>
          }
          {r.warnings.map((w, i) => <Alert key={`w${i}`} kind="warning">{w}</Alert>)}
          {r.leaks.map((l, i) => <Alert key={`l${i}`} kind="error">{l}</Alert>)}

          {/* File-level metrics */}
          <div className="metrics-grid metrics-grid--compact">
            <Metric label="Blocks" value={r.block_count} />
            <Metric label="PII Entities" value={r.entities.length} accent={r.entities.length > 0} />
            <Metric label="Skipped (low conf.)" value={r.skipped_entities.length} />
            <Metric label="Non-PII preserved" value={pct(r.non_pii_preserved)} help="Demo proxy metric" />
            {r.lowest_ocr != null && <Metric label="Lowest OCR" value={r.lowest_ocr.toFixed(2)} />}
          </div>

          {/* Inner tabs */}
          <Tabs
            inner
            tabs={["Detected PII", "Redacted Text", "Traceability & Report"]}
            value={inner}
            onChange={setInner}
          />

          {inner === "Detected PII"          && <EntitiesPane r={r} corrMap={corrMap} />}
          {inner === "Redacted Text"          && <RedactedPane r={r} />}
          {inner === "Traceability & Report"  && <TracePane r={r} />}
        </>
      )}

      <Expander title="Processing log">
        <pre className="code-block">{r.log?.join("\n") || "—"}</pre>
      </Expander>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// EVALUATION TAB
// ─────────────────────────────────────────────────────────────────────────────
export function EvalTab({ runId, results }) {
  const [gt, setGt] = useState(null);
  const [partial, setPartial] = useState(false);
  const [mtype, setMtype] = useState(false);
  const [out, setOut] = useState(null);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!gt) { setOut(null); setErr(""); return; }
    let live = true;
    setLoading(true);
    api.evaluate(runId, gt, partial, mtype)
      .then((d) => { if (live) { setOut(d); setErr(""); setLoading(false); } })
      .catch((e) => { if (live) { setOut(null); setErr(e.message); setLoading(false); } });
    return () => { live = false; };
  }, [gt, partial, mtype, runId, results]);

  const fcols = ["File", "Ground truth", "Detected", "Hits", "False positives", "Missed (false negatives)", "Precision", "Recall"]
    .map((k, i) => ({ key: k, label: k, className: i ? "num" : "wrap" }));
  const tcols = ["Type", "Ground truth", "Found", "Recall"]
    .map((k, i) => ({ key: k, label: k, className: i ? "num" : "" }));

  return (
    <div className="panel">
      <div className="eval-intro">
        <p>
          Score detection accuracy against a <strong>ground truth</strong> file
          (CSV or JSON with <code>filename</code>, <code>text</code>, optional <code>entity_type</code> columns).
        </p>
        <p className="findings-note">
          Ground truth data stays in memory only. Never commit it. The team's offline evaluation command is the source of official numbers.
        </p>
      </div>

      <div className="eval-controls">
        <label className="btn btn--ghost" style={{ cursor: "pointer" }}>
          Choose ground truth file
          <input type="file" accept=".csv,.json" hidden onChange={(e) => setGt(e.target.files[0] || null)} />
        </label>
        <span className="muted small">{gt ? gt.name : "No file selected (.csv or .json)"}</span>
        {gt && (
          <button className="icon-btn" title="Remove" onClick={() => setGt(null)}>✕</button>
        )}
      </div>

      <div className="eval-options">
        <label className="toggle-check">
          <input type="checkbox" checked={partial} onChange={(e) => setPartial(e.target.checked)} />
          Count partial / overlapping matches as hits
        </label>
        <label className="toggle-check">
          <input type="checkbox" checked={mtype} onChange={(e) => setMtype(e.target.checked)} />
          Also require the PII type to match
        </label>
      </div>

      {loading && <Alert kind="info">Scoring…</Alert>}
      {err && <Alert kind="error">{err}</Alert>}

      {out && (
        out.files.length === 0
          ? <Alert kind="warning">No filenames in the ground truth match the processed files.</Alert>
          : (
            <>
              <h4 className="section-label">Per-File Results</h4>
              <DataTable columns={fcols} rows={out.files} />
              <div className="metrics-grid metrics-grid--compact">
                <Metric label="Overall Recall" value={pct(out.summary?.recall)} help="True positives / ground truth count" />
                <Metric label="Overall Precision" value={pct(out.summary?.precision)} help="(Detected - FP) / Detected" />
                <Metric label="Missed Items" value={out.summary?.missed ?? "—"} />
              </div>
              {out.types.length > 0 && (
                <>
                  <h4 className="section-label" style={{ marginTop: 24 }}>Recall by PII Type</h4>
                  <DataTable columns={tcols} rows={out.types} />
                </>
              )}
            </>
          )
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
  const hasFindings = ok.some((r) => r.entities.length > 0);
  const cleared = results.some((r) => r.llm_ready);

  const link = (path, disabled) =>
    disabled
      ? { className: "btn btn--ghost btn--disabled", "aria-disabled": true }
      : { className: "btn btn--ghost", href: `/api/runs/${runId}/${path}` };

  return (
    <div className="panel">
      <Alert kind="info">
        All exports contain <strong>no raw PII values</strong>. Only placeholders, types, and metadata are included.
      </Alert>

      <div className="exports-section">
        <h4 className="section-label">Bulk Exports</h4>
        <div className="dl-row">
          <a {...link("report.json", false)}>Export Report (JSON)</a>
          <a {...link("findings.csv", !hasFindings)}>Export Findings (CSV)</a>
          <a {...link("redacted.zip", !cleared)}>Download Redacted (ZIP)</a>
        </div>
        {!cleared && (
          <p className="findings-note">ZIP export disabled — no files are cleared for LLM yet.</p>
        )}
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
          {sel && (
            <>
              <div className="dl-row">
                <a {...link(`files/${sel.index}/redacted.txt`, !sel.llm_ready)}>
                  Download Redacted .txt
                </a>
              </div>
              {!sel.llm_ready && (
                <p className="findings-note">Disabled: this file is not cleared for LLM (possible leaks detected).</p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
