import { useCallback, useEffect, useRef, useState } from "react";
import { api, failedStub, precheck } from "./api";
import { EvalTab, ExportsTab, FileTab, OverviewTab } from "./tabs";
import { Alert, DataTable, Metric, Tabs, ThemeSwitch, useTheme } from "./ui";

export default function App() {
  const [theme, setTheme] = useTheme();
  const [cfg, setCfg] = useState(null);
  const [cfgErr, setCfgErr] = useState("");
  const [files, setFiles] = useState([]);       // [{file, type, sizeKb, ok, msg}]
  const [results, setResults] = useState([]);
  const [runId, setRunId] = useState(null);
  const [busy, setBusy] = useState(null);       // {i, n, name} while running
  const [over, setOver] = useState(false);
  const [tab, setTab] = useState("Overview");
  const inputRef = useRef(null);
  const resultsRef = useRef(null);

  useEffect(() => { api.config().then(setCfg).catch((e) => setCfgErr(e.message)); }, []);

  const addFiles = useCallback(async (list) => {
    const checked = await Promise.all([...list].map((f) => precheck(f, cfg)));
    setFiles((prev) => [...prev, ...checked]);
  }, [cfg]);

  const run = async () => {
    if (!files.length || busy) return;
    if (runId) api.deleteRun(runId);
    setResults([]);
    let id;
    try { id = (await api.createRun()).run_id; }
    catch (e) { setCfgErr(`Cannot reach the server: ${e.message}`); return; }
    setRunId(id);
    const out = [];
    for (let i = 0; i < files.length; i++) {
      const f = files[i].file;
      setBusy({ i, n: files.length, name: f.name });
      try { out.push(await api.process(id, f)); }
      catch (e) { out.push(failedStub(f.name, e.message)); }
    }
    setBusy(null);
    setResults(out);
    setTab("Overview");
    setTimeout(() => resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
  };

  const clearAll = () => {
    if (runId) api.deleteRun(runId);
    setRunId(null); setResults([]); setFiles([]); setBusy(null); setCfgErr("");
  };

  const onDrop = (e) => { e.preventDefault(); setOver(false); if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files); };

  const ok = results.filter((r) => r.status !== "failed");
  const fileCols = [
    { key: "name", label: "File", render: (x) => x.file.name, className: "wrap" },
    { key: "type", label: "Type" },
    { key: "sizeKb", label: "Size (KB)", className: "num" },
    { key: "pre", label: "Pre-check", render: (x) => (x.ok ? "✅ OK" : `❌ ${x.msg}`), className: "wrap" },
    { key: "rm", label: "", render: (x) => (
      <button className="icon-btn" title="Remove" disabled={!!busy} onClick={() => setFiles(files.filter((y) => y !== x))}>✕</button>) },
  ];

  return (
    <div className="container">
      <header className="nav">
        <div className="brand"><div className="logo">🛡</div>PII Shield</div>
        <ThemeSwitch mode={theme} onChange={setTheme} />
      </header>

      <section className="hero">
        <h1><span className="hl">PII Shield:</span> Make Documents AI-Safe</h1>
        <p>Detect, redact and verify personal data before it reaches an LLM</p>
      </section>

      {cfgErr && <Alert kind="error">{cfgErr}</Alert>}

      <div className={`drop ${over ? "over" : ""}`}
           onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={onDrop}>
        <svg width="46" height="46" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M12 16V4M7 9l5-5 5 5" /><path d="M20 16v3a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-3" />
        </svg>
        <div className="t">Drag and drop evidence files here</div>
        <div className="s">PDF, DOCX, PPTX, TXT, PNG, JPG, TIF · up to {cfg?.max_file_mb ?? 25} MB per file</div>
        <button className="btn primary" style={{ marginTop: 10 }} onClick={() => inputRef.current?.click()}>Browse files</button>
        <input ref={inputRef} type="file" multiple hidden
               onChange={(e) => { if (e.target.files.length) addFiles(e.target.files); e.target.value = ""; }} />
      </div>

      {files.length > 0 && <DataTable columns={fileCols} rows={files} noMax />}

      <div className="actions">
        <button className="btn primary" disabled={!files.length || !!busy} onClick={run}>{busy ? "Analysing…" : "Run analysis"}</button>
        <button className="btn" disabled={!!busy} onClick={clearAll}>Clear all</button>
      </div>

      {busy && (
        <>
          <div className="progress indet"><div /></div>
          <p className="caption" style={{ textAlign: "center" }}>[{busy.i + 1}/{busy.n}] {busy.name}: processing…</p>
        </>
      )}

      {!results.length && !busy && (
        <div className="foot">
          Up to {cfg?.max_file_mb ?? 25} MB per file · {(cfg?.supported ?? []).join(", ")} · Raw PII values are never shown or exported
        </div>
      )}

      {results.length > 0 && (
        <div ref={resultsRef}>
          <hr />
          <h2>Results</h2>
          <div className="metrics">
            <Metric label="Files" value={results.length} />
            <Metric label="Processed" value={ok.length} />
            <Metric label="Failed" value={results.length - ok.length} />
            <Metric label="PII entities" value={results.reduce((a, r) => a + r.entities.length, 0)} />
            <Metric label="Cleared for LLM" value={`${results.filter((r) => r.llm_ready).length}/${results.length}`} />
          </div>
          <Tabs tabs={["Overview", "File details", "Evaluation (ground truth)", "Exports"]} value={tab} onChange={setTab} />
          {tab === "Overview" && <OverviewTab results={results} />}
          {tab === "File details" && <FileTab results={results} />}
          {tab === "Evaluation (ground truth)" && <EvalTab runId={runId} results={results} />}
          {tab === "Exports" && <ExportsTab runId={runId} results={results} />}
        </div>
      )}
    </div>
  );
}
