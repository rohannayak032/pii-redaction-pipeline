from pii_pipeline.schemas import TextBlock
from pii_pipeline.detection.detector import detect


def make(text):
    return TextBlock("a.txt", "para 1", 0, text)


def test_finds_email_and_offsets_are_exact():
    block = make("Contact alice@example.com today")
    entities = detect([block])
    assert len(entities) == 1
    e = entities[0]
    assert block.text[e.start:e.end] == "alice@example.com"


def test_two_emails_in_one_block():
    entities = detect([make("a@x.com and b@y.org")])
    assert len(entities) == 2


def test_trailing_full_stop_not_included():
    block = make("Write to alice@example.com.")
    e = detect([block])[0]
    assert block.text[e.start:e.end] == "alice@example.com"


def test_no_email_no_result():
    assert detect([make("Nothing to see here, 123 at home")]) == []