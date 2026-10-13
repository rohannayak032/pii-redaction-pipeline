// Thin client for the Python API (server.py). All PII pipeline processing stays on the server.
async function json(res) {
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try { msg = (await res.json()).detail || msg; } catch { /* keep default */ }
    throw new Error(msg);
  }
  return res.json();
}

export const api = {
  // {max_file_mb, supported: [".pdf", ...], gt_columns: [...]} from the extraction and evaluation modules
  config: () => fetch("/api/config").then(json),
  createRun: () => fetch("/api/runs", { method: "POST" }).then(json),
  deleteRun: (id) => fetch(`/api/runs/${id}`, { method: "DELETE" }).catch(() => {}),
  process: (runId, file) => {
    const fd = new FormData();
    fd.append("file", file, file.name);
    return fetch(`/api/runs/${runId}/process`, { method: "POST", body: fd }).then(json);
  },
  evaluate: (runId, file, requireType, exact) => {
    const fd = new FormData();
    fd.append("ground_truth", file, file.name);
    fd.append("require_type", String(requireType));
    fd.append("exact", String(exact));
    return fetch(`/api/runs/${runId}/evaluate`, { method: "POST", body: fd }).then(json);
  },
};

/** Quick UX check before upload; the server and the extraction module validate again. */
export function precheck(file, cfg) {
  const dot = file.name.lastIndexOf(".");
  const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : "";
  const type = ext.slice(1);
  const fail = (msg) => ({ file, type, ok: false, msg });
  if (!cfg.supported.includes(ext)) {
    return fail(`Unsupported format '${ext || "none"}'. Supported: ${cfg.supported.join(", ")}.`);
  }
  if (file.size === 0) return fail("File is empty (0 bytes).");
  if (file.size > cfg.max_file_mb * 1024 * 1024) {
    return fail(`File size (${(file.size / (1024 * 1024)).toFixed(1)} MB) exceeds the ${cfg.max_file_mb} MB limit.`);
  }
  return { file, type, ok: true, msg: "Ready for analysis" };
}

// Shape of a server view-model for a file whose request itself failed (network / HTTP error).
export const failedStub = (filename, message) => ({
  index: -1,
  filename,
  file_type: "",
  sha256: "",
  status: "failed",
  error: message,
  failed_stage: "upload",
  llm_ready: false,
  block_count: 0,
  pages: [],
  timings: {},
  leaks: [],
  extraction: { warnings: [], sources: {}, kinds: {} },
  detectors: {},
  detected_types: {},
  entities: [],
  records: [],
  report: { findings: [], summary: { total_findings: 0, by_pii_type: {}, by_file: {} } },
  placeholders: [],
  redacted: [],
});
