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

  const changeTheme = (nextMode) => {
    if (nextMode === mode) return;

    const applyTheme = () => {
      setMode(nextMode);
      const el = document.documentElement;
      if (nextMode === "system") el.removeAttribute("data-theme");
      else el.dataset.theme = nextMode;
      try {
        nextMode === "system"
          ? localStorage.removeItem("pii-theme")
          : localStorage.setItem("pii-theme", nextMode);
      } catch { /* ignore */ }
    };

    const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (prefersReducedMotion) {
      applyTheme();
      return;
    }

    const targetDark =
      nextMode === "dark" ||
      (nextMode === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
    const targetThemeName = targetDark ? "dark" : "light";

    // Broadcast event for laser sweep and collision burst animation
    window.dispatchEvent(
      new CustomEvent("pii-theme-transition", {
        detail: {
          targetTheme: targetThemeName,
          hasViewTransition: typeof document.startViewTransition === "function",
        },
      })
    );

    if (typeof document.startViewTransition === "function") {
      document.documentElement.classList.add("theme-transitioning");
      const transition = document.startViewTransition(() => {
        applyTheme();
      });
      transition.finished.finally(() => {
        document.documentElement.classList.remove("theme-transitioning");
      });
    } else {
      setTimeout(() => {
        applyTheme();
      }, 320);
    }
  };

  useEffect(() => {
    const el = document.documentElement;
    if (mode === "system") el.removeAttribute("data-theme");
    else el.dataset.theme = mode;
  }, []);

  return [mode, changeTheme];
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

// ─── Dynamic Cybersecurity Background ─────────────────────────────────────────
// Renders an ambient animated network mesh with drifting defense nodes,
// data packet pings, and glowing aura behind the application.
export function DynamicBackground() {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animId = null;
    let width = 0;
    let height = 0;
    let particles = [];
    const mouse = { x: null, y: null, active: false };

    const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const isDarkTheme = () => {
      const themeAttr = document.documentElement.getAttribute("data-theme");
      if (themeAttr === "dark") return true;
      if (themeAttr === "light") return false;
      return window.matchMedia("(prefers-color-scheme: dark)").matches;
    };

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = window.innerWidth;
      height = window.innerHeight;
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      const count = Math.min(65, Math.max(24, Math.floor((width * height) / 28000)));
      particles = [];
      for (let i = 0; i < count; i++) {
        particles.push({
          x: Math.random() * width,
          y: Math.random() * height,
          vx: (Math.random() - 0.5) * 0.42,
          vy: (Math.random() - 0.5) * 0.42,
          radius: Math.random() * 1.5 + 1.2,
          isCyan: Math.random() > 0.35,
          pulse: Math.random() * Math.PI * 2,
          pulseSpeed: 0.02 + Math.random() * 0.02,
        });
      }
    };

    resize();
    window.addEventListener("resize", resize, { passive: true });

    const onMouseMove = (e) => {
      mouse.x = e.clientX;
      mouse.y = e.clientY;
      mouse.active = true;
    };

    const onMouseLeave = () => {
      mouse.active = false;
      mouse.x = null;
      mouse.y = null;
    };

    const onTouchMove = (e) => {
      if (e.touches && e.touches[0]) {
        mouse.x = e.touches[0].clientX;
        mouse.y = e.touches[0].clientY;
        mouse.active = true;
      }
    };

    const onTouchEnd = () => {
      mouse.active = false;
      mouse.x = null;
      mouse.y = null;
    };

    window.addEventListener("mousemove", onMouseMove, { passive: true });
    window.addEventListener("mouseleave", onMouseLeave, { passive: true });
    window.addEventListener("touchmove", onTouchMove, { passive: true });
    window.addEventListener("touchend", onTouchEnd, { passive: true });

    const maxDist = 125;
    const maxDistSq = maxDist * maxDist;
    const mouseRadius = 150;

    const render = (time) => {
      const dark = isDarkTheme();
      ctx.clearRect(0, 0, width, height);

      const cyanRGB = dark ? "34, 211, 238" : "8, 145, 178";
      const indigoRGB = dark ? "99, 102, 241" : "99, 102, 241";

      const len = particles.length;
      for (let i = 0; i < len; i++) {
        const p = particles[i];
        if (!prefersReducedMotion) {
          p.x += p.vx;
          p.y += p.vy;
          p.pulse += p.pulseSpeed;

          if (p.x < -10) p.x = width + 10;
          else if (p.x > width + 10) p.x = -10;
          if (p.y < -10) p.y = height + 10;
          else if (p.y > height + 10) p.y = -10;

          if (mouse.active && mouse.x !== null) {
            const dx = mouse.x - p.x;
            const dy = mouse.y - p.y;
            const dist = Math.hypot(dx, dy);
            if (dist < mouseRadius && dist > 0) {
              const force = (1 - dist / mouseRadius) * 0.06;
              p.x += dx * force;
              p.y += dy * force;
            }
          }
        }

        const rgb = p.isCyan ? cyanRGB : indigoRGB;
        const pulseAlpha = Math.sin(p.pulse) * 0.2 + 0.6;
        const alpha = dark ? (p.isCyan ? 0.38 * pulseAlpha : 0.25 * pulseAlpha) : 0.22 * pulseAlpha;

        ctx.beginPath();
        ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${rgb}, ${alpha})`;
        ctx.fill();

        if (p.isCyan && dark) {
          ctx.beginPath();
          ctx.arc(p.x, p.y, p.radius * 2, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(${cyanRGB}, ${alpha * 0.16})`;
          ctx.fill();
        }
      }

      for (let i = 0; i < len; i++) {
        const p1 = particles[i];
        for (let j = i + 1; j < len; j++) {
          const p2 = particles[j];
          const dx = p1.x - p2.x;
          if (Math.abs(dx) > maxDist) continue;
          const dy = p1.y - p2.y;
          if (Math.abs(dy) > maxDist) continue;

          const distSq = dx * dx + dy * dy;
          if (distSq < maxDistSq) {
            const dist = Math.sqrt(distSq);
            const ratio = 1 - dist / maxDist;
            const lineAlpha = (dark ? 0.15 : 0.09) * ratio * ratio;

            ctx.beginPath();
            ctx.moveTo(p1.x, p1.y);
            ctx.lineTo(p2.x, p2.y);
            ctx.strokeStyle = `rgba(${cyanRGB}, ${lineAlpha})`;
            ctx.lineWidth = 0.85;
            ctx.stroke();

            if (!prefersReducedMotion && (i + j) % 6 === 0) {
              const t = ((time * 0.00075 + (i * 0.25)) % 1);
              const packetX = p1.x + (p2.x - p1.x) * t;
              const packetY = p1.y + (p2.y - p1.y) * t;
              const packetAlpha = (dark ? 0.55 : 0.35) * ratio;
              ctx.beginPath();
              ctx.arc(packetX, packetY, 1.3, 0, Math.PI * 2);
              ctx.fillStyle = `rgba(${cyanRGB}, ${packetAlpha})`;
              ctx.fill();
            }
          }
        }

        if (mouse.active && mouse.x !== null) {
          const dx = p1.x - mouse.x;
          const dy = p1.y - mouse.y;
          const dist = Math.hypot(dx, dy);
          if (dist < mouseRadius) {
            const ratio = 1 - dist / mouseRadius;
            const lineAlpha = (dark ? 0.25 : 0.15) * ratio;
            ctx.beginPath();
            ctx.moveTo(p1.x, p1.y);
            ctx.lineTo(mouse.x, mouse.y);
            ctx.strokeStyle = `rgba(${cyanRGB}, ${lineAlpha})`;
            ctx.lineWidth = 0.9;
            ctx.stroke();
          }
        }
      }

      if (!prefersReducedMotion) {
        animId = requestAnimationFrame(render);
      }
    };

    if (prefersReducedMotion) {
      render(0);
    } else {
      animId = requestAnimationFrame(render);
    }

    const onVisibilityChange = () => {
      if (document.hidden) {
        if (animId) cancelAnimationFrame(animId);
      } else if (!prefersReducedMotion) {
        animId = requestAnimationFrame(render);
      }
    };

    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      if (animId) cancelAnimationFrame(animId);
      window.removeEventListener("resize", resize);
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseleave", onMouseLeave);
      window.removeEventListener("touchmove", onTouchMove);
      window.removeEventListener("touchend", onTouchEnd);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, []);

  return (
    <div className="dynamic-bg" aria-hidden="true">
      <div className="dynamic-bg-glow glow-cyan" />
      <div className="dynamic-bg-glow glow-indigo" />
      <div className="dynamic-bg-grid" />
      <canvas ref={canvasRef} className="dynamic-bg-canvas" />
    </div>
  );
}

// ─── Theme Transition Beams & Collision Overlay ──────────────────────────────
// Renders dual laser blades and cyber curtains sweeping from the left and
// right edges, colliding in the middle with an Electric Cyan burst.
export function ThemeTransitionBeams() {
  const [transitionState, setTransitionState] = useState(null);

  useEffect(() => {
    const handleTransition = (e) => {
      const { targetTheme, hasViewTransition } = e.detail || {};
      setTransitionState({ targetTheme, hasViewTransition, id: Date.now() });
    };

    window.addEventListener("pii-theme-transition", handleTransition);
    return () => window.removeEventListener("pii-theme-transition", handleTransition);
  }, []);

  useEffect(() => {
    if (!transitionState) return;
    const timer = setTimeout(() => {
      setTransitionState(null);
    }, 950);
    return () => clearTimeout(timer);
  }, [transitionState]);

  if (!transitionState) return null;

  const { targetTheme, hasViewTransition, id } = transitionState;

  return (
    <div key={id} className={`theme-sweep-container target-${targetTheme}`} aria-hidden="true">
      {/* Fallback curtains for browsers without native View Transitions */}
      {!hasViewTransition && (
        <>
          <div className="theme-curtain curtain-left" />
          <div className="theme-curtain curtain-right" />
        </>
      )}

      {/* Dual laser blades sweeping inward */}
      <div className="theme-laser-blade laser-left" />
      <div className="theme-laser-blade laser-right" />

      {/* Collision pulse and spark line down the middle */}
      <div className="theme-collision-line" />
      <div className="theme-collision-burst" />
    </div>
  );
}

// ─── Cyber Brand Shield Logo ──────────────────────────────────────────────────
// High-tech faceted cybersecurity shield with dual armor plates, cryptographic
// lock shackle, central data sanitization beam, and circuit traces.
export function BrandShield({ size = 28 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className="brand-shield-icon"
      aria-hidden="true"
    >
      <defs>
        {/* Outer Shield Rim Gradient: Electric Cyan to Indigo */}
        <linearGradient id="shieldRimGrad" x1="4" y1="2" x2="28" y2="30" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#22D3EE" />
          <stop offset="45%" stopColor="#38BDF8" />
          <stop offset="100%" stopColor="#6366F1" />
        </linearGradient>

        {/* Left Armor Plate (Deep Midnight with Cyan Hue) */}
        <linearGradient id="shieldPlateL" x1="6" y1="4" x2="16" y2="28" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#1E2E48" />
          <stop offset="100%" stopColor="#0B1320" />
        </linearGradient>

        {/* Right Armor Plate (Specular Bevel Reflection) */}
        <linearGradient id="shieldPlateR" x1="16" y1="4" x2="26" y2="28" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#2F4468" />
          <stop offset="50%" stopColor="#1C2D46" />
          <stop offset="100%" stopColor="#0E1827" />
        </linearGradient>

        {/* Core Chip Redaction Bar Gradient */}
        <linearGradient id="coreBeamGrad" x1="12" y1="16" x2="20" y2="16" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#67E8F9" />
          <stop offset="100%" stopColor="#22D3EE" />
        </linearGradient>
      </defs>

      {/* Outer Shield Beveled Contour / Cyber Armor Rim */}
      <path
        d="M16 2.5 L27 6.5 V14.5 C27 21.8 22.2 26.8 16 29.5 C9.8 26.8 5 21.8 5 14.5 V6.5 L16 2.5 Z"
        stroke="url(#shieldRimGrad)"
        strokeWidth="1.75"
        strokeLinejoin="round"
      />

      {/* Left Armor Plate */}
      <path
        d="M16 3.8 L6.5 7.2 V14.5 C6.5 21 10.8 25.5 16 28 V3.8 Z"
        fill="url(#shieldPlateL)"
      />

      {/* Right Armor Plate */}
      <path
        d="M16 3.8 L25.5 7.2 V14.5 C25.5 21 21.2 25.5 16 28 V3.8 Z"
        fill="url(#shieldPlateR)"
      />

      {/* Center Spine Crease Line */}
      <line x1="16" y1="3.8" x2="16" y2="28" stroke="rgba(34, 211, 238, 0.45)" strokeWidth="0.8" />

      {/* Cryptographic Lock Arch / Upper Perimeter Sensor */}
      <path
        d="M13.2 13.5 V10.8 C13.2 9.25 14.45 8 16 8 C17.55 8 18.8 9.25 18.8 10.8 V13.5"
        stroke="#22D3EE"
        strokeWidth="1.35"
        strokeLinecap="round"
      />

      {/* Central Redaction Core Chip */}
      <rect
        x="10.5"
        y="13.5"
        width="11"
        height="7"
        rx="1.5"
        fill="#080F1B"
        stroke="url(#shieldRimGrad)"
        strokeWidth="1.15"
      />

      {/* Active PII Sanitization / Redaction Beam */}
      <rect x="12" y="16.2" width="8" height="1.6" rx="0.8" fill="url(#coreBeamGrad)" />

      {/* High-Tech Optical Sensor Node / Keyhole Center */}
      <circle cx="16" cy="17" r="1.1" fill="#FFFFFF" />

      {/* Lower Defense Circuit Trace */}
      <path
        d="M16 20.5 V24.8 M13.8 22.8 L16 24.8 L18.2 22.8"
        stroke="#22D3EE"
        strokeWidth="1.15"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.9"
      />

      {/* Corner Circuit Radar Dots */}
      <circle cx="9.2" cy="10.2" r="0.8" fill="#22D3EE" opacity="0.85" />
      <circle cx="22.8" cy="10.2" r="0.8" fill="#22D3EE" opacity="0.85" />
    </svg>
  );
}

