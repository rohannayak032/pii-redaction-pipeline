"""Build synthetic PDFs: digital, scanned, mixed, rotated, encrypted, blank."""

from __future__ import annotations

from pathlib import Path

import pymupdf

from . import fake as f

PERSON_SCAN_1 = "Robin Vale"
PERSON_SCAN_2 = "Quinn Hart"
PERSON_ROTATED = "Pat Lowe"
PERSON_SKEWED = "Lane Ford"
PERSON_ANNOT_AUTHOR = "Pat Kim"
PERSON_FORM = "Chris Doe"
EMAIL_LINK = "hidden.person@example.test"
TABLE_ROWS = [["Employee ID", "Name", "Email"],
              [f.EMP_1, f.PERSON_BODY, f.EMAIL_BODY],
              [f.EMP_2, f.PERSON_TABLE_2, "ben.ortiz@example.test"]]


def _native_page(doc: pymupdf.Document, title: str) -> pymupdf.Page:
    page = doc.new_page()
    page.insert_text((72, 72), title, fontsize=16)
    page.insert_text((72, 100), f"Reviewed by {f.PERSON_HEADING} ({f.EMAIL_BODY}).", fontsize=11)
    return page


def _ruled_table(page: pymupdf.Page, rows=TABLE_ROWS, origin=(72, 140)) -> None:
    x0, y0 = origin
    widths, height = [110, 120, 190], 22
    xs = [x0]
    for w in widths:
        xs.append(xs[-1] + w)
    for r in range(len(rows) + 1):
        page.draw_line((x0, y0 + r * height), (xs[-1], y0 + r * height))
    for x in xs:
        page.draw_line((x, y0), (x, y0 + len(rows) * height))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            page.insert_text((xs[c] + 4, y0 + r * height + 15), value, fontsize=10)


def _scanned_page(doc: pymupdf.Document, lines: list[str], rotate: int = 0, skew: float = 0.0) -> None:
    image = f.text_image(lines, size=(1700, 2200), font_size=44)
    if skew:
        image = image.rotate(skew, expand=True, fillcolor="white")
    if rotate:
        image = image.rotate(-rotate, expand=True, fillcolor="white")
    page = doc.new_page()
    page.insert_image(page.rect, stream=f.png_bytes(image))


def build_digital(path: Path) -> Path:
    doc = pymupdf.open()
    page = _native_page(doc, "Quarterly HR summary")
    _ruled_table(page)
    image = f.text_image([f"Badge holder: {f.PERSON_IMAGE}", f"Phone {f.PHONE}"])
    page.insert_image(pymupdf.Rect(72, 260, 472, 346), stream=f.png_bytes(image))
    annot = page.add_text_annot((500, 80), f"Please verify SSN {f.SSN}")
    annot.set_info(title=PERSON_ANNOT_AUTHOR)
    widget = pymupdf.Widget()
    widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    widget.field_name, widget.field_value = "Manager", PERSON_FORM
    widget.rect = pymupdf.Rect(72, 380, 300, 400)
    page.add_widget(widget)
    page.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(72, 90, 200, 102),
                      "uri": f"mailto:{EMAIL_LINK}"})
    page2 = doc.new_page()
    page2.insert_text((72, 72), f"Second page for {f.PERSON_LIST}", fontsize=12)
    doc.set_metadata({"author": f.PERSON_AUTHOR, "title": "HR summary"})
    doc.save(path)
    return path


def build_mixed(path: Path) -> Path:
    """native / scanned / native / scanned (scan 2 holds a ruled table)."""
    doc = pymupdf.open()
    _native_page(doc, "Page one native")
    _scanned_page(doc, [f"Scanned letter for {PERSON_SCAN_1}", f"Employee ID {f.EMP_1}"])
    _native_page(doc, "Page three native")
    page = doc.new_page()
    table = f.ruled_table_image([["Employee ID", "Name"], [f.EMP_2, PERSON_SCAN_2]], [420, 420], size=(1700, 2200))
    page.insert_image(page.rect, stream=f.png_bytes(table))
    doc.save(path)
    return path


def build_rotated_and_skewed(path: Path) -> Path:
    doc = pymupdf.open()
    _scanned_page(doc, [f"Rotated record for {PERSON_ROTATED}", f"Employee ID {f.EMP_1}"], rotate=90)
    _scanned_page(doc, [f"Skewed record for {PERSON_SKEWED}", f"Employee ID {f.EMP_2}"], skew=3.0)
    doc.save(path)
    return path


def build_blank(path: Path) -> Path:
    doc = pymupdf.open()
    doc.new_page()
    doc.save(path)
    return path


def build_encrypted(path: Path) -> Path:
    doc = pymupdf.open()
    _native_page(doc, "Secret")
    doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner-pw", user_pw="user-pw")
    return path
