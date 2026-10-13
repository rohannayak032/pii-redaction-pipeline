"""
pipeline.py - workflow layer (Application role)
===============================================
process_document(filename, data, settings) runs:
    validate -> route -> Extraction -> Detection -> Redaction -> verify -> DocResult

* Teammates' objects (TextBlock / Entity / RedactedBlock) are passed through UNCHANGED; this module only
  reads them with tolerant getters to build its own view-model for the UI.
* Raw PII (Ent.value) lives only in memory for redaction/verification. It is never logged, printed,
  returned by to_report(), or shown by the UI.
"""
from __future__ import annotations

import copy
import dataclasses
import difflib
import hashlib
import importlib
import inspect
import os
import re
import shutil
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    from . import backend_config as cfg
    from . import mock_modules as mock
except ImportError:                      # running as a plain script (streamlit run app.py)
    import backend_config as cfg
    import mock_modules as mock

PLACEHOLDER_RE = re.compile(r"\[[A-Z][A-Z_]*_\d+\]")
_BIG = 10 ** 9


# ----------------------------------------------------------------- view model
@dataclass
class Blk:
    pos: int
    key: Any
    file: str
    location: str
    page: int
    text: str
    ocr_confidence: Optional[float] = None
    raw: Any = field(default=None, repr=False)


@dataclass
class Ent:
    block: int                      # position in DocResult.blocks, -1 = could not be resolved
    entity_type: str
    start: int                      # offset inside the block text (-1 = unknown)
    end: int
    confidence: float
    detector: str
    page: int = 1
    location: str = ""
    placeholder: str = ""
    value: str = field(default="", repr=False)    # RAW PII - internal only
    raw: Any = field(default=None, repr=False)

    @property
    def severity(self) -> str:
        return severity_of(self.entity_type)

    def public(self) -> dict:
        return {"entity_type": self.entity_type, "severity": self.severity, "block": self.block + 1,
                "page": self.page, "location": self.location,
                "start": self.start if self.start >= 0 else None,
                "end": self.end if self.start >= 0 else None,
                "confidence": round(self.confidence, 3), "detector": self.detector,
                "placeholder": self.placeholder}


@dataclass
class Settings:
    force_mock: bool = False
    strict_real: bool = False
    min_confidence: float = 0.0


@dataclass
class DocResult:
    filename: str
    file_type: str = ""
    size_bytes: int = 0
    sha256: str = ""
    status: str = "pending"          # success | warning | failed
    error: str = ""
    failed_stage: str = ""
    blocks: List[Blk] = field(default_factory=list)
    redacted_texts: List[str] = field(default_factory=list)
    aligned: bool = True             # redacted_texts line up 1:1 with blocks
    entities: List[Ent] = field(default_factory=list)
    skipped_entities: List[Ent] = field(default_factory=list)
    teammate_report: Any = None      # report object returned by the redaction module (scrubbed before display)
    warnings: List[str] = field(default_factory=list)
    leaks: List[str] = field(default_factory=list)
    backends: Dict[str, str] = field(default_factory=dict)
    timings: Dict[str, float] = field(default_factory=dict)
    log: List[str] = field(default_factory=list)

    @property
    def llm_ready(self) -> bool:
        return self.status in ("success", "warning") and not self.leaks and bool(self.redacted_texts)

    @property
    def risk(self) -> str:
        if self.status == "failed":
            return "N/A"
        if not self.entities:
            return "None found"
        for level in ("High", "Medium"):
            if any(e.severity == level for e in self.entities):
                return level
        return "Low"

    @property
    def pages(self) -> List[int]:
        return sorted({b.page for b in self.blocks})

    def by_category(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for e in self.entities:
            out[e.entity_type] = out.get(e.entity_type, 0) + 1
        return out

    def redacted_text(self) -> str:
        if self.aligned:
            parts, last = [], None
            for b, t in zip(self.blocks, self.redacted_texts):
                if b.page != last and len(self.pages) > 1:
                    parts.append(f"=== Page/Slide {b.page} ===")
                    last = b.page
                parts.append(t)
            return "\n".join(parts)
        return "\n".join(self.redacted_texts)

    def to_report(self) -> dict:
        """Exposure report: type, location, confidence - never raw values."""
        return {
            "filename": self.filename, "file_type": self.file_type, "sha256": self.sha256,
            "status": self.status, "error": self.error, "risk": self.risk,
            "cleared_for_llm": self.llm_ready, "blocks": len(self.blocks), "pages": len(self.pages),
            "categories": self.by_category(), "warnings": self.warnings, "leaks": self.leaks,
            "backends": self.backends, "timings_sec": self.timings,
            "findings": [e.public() for e in self.entities],
            "below_threshold_not_redacted": [e.public() for e in self.skipped_entities],
        }


class PipelineError(Exception):
    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage


# ----------------------------------------------------------------- small helpers
def norm_type(t: Any) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", str(t or "UNKNOWN").strip()).strip("_").upper() or "UNKNOWN"


def severity_of(entity_type: str) -> str:
    t = norm_type(entity_type)
    return "High" if t in cfg.HIGH_SEVERITY else "Medium" if t in cfg.MEDIUM_SEVERITY else "Low"


def _norm_value(text: str) -> str:
    t = re.sub(r"\s+", " ", str(text).strip().lower())
    digits = re.sub(r"\D", "", t)
    return digits if len(digits) >= 6 else t


def _get(obj: Any, *names: str, default: Any = None) -> Any:
    for n in names:
        if isinstance(obj, dict):
            if obj.get(n) is not None:
                return obj[n]
        elif getattr(obj, n, None) is not None:
            return getattr(obj, n)
    return default


def _invoke(fn: Callable, *args: Any) -> Any:
    """Call fn with as many positional args as it accepts."""
    try:
        params = list(inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):
        return fn(*args)
    if any(p.kind == p.VAR_POSITIONAL for p in params):
        return fn(*args)
    n = len([p for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)])
    return fn(*args[:n])


def _short(e: Exception) -> str:
    return f"{type(e).__name__}: {str(e)[:160]}"


def _loc_str(loc: Any) -> str:
    if loc is None:
        return ""
    if isinstance(loc, str):
        return loc[:80]
    try:
        d = dataclasses.asdict(loc) if dataclasses.is_dataclass(loc) and not isinstance(loc, type) else (
            loc if isinstance(loc, dict) else dict(vars(loc)))
        return ", ".join(f"{k}={v}" for k, v in d.items() if v is not None)[:80]
    except Exception:
        return str(loc)[:80]


def _page_of(item: Any, loc_raw: Any, loc_s: str) -> int:
    for src in (item, loc_raw):
        if src is not None and not isinstance(src, str):
            p = _get(src, "page", "page_number", "slide", "page_no")
            try:
                if p is not None:
                    return int(p)
            except (TypeError, ValueError):
                pass
    m = re.search(r"(?:page|slide|p\.?)\s*=?\s*(\d+)", loc_s, re.I)
    return int(m.group(1)) if m else 1


# ----------------------------------------------------------------- backend loading
def _resolve(stage: str, file_type: Optional[str]) -> Tuple[Optional[Callable], str, str]:
    spec = cfg.BACKEND[stage]
    if stage == "extraction" and file_type in cfg.EXTRACTION_BY_TYPE:
        spec = cfg.EXTRACTION_BY_TYPE[file_type]
    importlib.invalidate_caches()
    problems = []
    for modname in spec["modules"]:
        try:
            mod = importlib.import_module(modname)
        except ModuleNotFoundError as e:
            if e.name and (modname == e.name or modname.startswith(e.name + ".")):
                problems.append(f"{modname} not found")
                continue
            raise PipelineError(stage, f"{modname} failed to import: missing dependency '{e.name}'")
        except Exception as e:
            raise PipelineError(stage, f"{modname} failed to import ({type(e).__name__})")
        for fname in spec["functions"]:
            fn = getattr(mod, fname, None)
            if callable(fn):
                return fn, f"real: {modname}.{fname}", ""
        problems.append(f"{modname} has none of {spec['functions']}")
    return None, "", "; ".join(problems)


def load_backend(stage: str, file_type: Optional[str], settings: Settings) -> Tuple[Optional[Callable], str]:
    mock_fn = {"extraction": mock.extract_document, "detection": mock.detect_pii}.get(stage)
    if settings.force_mock:
        return mock_fn, "mock" if mock_fn else "builtin"
    fn, label, problem = _resolve(stage, file_type)
    if fn is not None:
        return fn, label
    if settings.strict_real:
        raise PipelineError(stage, f"Strict mode: real backend unavailable ({problem}).")
    return mock_fn, (f"mock ({problem})" if mock_fn else f"builtin ({problem})")


def backend_status(settings: Settings) -> List[dict]:
    rows = []
    for stage, name in (("extraction", "Extraction"), ("detection", "PII detection"),
                        ("redaction", "Redaction & traceability")):
        try:
            _, label = load_backend(stage, None, settings)
        except PipelineError as e:
            label = f"ERROR: {e}"
        rows.append({"Stage": name, "Active backend": label})
    return rows


# ----------------------------------------------------------------- normalisers
def normalize_blocks(raw: Any, filename: str) -> Tuple[List[Blk], List[str]]:
    warnings: List[str] = []
    if isinstance(raw, dict) or not isinstance(raw, (str, list, tuple)):
        if raw is None:
            raise PipelineError("extraction", "Extraction returned nothing.")
        warnings = [str(w) for w in (_get(raw, "warnings", default=[]) or [])]
        inner = _get(raw, "blocks", "text_blocks", "pages", "slides", default=None)
        raw = inner if inner is not None else _get(raw, "text", "content", default="")
    if isinstance(raw, str):
        raw = [raw]
    blocks: List[Blk] = []
    for i, item in enumerate(raw):
        if isinstance(item, str):
            item = mock.MockBlock(filename, f"block {i + 1}", i, item)
        text = _get(item, "text", "content", default=None)
        if text is None:
            raise PipelineError("extraction", f"Block {i + 1} has no text field ({type(item).__name__}).")
        loc_raw = _get(item, "location", "loc", "position")
        loc = _loc_str(loc_raw)
        ocr = _get(item, "ocr_confidence")
        try:
            ocr = float(ocr) if ocr is not None else None
        except (TypeError, ValueError):
            ocr = None
        blocks.append(Blk(pos=i, key=_get(item, "block_id", "id", "index", "block_index", "order",
                                          "reading_order", default=i),
                          file=str(_get(item, "file", "filename", "source_file", default=filename)),
                          location=loc or f"block {i + 1}", page=_page_of(item, loc_raw, loc),
                          text=str(text), ocr_confidence=ocr, raw=item))
    return blocks, warnings


def normalize_entities(raw: Any, blocks: List[Blk]) -> Tuple[List[Ent], int]:
    """Returns (entities, number that needed relocation / could not be placed)."""
    if raw is None:
        return [], 0
    if isinstance(raw, dict) or not isinstance(raw, (list, tuple)):
        raw = _get(raw, "entities", "findings", default=[])
    key2pos = {str(b.key): b.pos for b in blocks}
    taken: Dict[int, List[Tuple[int, int]]] = {b.pos: [] for b in blocks}
    out: List[Ent] = []
    problems = 0

    def free(pos, s, e):
        return all(e <= a or s >= z for a, z in taken[pos])

    for r in raw:
        etype = norm_type(_get(r, "entity_type", "type", "label", "category", "pii_type", default="UNKNOWN"))
        value = _get(r, "value", "text", "match", "raw", default="")
        value = value if isinstance(value, str) else str(value)
        s, e = _get(r, "start", "start_char", "begin"), _get(r, "end", "end_char", "stop")
        try:
            s, e = (int(s), int(e)) if s is not None and e is not None else (-1, -1)
        except (TypeError, ValueError):
            s, e = -1, -1
        try:
            conf = float(_get(r, "confidence", "score", default=1.0))
        except (TypeError, ValueError):
            conf = 1.0
        det = str(_get(r, "detector", "method", "source", default="unknown"))
        ref = _get(r, "block_id", "block_index", "block_idx", "block", "text_block")
        if ref is not None and not isinstance(ref, (int, str)):
            ref = _get(ref, "block_id", "id", "index", "order")
        pos = key2pos.get(str(ref)) if ref is not None else None
        if pos is None and isinstance(ref, int) and 0 <= ref < len(blocks):
            pos = ref
        if pos is None and len(blocks) == 1:
            pos = 0
        # offsets valid?
        if pos is not None and 0 <= s < e <= len(blocks[pos].text):
            if not value:
                value = blocks[pos].text[s:e]
            if blocks[pos].text[s:e] != value:
                s = -1
        elif pos is not None:
            s = -1
        if not value:
            continue
        if s < 0 or pos is None:                  # try to relocate by value
            problems += 1
            cand = [pos] if pos is not None else [b.pos for b in blocks]
            pos, s2 = None, -1
            for p in cand:
                i = 0
                while True:
                    i = blocks[p].text.find(value, i)
                    if i < 0:
                        break
                    if free(p, i, i + len(value)):
                        pos, s2 = p, i
                        break
                    i += 1
                if pos is not None:
                    break
            s = s2
            e = s + len(value) if s >= 0 else -1
        if pos is not None and s >= 0:
            taken[pos].append((s, e))
        b = blocks[pos] if pos is not None else None
        out.append(Ent(block=pos if pos is not None else -1, entity_type=etype, start=s, end=e,
                       confidence=conf, detector=det, page=b.page if b else 1,
                       location=b.location if b else "unplaced",
                       placeholder=str(_get(r, "placeholder", "replacement", default="") or ""),
                       value=value, raw=r))
    out.sort(key=lambda x: (x.block if x.block >= 0 else _BIG, x.start if x.start >= 0 else _BIG))
    return out, problems


def _resolve_overlaps(ents: List[Ent]) -> List[Ent]:
    kept: List[Ent] = []
    for e in sorted(ents, key=lambda x: (-(x.end - x.start), -x.confidence)):
        if all(e.end <= k.start or e.start >= k.end for k in kept):
            kept.append(e)
    return sorted(kept, key=lambda x: x.start)


# ----------------------------------------------------------------- built-in redactor (fallback)
def builtin_redact(blocks: List[Blk], ents: List[Ent]) -> List[str]:
    """Same value -> same placeholder within the file ([EMAIL_1]). Sets Ent.placeholder."""
    counters: Dict[str, int] = {}
    seen: Dict[Tuple[str, str], str] = {}
    for e in sorted(ents, key=lambda x: (x.block if x.block >= 0 else _BIG, x.start if x.start >= 0 else _BIG)):
        key = (e.entity_type, _norm_value(e.value))
        if key not in seen:
            counters[e.entity_type] = counters.get(e.entity_type, 0) + 1
            seen[key] = f"[{e.entity_type}_{counters[e.entity_type]}]"
        e.placeholder = seen[key]
    texts = []
    for b in blocks:
        text = b.text
        located = _resolve_overlaps([e for e in ents if e.block == b.pos and e.start >= 0])
        for e in sorted(located, key=lambda x: x.start, reverse=True):
            text = text[:e.start] + e.placeholder + text[e.end:]
        texts.append(text)
    for e in sorted([e for e in ents if e.start < 0], key=lambda x: -len(x.value)):
        texts = [t.replace(e.value, e.placeholder) for t in texts]
    return texts


def _normalize_redaction(raw: Any, blocks: List[Blk]) -> Tuple[List[str], Any, bool, List[str]]:
    warns: List[str] = []
    report = None
    if isinstance(raw, tuple) and len(raw) == 2 and isinstance(raw[0], (list, tuple)):
        raw, report = raw
    elif isinstance(raw, dict) or (raw is not None and not isinstance(raw, (str, list, tuple))):
        report = _get(raw, "report", "exposure_report", default=None)
        raw = _get(raw, "redacted_blocks", "blocks", "pages", "redacted", default=None)
        if raw is None:
            raise PipelineError("redaction", "Redaction output has no redacted blocks.")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        raise PipelineError("redaction", f"Unrecognised redaction output ({type(raw).__name__}).")
    texts = []
    for i, item in enumerate(raw):
        t = item if isinstance(item, str) else _get(item, "text", "redacted_text", "content", default=None)
        if t is None:
            raise PipelineError("redaction", f"Redacted block {i + 1} has no text field.")
        texts.append(str(t))
    aligned = len(texts) == len(blocks)
    if not aligned:
        warns.append(f"Redaction returned {len(texts)} block(s) for {len(blocks)} input block(s); per-block "
                     "traceability is unreliable.")
    return texts, report, aligned, warns


# ----------------------------------------------------------------- validation
def validate_file(filename: str, data: bytes) -> Tuple[str, str]:
    ext = os.path.splitext(filename)[1].lower()
    if ext not in cfg.SUPPORTED_TYPES:
        raise PipelineError("validation", f"Unsupported file type '{ext or 'none'}'. Supported: "
                            + ", ".join(sorted(cfg.SUPPORTED_TYPES)))
    if not data:
        raise PipelineError("validation", "File is empty (0 bytes).")
    if len(data) > cfg.MAX_FILE_MB * 1024 * 1024:
        raise PipelineError("validation", f"File exceeds {cfg.MAX_FILE_MB} MB limit.")
    ftype = cfg.SUPPORTED_TYPES[ext]
    if ftype == "pdf" and not data[:1024].lstrip().startswith(b"%PDF"):
        raise PipelineError("validation", "File has .pdf extension but is not a valid PDF.")
    if ftype in ("docx", "pptx") and data[:2] != b"PK":
        raise PipelineError("validation", f"File has .{ftype} extension but is not a valid Office file.")
    return ftype, ""


# ----------------------------------------------------------------- main entry point
def process_document(filename: str, data: bytes, settings: Optional[Settings] = None,
                     progress: Optional[Callable[[str, float], None]] = None) -> DocResult:
    settings = settings or Settings()
    prog = progress or (lambda stage, frac: None)
    res = DocResult(filename=filename, size_bytes=len(data or b""), sha256=hashlib.sha256(data or b"").hexdigest())
    tmpdir = None
    stage = "validation"
    try:
        prog("Validating", 0.05)
        res.file_type, _ = validate_file(filename, data)
        res.log.append(f"Validated as {res.file_type}; routed to extraction.")

        # ---- extraction
        stage = "extraction"
        prog("Extracting text", 0.2)
        t0 = time.time()
        fn, label = load_backend("extraction", res.file_type, settings)
        res.backends["extraction"] = label
        safe = re.sub(r"[^\w.\- ]", "_", os.path.basename(filename)) or f"upload{os.path.splitext(filename)[1]}"
        tmpdir = tempfile.mkdtemp(prefix="pii_")
        path = Path(tmpdir) / safe
        path.write_bytes(data)
        arg = {"path": path, "str": str(path), "bytes": data}.get(cfg.EXTRACTION_ARG, path)
        try:
            raw = _invoke(fn, arg, res.file_type)
        except PipelineError:
            raise
        except Exception as e:
            raise PipelineError("extraction", _short(e))
        res.blocks, w = normalize_blocks(raw, filename)
        res.warnings += w
        res.timings["extraction"] = round(time.time() - t0, 3)
        if not any(b.text.strip() for b in res.blocks):
            raise PipelineError("extraction", "No text could be extracted (empty or image-only document - OCR may be required).")
        empty = [b.pos + 1 for b in res.blocks if not b.text.strip()]
        if empty:
            res.warnings.append(f"{len(empty)} block(s) had no text.")
        low = [b for b in res.blocks if b.ocr_confidence is not None and b.ocr_confidence < 0.6]
        if low:
            res.warnings.append(f"{len(low)} block(s) have low OCR confidence (<0.60) - PII may be missed there.")
        res.log.append(f"{len(res.blocks)} block(s) over {len(res.pages)} page/slide(s), "
                       f"{sum(len(b.text) for b in res.blocks):,} characters ({label}).")
        raw_blocks = [b.raw for b in res.blocks]

        # ---- detection
        stage = "detection"
        prog("Detecting PII", 0.5)
        t0 = time.time()
        dfn, dlabel = load_backend("detection", res.file_type, settings)
        res.backends["detection"] = dlabel
        try:
            raw_ents = _invoke(dfn, raw_blocks)
        except PipelineError:
            raise
        except Exception as e:
            raise PipelineError("detection", _short(e))
        all_ents, problems = normalize_entities(raw_ents, res.blocks)
        if problems:
            res.warnings.append(f"{problems} entit(ies) had offsets that did not match their block; "
                                "the app re-located them by value (check the detector's offsets).")
        if any(e.block < 0 for e in all_ents):
            res.warnings.append("Some entities could not be placed in any block; they are redacted by value only.")
        res.entities = [e for e in all_ents if e.confidence >= settings.min_confidence]
        res.skipped_entities = [e for e in all_ents if e.confidence < settings.min_confidence]
        if res.skipped_entities:
            res.warnings.append(f"{len(res.skipped_entities)} detection(s) below confidence "
                                f"{settings.min_confidence:.2f} were NOT redacted - review them.")
        res.timings["detection"] = round(time.time() - t0, 3)
        res.log.append(f"{len(res.entities)} entit(ies) to redact ({dlabel}).")

        # ---- redaction
        stage = "redaction"
        prog("Redacting", 0.75)
        t0 = time.time()
        rfn, rlabel = _load_redactor(settings)
        res.backends["redaction"] = rlabel
        if rfn is None:
            res.redacted_texts, res.aligned = builtin_redact(res.blocks, res.entities), True
        else:
            try:
                raw_red = _invoke(rfn, raw_blocks, [e.raw for e in res.entities])
            except Exception as e:
                raise PipelineError("redaction", _short(e))
            res.redacted_texts, res.teammate_report, res.aligned, w = _normalize_redaction(raw_red, res.blocks)
            res.warnings += w
        res.timings["redaction"] = round(time.time() - t0, 3)

        # ---- verification
        stage = "verification"
        prog("Verifying", 0.9)
        t0 = time.time()
        res.leaks = _verify(res, dfn)
        if res.leaks:
            res.warnings.append(f"{len(res.leaks)} possible PII leak(s) after redaction - NOT cleared for LLM.")
        res.timings["verify"] = round(time.time() - t0, 3)
        res.status = "warning" if res.warnings else "success"
        prog("Done", 1.0)
    except PipelineError as e:
        res.status, res.error, res.failed_stage = "failed", str(e), e.stage
        res.log.append(f"FAILED at {e.stage}: {e}")
    except Exception as e:
        res.status, res.error, res.failed_stage = "failed", f"Unexpected error: {_short(e)}", stage
        res.log.append(traceback.format_exc(limit=3))
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
    return res


def _load_redactor(settings: Settings):
    if settings.force_mock:
        return None, "builtin"
    fn, label, problem = _resolve("redaction", None)
    if fn is not None:
        return fn, label
    if settings.strict_real:
        raise PipelineError("redaction", f"Strict mode: real backend unavailable ({problem}).")
    return None, f"builtin ({problem})"


def _with_text(raw: Any, text: str) -> Any:
    if isinstance(raw, dict):
        return {**raw, "text": text}
    if hasattr(raw, "model_copy"):
        return raw.model_copy(update={"text": text})
    if dataclasses.is_dataclass(raw) and not isinstance(raw, type):
        return dataclasses.replace(raw, text=text)
    c = copy.copy(raw)
    setattr(c, "text", text)
    return c


def _verify(res: DocResult, detect_fn: Callable) -> List[str]:
    leaks: List[str] = []
    for e in res.entities:
        if len(e.value) < 3:
            continue
        hits = [i for i, t in enumerate(res.redacted_texts) if e.value in t]
        if hits:
            where = res.blocks[hits[0]].location if res.aligned and hits[0] < len(res.blocks) else "unknown location"
            leaks.append(f"{e.entity_type} value still present after redaction ({where}).")
    if not res.aligned:
        res.warnings.append("Residual check skipped: redacted blocks do not align with input blocks.")
        return leaks
    try:   # second detection pass on the redacted blocks
        red_raw = [_with_text(b.raw, t) for b, t in zip(res.blocks, res.redacted_texts)]
        red_blocks = [Blk(b.pos, b.key, b.file, b.location, b.page, t, b.ocr_confidence, r)
                      for b, t, r in zip(res.blocks, res.redacted_texts, red_raw)]
        residual, _ = normalize_entities(_invoke(detect_fn, red_raw), red_blocks)
        for e in residual:
            if e.start < 0 or e.confidence < 0.5 or PLACEHOLDER_RE.search(e.value):
                continue
            txt = red_blocks[e.block].text
            if any(m.start() < e.end and e.start < m.end() for m in PLACEHOLDER_RE.finditer(txt)):
                continue
            leaks.append(f"Residual {e.entity_type} found on second pass ({e.location}).")
    except Exception as ex:
        res.warnings.append(f"Residual check skipped: {_short(ex)}")
    return leaks


# ----------------------------------------------------------------- redaction integrity (demo proxy)
def non_pii_preserved(res: DocResult) -> Optional[float]:
    """Share of non-PII text that survives redaction (1.0 = nothing but PII changed). Demo proxy only."""
    if not res.aligned or not res.blocks:
        return None
    try:
        num = den = 0.0
        for b, red in zip(res.blocks, res.redacted_texts):
            spans = sorted((e.start, e.end) for e in res.entities if e.block == b.pos and e.start >= 0)
            clean, pos = [], 0
            for s, e in spans:
                if s > pos:
                    clean.append(b.text[pos:s])
                pos = max(pos, e)
            clean.append(b.text[pos:])
            a, c = "".join(clean), PLACEHOLDER_RE.sub("", red)
            ratio = 1.0 if a == c else difflib.SequenceMatcher(None, a[:4000], c[:4000], autojunk=False).ratio()
            num += ratio * len(a)
            den += len(a)
        return num / den if den else 1.0
    except Exception:
        return None


def placeholder_table(res: DocResult) -> List[dict]:
    """Token -> occurrences/pages, built from the redacted text (works for any redaction module)."""
    seen: Dict[str, dict] = {}
    for i, t in enumerate(res.redacted_texts):
        page = res.blocks[i].page if res.aligned and i < len(res.blocks) else None
        for m in PLACEHOLDER_RE.finditer(t):
            d = seen.setdefault(m.group(), {"n": 0, "pages": set()})
            d["n"] += 1
            if page is not None:
                d["pages"].add(page)
    return [{"Placeholder": k, "Type": re.sub(r"_\d+\]$", "", k)[1:], "Occurrences": v["n"],
             "Pages/Slides": ", ".join(map(str, sorted(v["pages"])))} for k, v in sorted(seen.items())]


def scrubbed_teammate_report(res: DocResult) -> Tuple[Any, str]:
    """Return (report, note). Refuses to expose it if any raw value appears inside."""
    if res.teammate_report is None:
        return None, ""
    try:
        rep = dataclasses.asdict(res.teammate_report) if dataclasses.is_dataclass(res.teammate_report) \
            and not isinstance(res.teammate_report, type) else res.teammate_report
        blob = repr(rep)
        if any(len(e.value) >= 3 and e.value in blob for e in res.entities):
            return None, "The redaction module's report contains raw PII values - hidden. Fix it in the redaction module."
        return rep, ""
    except Exception as ex:
        return None, f"Could not read redaction report ({_short(ex)})."


# ----------------------------------------------------------------- ground-truth scoring (offline QA helper)
def evaluate_detection(results: List[DocResult], truth: List[dict], partial: bool = False,
                       match_type: bool = False) -> Tuple[List[dict], List[dict]]:
    """Per-file and per-type scores. Values are compared internally and never returned."""
    truth_by: Dict[str, List[Tuple[str, str]]] = {}
    for row in truth:
        f = str(_get(row, "filename", "file", default="")).strip()
        v = str(_get(row, "text", "value", "pii", default="")).strip()
        if f and v:
            truth_by.setdefault(f, []).append((_norm_value(v), norm_type(_get(row, "entity_type", "type", "category", default=""))))

    def same(a, b):
        if a[0] == b[0] or (partial and a[0] and b[0] and (a[0] in b[0] or b[0] in a[0])):
            return (not match_type) or a[1] == b[1]
        return False

    files, types = [], {}
    for r in results:
        if r.filename not in truth_by:
            continue
        gt = list(dict.fromkeys(truth_by[r.filename]))
        pred = list(dict.fromkeys((_norm_value(e.value), e.entity_type) for e in r.entities))
        hit_gt = [any(same(p, g) for p in pred) for g in gt]
        hit_pred = [any(same(p, g) for g in gt) for p in pred]
        tp, fn, fp = sum(hit_gt), len(gt) - sum(hit_gt), len(pred) - sum(hit_pred)
        prec = sum(hit_pred) / len(pred) if pred else 0.0
        rec = tp / len(gt) if gt else 1.0
        files.append({"File": r.filename, "Ground truth": len(gt), "Detected": len(pred), "Hits": tp,
                      "False positives": fp, "Missed (false negatives)": fn,
                      "Precision": round(prec, 3), "Recall": round(rec, 3)})
        for g, h in zip(gt, hit_gt):
            t = types.setdefault(g[1] or "UNLABELLED", [0, 0])
            t[0] += 1
            t[1] += int(h)
    per_type = [{"Type": k, "Ground truth": v[0], "Found": v[1], "Recall": round(v[1] / v[0], 3)}
                for k, v in sorted(types.items())]
    return files, per_type
