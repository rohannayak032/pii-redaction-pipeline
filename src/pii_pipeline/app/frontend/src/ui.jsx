import { useEffect, useRef, useState } from "react";

// ─── theme ───────────────────────────────────────────────────────────────────
const THEMES = [["light", "Light"], ["dark", "Dark"], ["system", "System"]];

export function useTheme() {
  const [mode, setMode] = useState(() => {
    try {
      const t = localStorage.getItem("pii-theme");
      return t === "light" || t === "dark" ? t : "system";
    } catch { return "system"; }
  });
  useEffect(() => {
    const el = document.documentElement;
    if (mode === "system") el.removeAttribute("data-theme");
    else el.dataset.theme = mode;
    try { mode === "system" ? localStorage.removeItem("pii-theme") : localStorage.setItem("pii-theme", mode); }
    catch { /* ignore */ }
  }, [mode]);
  return [mode, setMode];
}

const THEME_ICONS = {
  light: (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="5" />
      <line x1="12" y1="1" x2="12" y2="3" /><line x1="12" y1="21" x2="12" y2="23" />
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" /><line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
      <line x1="1" y1="12" x2="3" y2="12" /><line x1="21" y1="12" x2="23" y2="12" />
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" /><line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
    </svg>
  ),
  dark: (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  ),
  system: (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
      <line x1="8" y1="21" x2="16" y2="21" />
      <line x1="12" y1="17" x2="12" y2="21" />
    </svg>
  ),
};

export function ThemeSwitch({ mode, onChange }) {
  return (
    <div className="switch" role="radiogroup" aria-label="Theme">
      {THEMES.map(([k, label]) => (
        <button key={k} role="radio" aria-checked={mode === k} title={label} onClick={() => onChange(k)}>
          <span className="theme-icon">{THEME_ICONS[k]}</span>
          <span className="theme-label">{label}</span>
        </button>
      ))}
    </div>
  );
}

// ─── Metric card ─────────────────────────────────────────────────────────────
export function Metric({ label, value, help, accent, icon }) {
  return (
    <div className={`metric${accent ? " metric--accent" : ""}`}>
      <div className="metric-header">
        {icon && <span className="metric-icon">{icon}</span>}
        <span className="metric-label">{label}</span>
        {help && <span className="help" title={help}>?</span>}
      </div>
      <div className="metric-value">{value}</div>
    </div>
  );
}

// ─── Alert ───────────────────────────────────────────────────────────────────
const ALERT_ICONS = {
  success: (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  ),
  error: (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  ),
  warning: (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  ),
  info: (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="10" />
      <line x1="12" y1="16" x2="12" y2="12" /><line x1="12" y1="8" x2="12.01" y2="8" />
    </svg>
  ),
};

export function Alert({ kind = "info", children }) {
  return (
    <div className={`alert alert--${kind}`} role={kind === "error" ? "alert" : "status"}>
      <span className={`alert-icon alert-icon--${kind}`}>{ALERT_ICONS[kind]}</span>
      <div className="alert-body">{children}</div>
    </div>
  );
}

// ─── Tabs ─────────────────────────────────────────────────────────────────────
export function Tabs({ tabs, value, onChange, inner }) {
  return (
    <div className={`tabs${inner ? " tabs--inner" : ""}`} role="tablist">
      {tabs.map((t) => (
        <button key={t} role="tab" aria-selected={value === t} className="tab" onClick={() => onChange(t)}>
          {t}
        </button>
      ))}
    </div>
  );
}

// ─── Expander (details/summary) ───────────────────────────────────────────────
export function Expander({ title, children, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <details className="expander" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary className="expander-summary">{title}</summary>
      <div className="expander-body">{children}</div>
    </details>
  );
}

// ─── Select ───────────────────────────────────────────────────────────────────
export function Select({ label, value, onChange, options }) {
  return (
    <div className="field">
      {label && <label className="field-label">{label}</label>}
      <select className="select" value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  );
}

// ─── MultiSelect dropdown ─────────────────────────────────────────────────────
export function MultiSelect({ label, options, value, onChange }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);
  const toggle = (o) => onChange(value.includes(o) ? value.filter((x) => x !== o) : [...value, o]);
  const displayText = value.length ? value.join(", ") : <span className="placeholder-text">All</span>;
  return (
    <div className="field" ref={ref}>
      <label className="field-label">{label}</label>
      <div className="multiselect">
        <button type="button" className="multiselect-btn" onClick={() => setOpen(!open)} aria-expanded={open}>
          {displayText}
          <span className="multiselect-chevron">{open ? "▴" : "▾"}</span>
        </button>
        {open && (
          <div className="multiselect-popup">
            {options.length === 0
              ? <span className="multiselect-empty">No options</span>
              : options.map((o) => (
                <label key={o} className="multiselect-option">
                  <input type="checkbox" checked={value.includes(o)} onChange={() => toggle(o)} />
                  <span>{String(o)}</span>
                </label>
              ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Search input ─────────────────────────────────────────────────────────────
export function SearchInput({ value, onChange, placeholder = "Search…" }) {
  return (
    <div className="search-wrap">
      <span className="search-icon">⌕</span>
      <input
        type="search"
        className="search-input"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
      {value && (
        <button className="search-clear" onClick={() => onChange("")} title="Clear">✕</button>
      )}
    </div>
  );
}

// ─── DataTable ────────────────────────────────────────────────────────────────
// columns: [{key, label, render?, className?, expandable?}]
// expandRow?: (row) => React node — rendered when row is clicked
export function DataTable({ columns, rows, empty = "No results.", noMax, expandRow }) {
  const [expanded, setExpanded] = useState(null);
  const handleRowClick = (i) => {
    if (!expandRow) return;
    setExpanded(expanded === i ? null : i);
  };
  return (
    <div className={`tablewrap${noMax ? " tablewrap--nomax" : ""}`}>
      <table>
        <thead>
          <tr>
            {expandRow && <th style={{ width: 28, padding: "10px 6px" }} />}
            {columns.map((c) => <th key={c.key}>{c.label}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr><td colSpan={columns.length + (expandRow ? 1 : 0)} className="empty">{empty}</td></tr>
          )}
          {rows.map((r, i) => (
            <>
              <tr
                key={`row-${i}`}
                className={`${expandRow ? "row-clickable" : ""}${expanded === i ? " row-expanded" : ""}`}
                onClick={() => handleRowClick(i)}
              >
                {expandRow && (
                  <td className="row-toggle" style={{ padding: "9px 6px", textAlign: "center", color: "var(--muted)" }}>
                    {expanded === i ? "▾" : "▸"}
                  </td>
                )}
                {columns.map((c) => (
                  <td key={c.key} className={c.className || ""}>{c.render ? c.render(r) : r[c.key] ?? "-"}</td>
                ))}
              </tr>
              {expandRow && expanded === i && (
                <tr key={`exp-${i}`} className="row-detail">
                  <td colSpan={columns.length + 1} className="row-detail-cell">
                    {expandRow(r)}
                  </td>
                </tr>
              )}
            </>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── BarChart ─────────────────────────────────────────────────────────────────
export function BarChart({ data }) {
  const entries = Object.entries(data).sort(([, a], [, b]) => b - a);
  const max = Math.max(...entries.map(([, v]) => v), 1);
  return (
    <div className="barchart" role="img" aria-label="PII findings by category">
      <div className="barchart-bars">
        {entries.map(([k, v]) => (
          <div className="barchart-col" key={k}>
            <span className="barchart-count">{v}</span>
            <div className="barchart-bar" style={{ height: `${(v / max) * 100}%` }} />
            <span className="barchart-label">{k}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Badges ───────────────────────────────────────────────────────────────────
const STATUS_BADGE_MAP = {
  success:  ["badge--ok",   "Success"],
  warning:  ["badge--warn", "Warnings"],
  failed:   ["badge--err",  "Failed"],
  pending:  ["badge--info", "Pending"],
};
export const StatusBadge = ({ status }) => {
  const [cls, label] = STATUS_BADGE_MAP[status] || ["badge--info", status];
  return <span className={`badge ${cls}`}>{label}</span>;
};

const SEV_MAP = {
  High:   "badge--err",
  Medium: "badge--warn",
  Low:    "badge--ok",
};
export const SeverityBadge = ({ s }) => (
  <span className={`badge ${SEV_MAP[s] || "badge--ok"}`}>{s}</span>
);

export const RiskBadge = ({ risk }) => {
  const cls = risk === "High" ? "badge--err" : risk === "Medium" ? "badge--warn" : risk === "None found" ? "badge--ok" : "badge--info";
  return <span className={`badge ${cls}`}>{risk}</span>;
};

export const ClearedBadge = ({ ready }) => (
  <span className={`badge ${ready ? "badge--ok" : "badge--err"}`}>{ready ? "Cleared" : "Not cleared"}</span>
);

// ─── Sensitive value toggle ───────────────────────────────────────────────────
// Shows masked PII with per-row eye-toggle. Never logs values.
export function SensitiveValue({ value, available = true }) {
  const [revealed, setRevealed] = useState(false);
  if (!available || !value) {
    return <span className="muted" style={{ fontSize: "0.82rem" }}>— unavailable</span>;
  }
  return (
    <span className="sensitive-wrap">
      <span className={`sensitive-val${revealed ? " revealed" : ""}`}>
        {revealed ? value : "•".repeat(Math.min(value.length, 12))}
      </span>
      <button
        className="eye-btn"
        title={revealed ? "Hide value" : "Reveal value"}
        onClick={() => setRevealed((v) => !v)}
        type="button"
        aria-label={revealed ? "Hide PII value" : "Show PII value"}
      >
        {revealed ? (
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
            <line x1="1" y1="1" x2="23" y2="23" />
          </svg>
        ) : (
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
            <circle cx="12" cy="12" r="3" />
          </svg>
        )}
      </button>
    </span>
  );
}

// ─── Format a confidence float as percentage ──────────────────────────────────
export const pct = (x) => (x == null ? "n/a" : `${(x * 100).toFixed(1)}%`);
