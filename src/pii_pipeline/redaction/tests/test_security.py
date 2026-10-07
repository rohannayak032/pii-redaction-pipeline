"""Checks for the 'no leak / no external calls' rules."""

import ast
import logging
import pathlib

from pii_pipeline.redaction import InvalidEntityError, redact_document

from .helpers import leaked, make_block, make_entity

PACKAGE_DIR = pathlib.Path(__file__).resolve().parent.parent
FORBIDDEN_IMPORTS = {
    "socket", "ssl", "http", "urllib", "requests", "httpx", "aiohttp",
    "openai", "anthropic", "google", "boto3", "logging", "subprocess",
}


def _source_files():
    return [p for p in PACKAGE_DIR.glob("*.py")]


def test_source_makes_no_network_or_logging_imports():
    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            assert not (set(names) & FORBIDDEN_IMPORTS), f"forbidden import in {path.name}"


def test_source_never_prints():
    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id in {"print", "open"}]
        assert not calls, f"print/open call in {path.name}"


def test_running_redaction_writes_nothing_to_stdout_stderr_or_logs(capsys):
    records = []

    class Collector(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    root = logging.getLogger()
    handler = Collector()
    root.addHandler(handler)
    try:
        block = make_block("Alex Morgan alex@example.test")
        redact_document([block], [make_entity(block, "Alex Morgan"), make_entity(block, "alex@example.test", "EMAIL")])
    finally:
        root.removeHandler(handler)
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""
    assert records == []


def test_redacted_output_contains_no_detected_value():
    block = make_block("Alex Morgan, alex@example.test, Alex Morgan again; call 555-0100")
    entities = [
        make_entity(block, "Alex Morgan"),
        make_entity(block, "alex@example.test", "EMAIL"),
        make_entity(block, "Alex Morgan", occurrence=1),
        make_entity(block, "555-0100", "PHONE"),
    ]
    redacted, _ = redact_document([block], entities)
    assert not leaked(redacted[0].text, [e.value for e in entities])


def test_exception_from_document_call_is_safe():
    block = make_block("Alex Morgan")
    stray = make_block("Alex Morgan", index=3)
    try:
        redact_document([block], [make_entity(stray, "Alex Morgan")])
    except InvalidEntityError as exc:
        assert not leaked(str(exc) + repr(exc.args), ["Alex Morgan"])
    else:
        raise AssertionError("expected InvalidEntityError")
