import { useEffect, useRef, useState } from "react";

// ---------------- theme: light | dark | system ----------------
const THEMES = [["light", "☀️ Light"], ["dark", "🌙 Dark"], ["system", "💻 System"]];

export function useTheme() {
  const [mode, setMode] = useState(() => {
    try { const t = localStorage.getItem("pii-theme"); return t === "light" || t === "dark" ? t : "system"; }
    catch { return "system"; }
  });
  useEffect(() => {
    const el = document.documentElement;
    if (mode === "system") el.removeAttribute("data-theme"); // CSS follows prefers-color-scheme live
    else el.dataset.theme = mode;
    try { mode === "system" ? localStorage.removeItem("pii-theme") : localStorage.setItem("pii-theme", mode); } catch { /* ignore */ }
  }, [mode]);
  return [mode, setMode];
}

export function ThemeSwitch({ mode, onChange }) {
  return (
    <div className="switch" role="radiogroup" aria-label="Theme">
      {THEMES.map(([k, label]) => (
        <button key={k} role="radio" aria-checked={mode === k} onClick={() => onChange(k)}>{label}</button>
      ))}
    </div>
  );
}

// ---------------- small building blocks ----------------
export function Metric({ label, value, help }) {
  return (
    <div className="metric">
      <div className="l">{label}{help && <span className="help" title={help}>?</span>}</div>
      <div className="v">{value}</div>
    </div>
  );
}

export function Alert({ kind = "info", children }) {
  const icon = { success: "✅", error: "⛔", warning: "⚠️", info: "ℹ️" }[kind];
  return <div className={`alert ${kind}`} role={kind === "error" ? "alert" : undefined}><span>{icon}</span><div>{children}</div></div>;
}

export function Tabs({ tabs, value, onChange, inner }) {
  return (
    <div className={`tabs ${inner ? "inner" : ""}`} role="tablist">
      {tabs.map((t) => (
        <button key={t} role="tab" aria-selected={value === t} className="tab" onClick={() => onChange(t)}>{t}</button>
      ))}
    </div>
  );
}

export function Expander({ title, children }) {
  return (
    <details className="exp">
      <summary>{title}</summary>
      <div className="body">{children}</div>
    </details>
  );
}

export function Select({ label, value, onChange, options }) {
  return (
    <div className="field">
      {label && <label>{label}</label>}
      <select className="select" value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  );
}

export function MultiSelect({ label, options, value, onChange }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);
  const toggle = (o) => onChange(value.includes(o) ? value.filter((x) => x !== o) : [...value, o]);
  return (
    <div className="field" ref={ref}>
      <label>{label}</label>
      <div className="ms">
        <button type="button" className="ms-btn" onClick={() => setOpen(!open)} aria-expanded={open}>
          {value.length ? value.join(", ") : <span className="muted">All</span>}
        </button>
        {open && (
          <div className="ms-pop">
            {options.map((o) => (
              <label key={o}><input type="checkbox" checked={value.includes(o)} onChange={() => toggle(o)} />{String(o)}</label>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// columns: [{key, label, render?, className?}]
export function DataTable({ columns, rows, empty = "No rows.", noMax }) {
  return (
    <div className={`tablewrap ${noMax ? "nomax" : ""}`}>
      <table>
        <thead><tr>{columns.map((c) => <th key={c.key}>{c.label}</th>)}</tr></thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={columns.length} className="empty">{empty}</td></tr>}
          {rows.map((r, i) => (
            <tr key={i}>{columns.map((c) => (
              <td key={c.key} className={c.className || ""}>{c.render ? c.render(r) : r[c.key] ?? "-"}</td>
            ))}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function BarChart({ data }) {
  const entries = Object.entries(data);
  const max = Math.max(...entries.map(([, v]) => v), 1);
  return (
    <div className="chart" role="img" aria-label="PII findings by category">
      <div className="bars">
        {entries.map(([k, v]) => (
          <div className="bar" key={k}><b>{v}</b><i style={{ height: `${(v / max) * 82}%` }} /></div>
        ))}
      </div>
      <div className="xlabels">{entries.map(([k]) => <span key={k}>{k}</span>)}</div>
    </div>
  );
}

export const StatusBadge = ({ status }) => {
  const m = { success: ["b-ok", "Success"], warning: ["b-warn", "Warnings"], failed: ["b-err", "Failed"] }[status] || ["b-info", status];
  return <span className={`badge ${m[0]}`}>{m[1]}</span>;
};

export const SeverityBadge = ({ s }) => (
  <span className={`badge ${s === "High" ? "b-err" : s === "Medium" ? "b-warn" : "b-info"}`}>{s}</span>
);

export const pct = (x) => (x == null ? "n/a" : `${(x * 100).toFixed(1)}%`);
