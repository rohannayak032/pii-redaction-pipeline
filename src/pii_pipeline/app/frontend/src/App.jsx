import { useCallback, useEffect, useRef, useState } from "react";
import { api, failedStub, precheck } from "./api";
import { EvalTab, ExportsTab, FileTab, FindingsTab, OverviewTab, groupFindings } from "./tabs";
import { Alert, BrandShield, DynamicBackground, Metric, Tabs, ThemeSwitch, ThemeTransitionBeams, useTheme } from "./ui";

// ─── Format file size ─────────────────────────────────────────────────────────
function fmtSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

// ─── File type badge ────────────────────────────────────────────────────────────
function FileTypeIcon({ type }) {
  return <span className="file-type-badge">{(type || "-").toUpperCase()}</span>;
}

// ─── Supported format pill ─────────────────────────────────────────────────────
function FormatPill({ ext }) {
  return <span className="format-pill" title={ext}>{ext.slice(1).toUpperCase()}</span>;
}

// ─── File queue row ────────────────────────────────────────────────────────────
function FileRow({ f, busy, onRemove }) {
  return (
    <div className={`file-row${f.ok ? "" : " file-row--invalid"}`}>
      <div className="file-row-icon">
        <FileTypeIcon type={f.type} />
      </div>
      <div className="file-row-info">
        <span className="file-row-name" title={f.file.name}>{f.file.name}</span>
        <span className="file-row-meta">{fmtSize(f.file.size)}</span>
      </div>
      <div className="file-row-status">
        {f.ok
          ? <span className="status-ok">Ready</span>
          : <span className="status-err" title={f.msg}>{f.msg}</span>
        }
      </div>
      <button
        className="file-row-remove"
        title="Remove file"
        disabled={!!busy}
        onClick={onRemove}
        aria-label={`Remove ${f.file.name}`}
      >
        ✕
      </button>
    </div>
  );
}

// ─── Drop zone ────────────────────────────────────────────────────────────────
function DropZone({ over, onDragOver, onDragLeave, onDrop, onBrowse, cfg }) {
  return (
    <div
      className={`dropzone${over ? " dropzone--active" : ""}`}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      role="region"
      aria-label="File upload drop zone"
    >
      <div className="dropzone-icon" aria-hidden="true">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 15V3M7 8l5-5 5 5" />
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
        </svg>
      </div>
      <p className="dropzone-headline">Drag &amp; drop documents here</p>
      <p className="dropzone-sub">or</p>
      <button className="btn btn--primary" onClick={onBrowse} type="button" disabled={!cfg}>
        Browse Files
      </button>
      <div className="dropzone-formats">
        {cfg?.supported.map((ext) => <FormatPill key={ext} ext={ext} />)}
        {cfg && <span className="dropzone-limit">· max {cfg.max_file_mb} MB per file</span>}
      </div>
      <p className="dropzone-privacy">
        Raw PII values are never stored, logged, or exported
      </p>
    </div>
  );
}

// ─── Progress bar ─────────────────────────────────────────────────────────────
function ProgressBar({ busy }) {
  if (!busy) return null;
  return (
    <div className="analysis-progress">
      <div className="progress-bar">
        <div className="progress-bar-fill progress-bar-fill--indeterminate" />
      </div>
      <p className="progress-label">
        <span className="progress-badge">{busy.i + 1}/{busy.n}</span>
        Analysing <strong>{busy.name}</strong>…
      </p>
    </div>
  );
}

// ─── App ──────────────────────────────────────────────────────────────────────
export default function App() {
  const [theme, setTheme] = useTheme();
  const [cfg, setCfg] = useState(null);
  const [cfgErr, setCfgErr] = useState("");
  const [files, setFiles] = useState([]); // [{file, type, sizeKb, ok, msg, ext}]
  const [results, setResults] = useState([]);
  const [runId, setRunId] = useState(null);
  const [busy, setBusy] = useState(null); // {i, n, name}
  const [over, setOver] = useState(false);
  const [tab, setTab] = useState("Overview");
  const [dupWarning, setDupWarning] = useState("");
  const inputRef = useRef(null);
  const resultsRef = useRef(null);

  useEffect(() => { api.config().then(setCfg).catch((e) => setCfgErr(`Cannot reach the server: ${e.message}`)); }, []);

  // ── Add files with dedup + validation ───────────────────────────────────────
  const addFiles = useCallback(async (list) => {
    if (!cfg) return;
    const checked = [...list].map((f) => precheck(f, cfg));
    let dups = 0;
    setFiles((prev) => {
      const prevNames = new Set(prev.map((x) => x.file.name));
      const fresh = checked.filter((c) => {
        if (prevNames.has(c.file.name)) { dups++; return false; }
        return true;
      });
      if (dups > 0) setDupWarning(`${dups} duplicate file(s) skipped.`);
      else setDupWarning("");
      return [...prev, ...fresh];
    });
  }, [cfg]);

  const removeFile = (idx) => setFiles((prev) => prev.filter((_, i) => i !== idx));

  // ── Run analysis ─────────────────────────────────────────────────────────────
  const run = async () => {
    const validFiles = files.filter((f) => f.ok);
    if (!validFiles.length || busy) return;
    if (runId) api.deleteRun(runId);
    setResults([]);
    setDupWarning("");
    let id;
    try {
      id = (await api.createRun()).run_id;
    } catch (e) {
      setCfgErr(`Cannot reach the server: ${e.message}`);
      return;
    }
    setRunId(id);
    const out = [];
    for (let i = 0; i < validFiles.length; i++) {
      const f = validFiles[i].file;
      setBusy({ i, n: validFiles.length, name: f.name });
      try {
        const res = await api.process(id, f);
        out.push(res);
      } catch (e) {
        out.push(failedStub(f.name, e.message));
      }
    }
    setBusy(null);
    setResults(out);
    setTab("Overview");
    setTimeout(() => resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 80);
  };

  // ── Clear all ────────────────────────────────────────────────────────────────
  const clearAll = () => {
    if (runId) api.deleteRun(runId);
    setRunId(null);
    setResults([]);
    setFiles([]);
    setBusy(null);
    setCfgErr("");
    setDupWarning("");
  };

  // ── Drag & drop ──────────────────────────────────────────────────────────────
  const onDragOver = (e) => { e.preventDefault(); setOver(true); };
  const onDragLeave = () => setOver(false);
  const onDrop = (e) => {
    e.preventDefault();
    setOver(false);
    if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
  };

  const ok = results.filter((r) => r.status !== "failed");
  const validFiles = files.filter((f) => f.ok);
  const invalidFiles = files.filter((f) => !f.ok);
  const totalDetections = results.reduce((a, r) => a + r.entities.length, 0);
  const uniquePii = results.reduce((a, r) => a + groupFindings(r.entities).length, 0);
  const totalRedactions = results.reduce((a, r) => a + r.records.length, 0);
  const totalLeaks = results.reduce((a, r) => a + r.leaks.length, 0);
  const totalSeconds = results.reduce((a, r) => a + Object.values(r.timings).reduce((x, y) => x + y, 0), 0);
  const clearedCount = results.filter((r) => r.llm_ready).length;

  return (
    <div className="app">
      <DynamicBackground />
      <ThemeTransitionBeams />
      {/* ── Navigation ── */}
      <header className="nav">
        <div className="nav-brand">
          <div className="brand-logo" aria-hidden="true">
            <BrandShield size={28} />
          </div>
          <div className="brand-text">
            <span className="brand-name">
              PII <span className="brand-name-hl">Shield</span>
            </span>
            <span className="brand-tagline">Document Redaction Platform</span>
          </div>
        </div>
        <div className="nav-actions">
          <ThemeSwitch mode={theme} onChange={setTheme} />
        </div>
      </header>

      <main className="main">
        {/* ── Hero ── */}
        <section className="hero">
          <h1 className="hero-title">
            <span className="hero-hl">Detect, Redact &amp; Verify</span>
            <br />PII Before It Reaches an LLM
          </h1>
          <p className="hero-sub">
            Extraction, detection, redaction and verification run on the server; the browser receives the detections and the redacted text, never the original document
          </p>
          <div className="hero-badges">
            <span className="hero-badge">No raw PII in exports</span>
            <span className="hero-badge">Rules + ML detection</span>
            <span className="hero-badge">Every block verified after redaction</span>
          </div>
        </section>

        {/* ── Server error ── */}
        {cfgErr && <Alert kind="error"><strong>Server error:</strong> {cfgErr}</Alert>}

        {/* ── Drop zone ── */}
        <section className="upload-section">
          <DropZone
            over={over}
            onDragOver={onDragOver}
            onDragLeave={onDragLeave}
            onDrop={onDrop}
            onBrowse={() => inputRef.current?.click()}
            cfg={cfg}
          />
          <input
            ref={inputRef}
            type="file"
            multiple
            hidden
            accept={cfg?.supported.join(",")}
            onChange={(e) => { if (e.target.files.length) addFiles(e.target.files); e.target.value = ""; }}
          />
        </section>

        {/* ── Dup warning ── */}
        {dupWarning && <Alert kind="warning">{dupWarning}</Alert>}

        {/* ── File queue ── */}
        {files.length > 0 && (
          <section className="file-queue">
            <div className="file-queue-header">
              <h3 className="file-queue-title">
                File Queue
                <span className="file-queue-count">{files.length} file{files.length !== 1 ? "s" : ""}</span>
              </h3>
              {invalidFiles.length > 0 && (
                <span className="file-queue-warn">
                  {invalidFiles.length} file{invalidFiles.length !== 1 ? "s" : ""} will be skipped (invalid)
                </span>
              )}
            </div>
            <div className="file-queue-list">
              {files.map((f, i) => (
                <FileRow key={`${f.file.name}-${i}`} f={f} busy={busy} onRemove={() => removeFile(i)} />
              ))}
            </div>
          </section>
        )}

        {/* ── Action buttons ── */}
        <div className="actions">
          <button
            className="btn btn--primary btn--large"
            disabled={!validFiles.length || !!busy}
            onClick={run}
            title={!validFiles.length ? "Add at least one valid file to begin" : ""}
          >
            {busy ? (
              <><span className="btn-spinner" />Analysing…</>
            ) : (
              "Run Analysis"
            )}
          </button>
          <button className="btn btn--ghost" disabled={!!busy} onClick={clearAll}>
            Clear All
          </button>
        </div>

        {/* ── Progress ── */}
        <ProgressBar busy={busy} />

        {/* ── Footer hint (pre-results) ── */}
        {!results.length && !busy && cfg && (
          <div className="upload-footer">
            Supported formats: {cfg.supported.join(", ")} &nbsp;·&nbsp;
            Max {cfg.max_file_mb} MB per file &nbsp;·&nbsp;
            Exports never contain raw PII values
          </div>
        )}

        {/* ── Results dashboard ── */}
        {results.length > 0 && (
          <section className="results-section" ref={resultsRef}>
            <div className="results-header">
              <h2 className="results-title">Analysis Results</h2>
              <div className="results-run-id">
                Run ID: <code>{runId?.slice(0, 12)}…</code>
              </div>
            </div>

            {/* Summary metric cards */}
            <div className="metrics-grid">
              <Metric label="Files Processed" value={`${ok.length}/${results.length}`} />
              <Metric label="Unique PII" value={uniquePii} accent={uniquePii > 0}
                help={`Distinct values per file (type + value); ${totalDetections} detections in total, repeats and overlapping detections included`} />
              <Metric label="Redactions Applied" value={totalRedactions}
                help="Replaced spans from redaction.redact_document (overlapping detections merged)" />
              <Metric label="Cleared for LLM" value={`${clearedCount}/${results.length}`} accent={clearedCount === results.length && results.length > 0} />
              <Metric label="Residual Leaks" value={totalLeaks}
                help="Detected values still found anywhere in the redacted text" />
              <Metric label="Processing Time" value={`${totalSeconds.toFixed(1)} s`} />
            </div>

            {/* Tab navigation */}
            <Tabs
              tabs={["Overview", "Findings", "File Details", "Evaluation", "Exports"]}
              value={tab}
              onChange={setTab}
            />

            <div className="tab-panel">
              {tab === "Overview" && <OverviewTab results={results} />}
              {tab === "Findings" && <FindingsTab results={results} />}
              {tab === "File Details" && <FileTab runId={runId} results={results} />}
              {tab === "Evaluation" && <EvalTab runId={runId} results={results} cfg={cfg} />}
              {tab === "Exports" && <ExportsTab runId={runId} results={results} />}
            </div>
          </section>
        )}
      </main>
    </div>
  );
}


