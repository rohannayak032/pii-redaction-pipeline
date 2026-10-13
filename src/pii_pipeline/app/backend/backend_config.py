"""
backend_config.py  -  the ONLY place where the app is told where teammates' code lives.

Each stage lists candidate modules and function names; the FIRST one that imports and exists wins.
Edit these once teammates confirm their real names (the sidebar "Backend status" shows what was found).

Contracts (team schemas.py):
  extraction : fn(path) -> list[TextBlock]            (reading order)
  detection  : fn(list[TextBlock]) -> list[Entity]    (start/end are offsets inside that block's text)
  redaction  : fn(list[TextBlock], list[Entity]) -> list[RedactedBlock]  or  (list[RedactedBlock], report)
The app passes the teammates' own objects straight through; it never converts them to dicts.
"""
import sys
from pathlib import Path

# make `import pii_pipeline` work when running from the repo without installing it
_here = Path(__file__).resolve().parent
for _p in (_here, *list(_here.parents)[:4]):
    if _p.name == "src" and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

BACKEND = {
    "extraction": {"modules": ["pii_pipeline.extraction"],
                   "functions": ["extract_file", "extract_document", "extract_blocks", "extract"]},
    "detection":  {"modules": ["pii_pipeline.detection"],
                   "functions": ["detect_entities", "detect_pii", "detect", "detect_blocks"]},
    "redaction":  {"modules": ["pii_pipeline.redaction"],
                   "functions": ["redact_blocks", "redact_document", "redact"]},
}

# Optional per-file-type override, e.g. {"pdf": {"modules": [...], "functions": ["extract_pdf"]}}
EXTRACTION_BY_TYPE = {}

# What the extraction function receives: "path" (pathlib.Path), "str" (path as text) or "bytes"
EXTRACTION_ARG = "path"

SUPPORTED_TYPES = {
    ".pdf": "pdf", ".docx": "docx", ".pptx": "pptx", ".txt": "txt",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".tif": "image", ".tiff": "image",
}
MAX_FILE_MB = 25

# Risk rating of each PII category. Add the detection teammate's category names here.
HIGH_SEVERITY = {"SSN", "CREDIT_CARD", "PASSPORT", "BANK_ACCOUNT", "IBAN", "NATIONAL_ID",
                 "DRIVER_LICENSE", "GOVERNMENT_ID", "TAX_ID", "AADHAAR", "PAN"}
MEDIUM_SEVERITY = {"PERSON", "EMAIL", "PHONE", "DATE_OF_BIRTH", "ADDRESS", "EMPLOYEE_ID", "FULL_NAME"}
