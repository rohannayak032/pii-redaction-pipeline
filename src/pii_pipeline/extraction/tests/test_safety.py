"""Security rules from the README: local only, nothing printed or logged."""

import ast
import logging
import warnings
import zipfile
from pathlib import Path

import pytest

import pii_pipeline.extraction as extraction
from pii_pipeline.extraction import (
    ExtractionWarningCategory,
    UnsupportedFileError,
    extract_document,
    extract_document_detailed,
)
from pii_pipeline.extraction.__main__ import main

from .fixtures import fake as f

MODULE_DIR = Path(extraction.__file__).parent
FORBIDDEN_IMPORTS = {"logging", "requests", "urllib", "http", "socket", "httpx", "aiohttp", "ftplib", "smtplib"}
PLANTED = [f.PERSON_BODY, f.EMAIL_BODY, f.SSN, f.PERSON_COMMENT_AUTHOR, f.PERSON_ORPHAN, f.PERSON_AUTHOR]


def _source_files():
    return [p for p in MODULE_DIR.rglob("*.py") if "tests" not in p.relative_to(MODULE_DIR).parts]


def test_no_print_logging_or_network_in_module():
    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                for name in names:
                    assert name.split(".")[0] not in FORBIDDEN_IMPORTS, (path.name, name)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
                assert path.name == "__main__.py", f"print() in {path.name}"


def test_nothing_printed_or_logged_during_extraction(files, capfd, caplog):
    caplog.set_level(logging.DEBUG)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for name in ("docx", "pptx", "pdf_digital"):
            extract_document(files[name])
    out, err = capfd.readouterr()
    emitted = out + err + caplog.text + " ".join(str(w.message) for w in caught)
    assert not any(value in emitted for value in PLANTED)
    assert all(issubclass(w.category, ExtractionWarningCategory) for w in caught)


def test_cli_summary_shows_no_text(files, capsys):
    assert main([str(files["docx"]), str(files["pptx"])]) == 0
    out = capsys.readouterr().out
    assert "blocks" in out
    assert not any(value in out for value in PLANTED)


def test_cli_refuses_output_outside_data_dir(files, tmp_path):
    with pytest.raises(SystemExit):
        main([str(files["docx"]), "--out", str(tmp_path / "leak.jsonl")])


def test_cli_writes_full_text_inside_data_dir(files, tmp_path):
    out = tmp_path / "data" / "extracted" / "x.jsonl"
    assert main([str(files["docx"]), "--out", str(out)]) == 0
    assert f.PERSON_BODY in out.read_text(encoding="utf-8")


# ---------------------------------------------------------------- dispatch
def test_unsupported_and_legacy_files(tmp_path):
    txt = tmp_path / "notes.txt"
    txt.write_text("Ava Stone")
    with pytest.raises(UnsupportedFileError) as info:
        extract_document(txt)
    assert "Ava" not in str(info.value)

    legacy = tmp_path / "old.doc"
    legacy.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 600)
    with pytest.raises(UnsupportedFileError, match="legacy"):
        extract_document(legacy)

    archive = tmp_path / "data.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("a.txt", "x")
    with pytest.raises(UnsupportedFileError):
        extract_document(archive)


def test_empty_file_and_extension_mismatch(tmp_path, files):
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    result = extract_document_detailed(empty)
    assert result.blocks == () and result.warnings[0].code == "EMPTY_FILE"

    renamed = tmp_path / "really_a_docx.pptx"
    renamed.write_bytes(Path(files["docx"]).read_bytes())
    result = extract_document_detailed(renamed)
    assert any(w.code == "EXTENSION_MISMATCH" for w in result.warnings)
    assert any(f.PERSON_BODY in b.text for b in result.blocks)


def test_damaged_file_error_has_no_content(tmp_path):
    broken = tmp_path / "broken.docx"
    with zipfile.ZipFile(broken, "w") as z:
        z.writestr("word/document.xml", f"<not-xml>{f.PERSON_BODY}")
    with pytest.raises(extraction.ExtractionError) as info:
        extract_document(broken)
    assert f.PERSON_BODY not in str(info.value)
    assert info.value.__cause__ is None and info.value.__suppress_context__
