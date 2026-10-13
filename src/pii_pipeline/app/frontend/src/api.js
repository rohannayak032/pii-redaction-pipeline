// Thin client for the Python API (server.py). All PII logic stays on the server.
async function json(res) {
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try { msg = (await res.json()).detail || msg; } catch { /* keep default */ }
    throw new Error(msg);
  }
  return res.json();
}

export const api = {
  config: () => fetch("/api/config").then(json),
  createRun: () => fetch("/api/runs", { method: "POST" }).then(json),
  deleteRun: (id) => fetch(`/api/runs/${id}`, { method: "DELETE" }).catch(() => {}),
  process: (runId, file) => {
    const fd = new FormData();
    fd.append("file", file, file.name);
    return fetch(`/api/runs/${runId}/process`, { method: "POST", body: fd }).then(json);
  },
  evaluate: (runId, file, partial, matchType) => {
    const fd = new FormData();
    fd.append("ground_truth", file, file.name);
    fd.append("partial", String(partial));
    fd.append("match_type", String(matchType));
    return fetch(`/api/runs/${runId}/evaluate`, { method: "POST", body: fd }).then(json);
  },
  url: (runId, path) => `/api/runs/${runId}/${path}`,
};

// ---- same pre-checks as pipeline.validate_file (shown before the run) ----
export async function precheck(file, cfg) {
  const dot = file.name.lastIndexOf(".");
  const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : "";
  const sizeKb = Math.round((file.size / 1024) * 10) / 10;
  const fail = (m) => ({ file, type: "-", sizeKb, ok: false, msg: m });
  if (!cfg) return { file, type: "…", sizeKb, ok: true, msg: "" };
  if (!(ext in cfg.types))
    return fail(`Unsupported file type '${ext || "none"}'. Supported: ${cfg.supported.join(", ")}`);
  if (file.size === 0) return fail("File is empty (0 bytes).");
  if (file.size > cfg.max_file_mb * 1024 * 1024) return fail(`File exceeds ${cfg.max_file_mb} MB limit.`);
  const type = cfg.types[ext];
  const head = new Uint8Array(await file.slice(0, 1024).arrayBuffer());
  if (type === "pdf") {
    let i = 0;
    while (i < head.length && [9, 10, 11, 12, 13, 32].includes(head[i])) i++;
    const sig = String.fromCharCode(...head.slice(i, i + 4));
    if (sig !== "%PDF") return fail("File has .pdf extension but is not a valid PDF.");
  }
  if ((type === "docx" || type === "pptx") && !(head[0] === 0x50 && head[1] === 0x4b))
    return fail(`File has .${type} extension but is not a valid Office file.`);
  return { file, type, sizeKb, ok: true, msg: "" };
}

export const failedStub = (filename, message) => ({
  index: -1, filename, file_type: "", status: "failed", error: message, failed_stage: "processing", risk: "N/A",
  llm_ready: false, aligned: true, pages: [], block_count: 0, categories: {}, warnings: [], leaks: [], timings: {},
  log: [`FAILED: ${message}`], backends: {}, entities: [], skipped_entities: [], redacted: [], placeholders: [],
  report: {}, teammate_report: null, teammate_report_note: "", non_pii_preserved: null, lowest_ocr: null,
});
