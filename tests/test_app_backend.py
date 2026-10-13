"""Web app workflow layer: real extraction and redaction, detection stubbed so no model loads."""

import json

import docx

from pii_pipeline.app.backend import pipeline as P
from pii_pipeline.schemas import Entity

EMAIL = "jane.doe@example.com"


def make_docx(tmp_path, *paragraphs):
    d = docx.Document()
    for text in paragraphs:
        d.add_paragraph(text)
    path = tmp_path / "t.docx"
    d.save(path)
    return path.read_bytes()


def find_email(blocks):
    """Stub detector: only the first occurrence, so a repeat in a later block is missed."""
    for b in blocks:
        i = b.text.find(EMAIL)
        if i >= 0:
            return [Entity(b.file, b.index, i, i + len(EMAIL), "EMAIL", 0.9, "stub", EMAIL)]
    return []


def test_rejects_bad_uploads_before_extraction():
    assert P.process_document("notes.txt", b"x").failed_stage == "validation"
    empty = P.process_document("a.pdf", b"")
    assert (empty.status, empty.failed_stage) == ("failed", "validation")


def test_redacts_and_view_has_no_raw_values(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "detect", find_email)
    res = P.process_document("t.docx", make_docx(tmp_path, f"Mail {EMAIL} today.", "No PII here."))
    assert res.status in ("success", "warning") and res.llm_ready and not res.leaks
    view = P.view(res, 0)
    assert view["records"][0]["placeholder"] == "[EMAIL_1]" and view["entities"][0]["placeholder"] == "[EMAIL_1]"
    assert "[EMAIL_1]" in view["redacted"][0]["text"]
    assert EMAIL not in json.dumps(view) and EMAIL not in res.redacted_text()


def test_undetected_repeat_is_a_leak(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "detect", find_email)
    res = P.process_document("t.docx", make_docx(tmp_path, f"Mail {EMAIL}.", f"Again {EMAIL}."))
    assert len(res.leaks) == 1 and not res.llm_ready and res.status == "warning"
    assert EMAIL not in res.leaks[0]


def test_value_inside_a_longer_word_is_not_a_leak():
    ann = Entity("t.docx", 0, 0, 3, "PERSON", 0.9, "stub", "Ann")
    blocks = [P.RedactedBlock("t.docx", 0, "p1", "[PERSON_1] wrote it."), P.RedactedBlock("t.docx", 1, "p2", "Annual review.")]
    assert P.residual_leaks([ann], blocks) == []
    blocks.append(P.RedactedBlock("t.docx", 2, "p3", "Ask Ann."))
    assert P.residual_leaks([ann], blocks) == ["A detected PERSON value still appears after redaction (p3)."]
