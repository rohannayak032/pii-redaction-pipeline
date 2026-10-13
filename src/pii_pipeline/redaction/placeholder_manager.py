"""Per-file placeholder numbering (``[PERSON_1]``, ``[EMAIL_2]``, ...).

Policy
------
* Namespace: one independent numbering space per ``file``.
* Numbering: separate counter per ``pii_type``, starting at 1, in the order
  values are first seen.
* Matching: same file + same pii_type + EXACT same string -> same placeholder.
  "john smith" and "John Smith" are different values. To change this policy
  later, edit :meth:`PlaceholderManager._normalize` (the single hook).
* Raw values are never stored: only a salted hash of each value is kept, so
  the manager cannot leak PII through ``repr``, ``vars`` or a crash dump.
"""

from __future__ import annotations

import hashlib
import os

from .validators import is_valid_pii_type


class PlaceholderManager:
    """Hands out stable placeholders, scoped per file and per PII type."""

    def __init__(self) -> None:
        self._salt = os.urandom(16)
        # file -> pii_type -> value hash -> number
        self._numbers: dict[str, dict[str, dict[str, int]]] = {}

    @staticmethod
    def _normalize(value: str) -> str:
        """Matching policy hook. Currently exact matching (identity)."""
        return value

    def _value_key(self, value: str) -> str:
        data = self._normalize(value).encode("utf-8", "surrogatepass")
        return hashlib.blake2b(data, key=self._salt, digest_size=16).hexdigest()

    def get_placeholder(self, file: str, pii_type: str, value: str) -> str:
        """Return the placeholder for ``value``, creating it on first use."""
        if not is_valid_pii_type(pii_type):
            raise ValueError("Invalid PII type for placeholder.")
        numbers = self._numbers.setdefault(file, {}).setdefault(pii_type, {})
        key = self._value_key(value)
        number = numbers.get(key)
        if number is None:
            number = len(numbers) + 1
            numbers[key] = number
        return f"[{pii_type}_{number}]"

    def count(self, file: str, pii_type: str) -> int:
        """How many distinct values of ``pii_type`` have been seen in ``file``."""
        return len(self._numbers.get(file, {}).get(pii_type, {}))

    def reset(self, file: str | None = None) -> None:
        """Forget one file's numbering, or everything if ``file`` is None."""
        if file is None:
            self._numbers.clear()
        else:
            self._numbers.pop(file, None)

    def __repr__(self) -> str:
        return f"PlaceholderManager(files={len(self._numbers)})"
