import dataclasses
import math

import pytest

from pii_pipeline.redaction import (
    InvalidBlockError,
    InvalidEntityError,
    PlaceholderManager,
    RedactionVerificationError,
    TraceRecord,
    redact_block,
    verify_redaction,
)
from pii_pipeline.redaction import redactor as redactor_module

from .helpers import leaked, make_block, make_entity

SECRET = "SECRETFAKE-123"
OTHER_SECRET = "WRONGFAKE-000"
TEXT = f"Contact {SECRET} now"


def _good():
    block = make_block(TEXT)
    return block, make_entity(block, SECRET, "EMPLOYEE_ID")


BAD_CHANGES = {
    "negative_start": {"start": -1},
    "negative_end": {"start": 0, "end": -1},
    "start_after_end": {"start": 15, "end": 8},
    "end_past_text": {"end": 500},
    "empty_span": {"start": 10, "end": 10},
    "other_file": {"file": "other.pdf"},
    "other_block": {"block_index": 9},
    "value_mismatch": {"value": OTHER_SECRET},
    "confidence_negative": {"confidence": -0.1},
    "confidence_too_big": {"confidence": 1.5},
    "confidence_nan": {"confidence": math.nan},
    "confidence_inf": {"confidence": math.inf},
    "confidence_string": {"confidence": "high"},
    "confidence_bool": {"confidence": True},
    "type_lowercase": {"pii_type": "person"},
    "type_empty": {"pii_type": ""},
    "type_none": {"pii_type": None},
    "type_space": {"pii_type": "PER SON"},
    "type_brackets": {"pii_type": "[PERSON]"},
    "type_too_long": {"pii_type": "A" * 100},
    "start_not_int": {"start": "8"},
    "value_not_string": {"value": None},
}


@pytest.mark.parametrize("change", list(BAD_CHANGES.values()), ids=list(BAD_CHANGES))
def test_invalid_entities_raise_without_leaking(change):
    block, entity = _good()
    bad = dataclasses.replace(entity, **change)
    with pytest.raises(InvalidEntityError) as exc:
        redact_block(block, [bad])
    message = str(exc.value)
    assert not leaked(message, [SECRET, OTHER_SECRET, "Contact", "now"])
    assert "Invalid entity" in message


def test_non_entity_object_is_rejected():
    block, _ = _good()
    with pytest.raises(InvalidEntityError):
        redact_block(block, [{"start": 0, "end": 3}])  # type: ignore[list-item]


def test_error_message_has_safe_metadata_only():
    block, entity = _good()
    bad = dataclasses.replace(entity, value=OTHER_SECRET)
    with pytest.raises(InvalidEntityError) as exc:
        redact_block(block, [bad])
    message = str(exc.value)
    assert "Entity span does not match the supplied text." in message
    for expected in ("doc.pdf", "block_index=0", "start=8", "end=22", "EMPLOYEE_ID"):
        assert expected in message
    assert exc.value.fields["pii_type"] == "EMPLOYEE_ID"


def test_empty_text_with_any_entity_is_invalid():
    block = make_block("")
    entity = dataclasses.replace(make_entity(make_block("abc"), "abc"), file=block.file)
    with pytest.raises(InvalidEntityError):
        redact_block(block, [entity])


def test_invalid_block_is_rejected():
    with pytest.raises(InvalidBlockError):
        redact_block("not a block", [])  # type: ignore[arg-type]
    with pytest.raises(InvalidBlockError):
        redact_block(dataclasses.replace(make_block("x"), text=None), [])  # type: ignore[arg-type]


def test_one_bad_entity_fails_everything_and_leaves_manager_untouched():
    block, entity = _good()
    bad = dataclasses.replace(entity, start=-5)
    manager = PlaceholderManager()
    with pytest.raises(InvalidEntityError):
        redact_block(block, [entity, bad], manager)
    assert manager.count(block.file, "EMPLOYEE_ID") == 0


def _record(block, start, end, placeholder="[EMPLOYEE_ID_1]"):
    return TraceRecord(block.file, block.index, block.location, start, end,
                       "EMPLOYEE_ID", 0.9, "fake", placeholder)


def test_verify_redaction_passes_for_correct_output():
    block, entity = _good()
    record = _record(block, 8, 22)
    redacted = "Contact [EMPLOYEE_ID_1] now"
    result = verify_redaction(block, redacted, [record], [entity])
    assert result.passed
    assert result.failures == ()


def test_verify_redaction_detects_left_over_pii():
    block, entity = _good()
    record = _record(block, 8, 22)
    result = verify_redaction(block, TEXT, [record], [entity])  # original text left in place
    assert not result.passed
    assert not leaked(" ".join(result.failures), [SECRET])


def test_verify_redaction_detects_uncovered_entity():
    block, entity = _good()
    result = verify_redaction(block, TEXT, [], [entity])
    assert not result.passed
    assert any("not covered" in f for f in result.failures)


def test_verify_redaction_detects_partial_cover():
    block, entity = _good()
    record = _record(block, 8, 15)  # covers only the first part of the entity
    result = verify_redaction(block, "Contact [EMPLOYEE_ID_1]-123 now", [record], [entity])
    assert not result.passed


def test_verify_redaction_detects_altered_surrounding_text():
    block, entity = _good()
    record = _record(block, 8, 22)
    result = verify_redaction(block, "Contakt [EMPLOYEE_ID_1] now", [record], [entity])
    assert not result.passed
    result = verify_redaction(block, "Contact [EMPLOYEE_ID_1] later", [record], [entity])
    assert not result.passed


def test_redact_block_fails_closed_if_engine_leaves_pii(monkeypatch):
    block, entity = _good()
    monkeypatch.setattr(redactor_module, "_apply_replacements", lambda text, records: text)
    with pytest.raises(RedactionVerificationError) as exc:
        redact_block(block, [entity])
    assert not leaked(str(exc.value), [SECRET])
