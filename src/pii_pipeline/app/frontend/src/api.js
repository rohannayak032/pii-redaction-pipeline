// Thin client for the Python API (server.py). All PII pipeline processing stays on the server.
async function json(res) {
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try { msg = (await res.json()).detail || msg; } catch { /* keep default */ }
    throw new Error(msg);
  }
  return res.json();
}

export const ALLOWED_FORMATS = {
  ".pdf": "pdf",
  ".docx": "docx",
  ".pptx": "pptx",
  ".txt": "txt",
};

export const ALLOWED_EXTENSIONS = Object.keys(ALLOWED_FORMATS);
export const ALLOWED_MIME_TYPES = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "text/plain",
];

export const MAX_FILE_SIZE_MB = 25;

export const api = {
  config: async () => {
    try {
      const cfg = await fetch("/api/config").then(json);
      return {
        ...cfg,
        max_file_mb: cfg.max_file_mb || MAX_FILE_SIZE_MB,
        // Restrict supported types strictly to the 4 approved enterprise formats
        supported: ALLOWED_EXTENSIONS,
        types: ALLOWED_FORMATS,
      };
    } catch {
      return {
        max_file_mb: MAX_FILE_SIZE_MB,
        supported: ALLOWED_EXTENSIONS,
        types: ALLOWED_FORMATS,
      };
    }
  },
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

/**
 * Strict frontend pre-check enforcing allowed document formats (PDF, DOCX, PPTX, TXT)
 * and magic byte signatures before sending to pipeline.
 *
 * NOTE: Frontend pre-validation provides immediate UX feedback and does not replace
 * backend server-side validation.
 */
export async function precheck(file, cfg) {
  const dot = file.name.lastIndexOf(".");
  const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : "";
  const sizeKb = Math.round((file.size / 1024) * 10) / 10;
  const maxMb = cfg?.max_file_mb ?? MAX_FILE_SIZE_MB;
  const maxBytes = maxMb * 1024 * 1024;
  const fail = (m) => ({ file, type: "-", sizeKb, ok: false, msg: m, ext });

  // Strict format enforcement: only PDF, DOCX, PPTX, TXT allowed
  if (!ALLOWED_FORMATS[ext]) {
    const rejectedList = [".png", ".jpg", ".jpeg", ".tif", ".tiff"];
    const isImage = rejectedList.includes(ext);
    return fail(
      isImage
        ? `Image formats (${ext}) are not supported. Upload PDF, DOCX, PPTX, or TXT documents only.`
        : `Unsupported format '${ext || "unknown"}'. Only PDF (.pdf), Word (.docx), PowerPoint (.pptx), and Plain Text (.txt) are accepted.`
    );
  }

  if (file.size === 0) {
    return fail("File is empty (0 bytes).");
  }

  if (file.size > maxBytes) {
    return fail(`File size (${(file.size / (1024 * 1024)).toFixed(1)} MB) exceeds the ${maxMb} MB limit.`);
  }

  const type = ALLOWED_FORMATS[ext];

  try {
    const head = new Uint8Array(await file.slice(0, 1024).arrayBuffer());
    if (type === "pdf") {
      let i = 0;
      while (i < head.length && [9, 10, 11, 12, 13, 32].includes(head[i])) i++;
      const sig = String.fromCharCode(...head.slice(i, i + 4));
      if (sig !== "%PDF") {
        return fail("File has .pdf extension but does not contain a valid %PDF header.");
      }
    } else if (type === "docx" || type === "pptx") {
      // Office Open XML zip signature: PK\x03\x04
      if (head.length < 4 || !(head[0] === 0x50 && head[1] === 0x4b)) {
        return fail(`File has .${type} extension but is not a valid Microsoft Office Open XML package.`);
      }
    }
  } catch {
    return fail("Unable to read file header for verification.");
  }

  return { file, type, sizeKb, ok: true, msg: "Ready for analysis", ext };
}

/**
 * Temporary, in-memory association of detected entities with original values.
 *
 * Privacy Architecture:
 * 1. Checks if the backend API response already provided raw value fields (e.g. value, original_value).
 * 2. If the document is plain text (.txt) uploaded in the current session, correlates entity block
 *    and [start, end] offsets against the in-memory File buffer without transmitting raw PII.
 * 3. For binary formats (.pdf, .docx, .pptx) where the backend strictly keeps raw PII inside the
 *    server process for zero-trust protection, records that status accurately without fabricating data.
 * 4. Stored strictly in ephemeral React state during the current session — NEVER persisted to
 *    localStorage, sessionStorage, IndexedDB, or transmitted in analytics.
 */
export async function correlateOriginalValues(fileObj, serverResult) {
  const entityMap = new Map(); // entityKey -> originalValue
  const placeholderMap = new Map(); // placeholder -> originalValue
  const fileType = serverResult.file_type || (fileObj.name.endsWith(".txt") ? "txt" : "");

  let isClientExtracted = false;
  let textBlocks = [];

  if (fileType === "txt" && fileObj) {
    try {
      const rawText = await fileObj.text();
      // Backend extraction splits on \n\s*\n into paragraph blocks
      textBlocks = rawText.split(/\r?\n\s*\r?\n/);
      isClientExtracted = true;
    } catch {
      // In-memory read failed or file unreadable
    }
  }

  const entities = serverResult.entities || [];

  for (const ent of entities) {
    let original = null;

    // 1. Direct API response inspection
    if (ent.value && typeof ent.value === "string") {
      original = ent.value;
    } else if (ent.original_value && typeof ent.original_value === "string") {
      original = ent.original_value;
    } else if (ent.text && typeof ent.text === "string") {
      original = ent.text;
    }

    // 2. Client-side extraction for plain text documents
    if (!original && isClientExtracted && ent.block >= 1 && ent.start >= 0 && ent.end > ent.start) {
      const bIdx = ent.block - 1;
      if (bIdx < textBlocks.length) {
        const blkText = textBlocks[bIdx];
        if (ent.end <= blkText.length) {
          const slice = blkText.slice(ent.start, ent.end);
          if (slice && slice.trim().length > 0) {
            original = slice;
          }
        }
      }
    }

    // 3. Fallback to existing placeholder mapping for repeated tokens
    if (!original && ent.placeholder && placeholderMap.has(ent.placeholder)) {
      original = placeholderMap.get(ent.placeholder);
    }

    if (original) {
      const entityKey = `${serverResult.filename}::${ent.n || ent.placeholder || ent.block + "_" + ent.start}`;
      entityMap.set(entityKey, original);
      if (ent.placeholder) {
        placeholderMap.set(ent.placeholder, original);
      }
    }
  }

  return {
    filename: serverResult.filename,
    entityMap,
    placeholderMap,
    isClientExtracted,
  };
}

export const failedStub = (filename, message) => ({
  index: -1,
  filename,
  file_type: "",
  status: "failed",
  error: message,
  failed_stage: "processing",
  risk: "N/A",
  llm_ready: false,
  aligned: true,
  pages: [],
  block_count: 0,
  categories: {},
  warnings: [],
  leaks: [],
  timings: {},
  log: [`FAILED: ${message}`],
  backends: {},
  entities: [],
  skipped_entities: [],
  redacted: [],
  placeholders: [],
  report: {},
  teammate_report: null,
  teammate_report_note: "",
  non_pii_preserved: null,
  lowest_ocr: null,
});
