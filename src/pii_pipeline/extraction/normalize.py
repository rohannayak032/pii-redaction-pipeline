"""Offset-safe text cleanup.

Every piece of text is cleaned BEFORE it is joined into a block, and spans are
computed on the joined result, so offsets always refer to the final
``TextBlock.text``.

Why not NFKC? It would also fold characters such as a superscript footnote
marker (``"¹"`` -> ``"1"``), turning ``805-52-0432¹`` into ``805-52-04321`` and
breaking ID patterns. We apply only the targeted folds below.
"""

from __future__ import annotations

import re
import unicodedata

# Characters that are invisible but can split an email or ID so a regex misses it.
_REMOVE = dict.fromkeys(map(ord, "­​‌‍⁠﻿᠎"), None)

_LIGATURES = {
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl",
    "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st",
}

# Hyphen and dash look-alikes -> ASCII hyphen, so "805‑52‑0432" (non-breaking
# hyphens) still matches an SSN pattern.
_HYPHENS = dict.fromkeys(map(ord, "‐‑‒–—―−﹣"), "-")

_SPACES = dict.fromkeys(
    map(ord, "          "
             "     　"),
    " ",
)

_TABLE = {**_REMOVE, **_HYPHENS, **_SPACES, **{ord(k): v for k, v in _LIGATURES.items()}}

# Fullwidth ASCII variants (U+FF01..U+FF5E) -> ASCII ("ｊｏｈｎ＠ｘ" -> "john@x").
_TABLE.update({cp: chr(cp - 0xFEE0) for cp in range(0xFF01, 0xFF5F)})

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_WHITESPACE = re.compile(r"\s+")


def clean(text: str | None) -> str:
    """Return ``text`` normalized to a single trimmed line."""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = text.translate(_TABLE)
    text = _CONTROL.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip()
