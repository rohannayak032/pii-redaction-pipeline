import json

from pii_pipeline.redaction import TraceRecord, build_report, redact_block, redact_document, report_to_json

from .helpers import leaked, make_block, make_entity

SECRETS = ["Alex Morgan", "alex@example.test"]


def _redact():
    block = make_block("Contact Alex Morgan at alex@example.test", file="demo.pdf", index=2, location="page 3")
    entities = [
        make_entity(block, "Alex Morgan", "PERSON", 0.91, "ner"),
        make_entity(block, "alex@example.test", "EMAIL", 0.98, "regex"),
    ]
    return redact_block(block, entities)


def test_trace_records_contain_expected_fields():
    _, records = _redact()
    assert [r.to_dict() for r in records] == [
        {
            "file": "demo.pdf", "block_index": 2, "location": "page 3",
            "start": 8, "end": 19, "pii_type": "PERSON", "confidence": 0.91,
            "detector": "ner", "placeholder": "[PERSON_1]", "merged_entities": 1,
        },
        {
            "file": "demo.pdf", "block_index": 2, "location": "page 3",
            "start": 23, "end": 40, "pii_type": "EMAIL", "confidence": 0.98,
            "detector": "regex", "placeholder": "[EMAIL_1]", "merged_entities": 1,
        },
    ]


def test_trace_record_has_no_value_field():
    _, records = _redact()
    assert "value" not in records[0].to_dict()
    assert not hasattr(records[0], "value")


def test_raw_pii_never_appears_in_records_report_or_reprs():
    redacted, records = _redact()
    blob = " ".join([
        repr(records), str(records), json.dumps(build_report(records)),
        report_to_json(records), repr(redacted),
    ])
    assert not leaked(blob, SECRETS)


def test_report_summary_counts():
    a = make_block("Alex Morgan alex@example.test", file="a.pdf")
    b = make_block("Sam Rivera", file="b.pdf")
    entities = [
        make_entity(a, "Alex Morgan"),
        make_entity(a, "alex@example.test", "EMAIL"),
        make_entity(b, "Sam Rivera"),
    ]
    _, records = redact_document([a, b], entities)
    report = build_report(records)
    assert len(report["findings"]) == 3
    assert report["summary"] == {
        "total_findings": 3,
        "by_pii_type": {"EMAIL": 1, "PERSON": 2},
        "by_file": {"a.pdf": 2, "b.pdf": 1},
    }


def test_report_json_round_trips():
    _, records = _redact()
    assert json.loads(report_to_json(records)) == build_report(records)


def test_records_trace_back_to_file_and_location_in_documents():
    b0 = make_block("Alex Morgan", file="a.pdf", index=0, location="page 1")
    b1 = make_block("Alex Morgan", file="b.docx", index=5, location="paragraph 6")
    _, records = redact_document([b0, b1], [make_entity(b0, "Alex Morgan"), make_entity(b1, "Alex Morgan")])
    assert [(r.file, r.block_index, r.location) for r in records] == [
        ("a.pdf", 0, "page 1"),
        ("b.docx", 5, "paragraph 6"),
    ]


def test_trace_record_is_immutable():
    record = TraceRecord("f", 0, "p1", 0, 1, "PERSON", 0.5, "d", "[PERSON_1]")
    try:
        record.start = 3  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("TraceRecord should be frozen")


def test_merged_overlap_is_reported_once_with_count():
    block = make_block("John Smith")
    entities = [make_entity(block, "John Smith"), make_entity(block, "Smith")]
    _, records = redact_block(block, entities)
    assert len(records) == 1 and records[0].merged_entities == 2
