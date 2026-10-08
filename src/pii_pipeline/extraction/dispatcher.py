"""File-type detection and dispatch.

The type is decided from the file's content (magic bytes / package layout),
not trusted from the extension. A mismatch is reported as a warning.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from .base import Context, UnsupportedFileError
from .validation import EXTENSION_MISMATCH

_OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_EXTENSIONS = {"pdf": {".pdf"}, "docx": {".docx", ".docm", ".dotx"}, "pptx": {".pptx", ".pptm", ".potx"}}


def detect_format(path: Path, ctx: Context) -> str | None:
    """Return ``"pdf"``, ``"docx"``, ``"pptx"``, or None for an empty file."""
    if not path.is_file():
        raise UnsupportedFileError(f"Not a file: {path.name!r}.")
    with path.open("rb") as handle:
        head = handle.read(1024)
    if not head:
        return None

    if b"%PDF-" in head:
        fmt = "pdf"
    elif head.startswith(_OLE2):
        raise UnsupportedFileError(
            f"{path.name!r} is a legacy binary Office file (.doc/.ppt) or a password-protected "
            "Office file. Save it as .docx/.pptx without a password first."
        )
    elif head.startswith(b"PK"):
        try:
            with zipfile.ZipFile(path) as package:
                names = set(package.namelist())
        except zipfile.BadZipFile:
            raise UnsupportedFileError(f"{path.name!r} is a damaged ZIP/Office file.") from None
        if "word/document.xml" in names:
            fmt = "docx"
        elif "ppt/presentation.xml" in names:
            fmt = "pptx"
        else:
            raise UnsupportedFileError(f"{path.name!r} is a ZIP file but not a Word or PowerPoint document.")
    else:
        raise UnsupportedFileError(
            f"Unsupported file type for {path.name!r}. Supported: PDF, DOCX, PPTX."
        )

    if path.suffix.lower() not in _EXTENSIONS[fmt]:
        ctx.warn(EXTENSION_MISMATCH, "document", f"content is {fmt.upper()} but the extension is {path.suffix!r}")
    return fmt
