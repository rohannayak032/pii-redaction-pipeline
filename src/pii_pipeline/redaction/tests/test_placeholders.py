import pytest

from pii_pipeline.redaction import PlaceholderManager, redact_block

from .helpers import leaked, make_block, make_entity


def test_numbering_is_separate_per_type():
    m = PlaceholderManager()
    assert m.get_placeholder("f.pdf", "PERSON", "Alice Fake") == "[PERSON_1]"
    assert m.get_placeholder("f.pdf", "PERSON", "Bob Fake") == "[PERSON_2]"
    assert m.get_placeholder("f.pdf", "EMAIL", "a@example.test") == "[EMAIL_1]"
    assert m.get_placeholder("f.pdf", "PERSON", "Carol Fake") == "[PERSON_3]"
    assert m.get_placeholder("f.pdf", "EMAIL", "b@example.test") == "[EMAIL_2]"


def test_same_value_reuses_placeholder():
    m = PlaceholderManager()
    first = m.get_placeholder("f.pdf", "PERSON", "Alice Fake")
    m.get_placeholder("f.pdf", "PERSON", "Bob Fake")
    assert m.get_placeholder("f.pdf", "PERSON", "Alice Fake") == first == "[PERSON_1]"
    assert m.count("f.pdf", "PERSON") == 2


def test_files_have_independent_namespaces():
    m = PlaceholderManager()
    assert m.get_placeholder("file_a.pdf", "PERSON", "Alice Fake") == "[PERSON_1]"
    assert m.get_placeholder("file_b.pdf", "PERSON", "Bob Fake") == "[PERSON_1]"
    assert m.get_placeholder("file_b.pdf", "PERSON", "Alice Fake") == "[PERSON_2]"
    assert m.get_placeholder("file_a.pdf", "PERSON", "Alice Fake") == "[PERSON_1]"


def test_matching_is_exact_and_case_sensitive():
    m = PlaceholderManager()
    assert m.get_placeholder("f.pdf", "PERSON", "Alice Fake") == "[PERSON_1]"
    assert m.get_placeholder("f.pdf", "PERSON", "alice fake") == "[PERSON_2]"
    assert m.get_placeholder("f.pdf", "PERSON", "Alice Fake ") == "[PERSON_3]"


def test_same_value_with_different_types_gets_separate_placeholders():
    m = PlaceholderManager()
    assert m.get_placeholder("f.pdf", "PERSON", "FAKE-42") == "[PERSON_1]"
    assert m.get_placeholder("f.pdf", "EMPLOYEE_ID", "FAKE-42") == "[EMPLOYEE_ID_1]"


def test_placeholder_reused_across_redact_block_calls_with_shared_manager():
    m = PlaceholderManager()
    b0 = make_block("Alex Morgan", index=0)
    b1 = make_block("Sam Rivera and Alex Morgan", index=1)
    r0, _ = redact_block(b0, [make_entity(b0, "Alex Morgan")], m)
    r1, _ = redact_block(b1, [make_entity(b1, "Sam Rivera"), make_entity(b1, "Alex Morgan")], m)
    assert r0.text == "[PERSON_1]"
    assert r1.text == "[PERSON_2] and [PERSON_1]"


def test_default_manager_is_fresh_for_each_call():
    block = make_block("Alex Morgan")
    entity = make_entity(block, "Alex Morgan")
    assert redact_block(block, [entity])[0].text == redact_block(block, [entity])[0].text == "[PERSON_1]"


def test_reset_one_file_or_all():
    m = PlaceholderManager()
    m.get_placeholder("a.pdf", "PERSON", "Alice Fake")
    m.get_placeholder("b.pdf", "PERSON", "Alice Fake")
    m.reset("a.pdf")
    assert m.count("a.pdf", "PERSON") == 0
    assert m.count("b.pdf", "PERSON") == 1
    m.reset()
    assert m.count("b.pdf", "PERSON") == 0


@pytest.mark.parametrize("bad_type", ["person", "", "PER SON", "[PERSON]", "PERSON\n", "A" * 65])
def test_invalid_type_is_rejected_without_echoing_value(bad_type):
    m = PlaceholderManager()
    with pytest.raises(ValueError) as exc:
        m.get_placeholder("f.pdf", bad_type, "SECRETFAKE-1")
    assert not leaked(str(exc.value), ["SECRETFAKE-1"])


def test_manager_does_not_store_or_show_raw_values():
    m = PlaceholderManager()
    secret = "SECRETFAKE-ALICE-123"
    m.get_placeholder("f.pdf", "PERSON", secret)
    assert not leaked(repr(m), [secret])
    assert not leaked(repr(vars(m)), [secret])
