"""Synthetic test values. All of them are invented; none come from case files.

Emails use the reserved ``.test`` TLD, SSN-like values use the never-issued
900 area, and phone numbers use the fictional 555-01xx range.
"""

import io

from PIL import Image, ImageDraw, ImageFont

PERSON_BODY = "Ava Stone"
PERSON_TABLE_2 = "Ben Ortiz"
PERSON_MERGED = "Cara Diaz"
PERSON_NESTED = "Eli Novak"
PERSON_HEADER_S1 = "Fay Quinn"
PERSON_HEADER_S2 = "Gus Romero"
PERSON_FIRST_PAGE = "Hana Ito"
PERSON_FOOTER = "Ivan Petrov"
PERSON_FOOTNOTE = "Kim Park"
PERSON_ENDNOTE = "Lia Moreau"
PERSON_COMMENT_AUTHOR = "Max Weber"
PERSON_COMMENT_BODY = "Nia Okafor"
PERSON_TEXTBOX = "Lee Grant"
PERSON_IMAGE = "Sam Lee"
PERSON_ALT = "Taylor Brook"
PERSON_AUTHOR = "Morgan Hale"
PERSON_LAST_MODIFIED = "Rowan Fox"
PERSON_ORPHAN = "Dana White"
PERSON_LIST = "Uma Shah"
PERSON_HEADING = "Vic Duran"

EMAIL_BODY = "ava.stone@example.test"
EMAIL_HIDDEN_LINK = "hidden.contact@example.test"
EMP_1 = "EMP-00101"
EMP_2 = "EMP-00102"
SSN = "900-12-3456"
PHONE = "+1 212-555-0101"
COMPANY = "Northwind Example Ltd"

_FONT_CACHE: dict[int, ImageFont.ImageFont] = {}


def font(size: int = 40):
    if size not in _FONT_CACHE:
        _FONT_CACHE[size] = ImageFont.load_default(size=size)
    return _FONT_CACHE[size]


def text_image(lines: list[str], size: tuple[int, int] = (1400, 300), font_size: int = 40,
               mode: str = "L") -> Image.Image:
    """White image with black text lines (OCR-friendly)."""
    image = Image.new(mode, size, "white")
    draw = ImageDraw.Draw(image)
    for i, line in enumerate(lines):
        draw.text((40, 40 + i * int(font_size * 1.8)), line, fill="black", font=font(font_size))
    return image


def png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def ruled_table_image(rows: list[list[str]], col_widths: list[int], origin=(60, 60), row_height=80,
                      size=(1700, 600), font_size=34) -> Image.Image:
    image = Image.new("L", size, 255)
    draw = ImageDraw.Draw(image)
    x0, y0 = origin
    xs = [x0]
    for width in col_widths:
        xs.append(xs[-1] + width)
    for r in range(len(rows) + 1):
        draw.line([(x0, y0 + r * row_height), (xs[-1], y0 + r * row_height)], fill=0, width=3)
    for x in xs:
        draw.line([(x, y0), (x, y0 + len(rows) * row_height)], fill=0, width=3)
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            draw.text((xs[c] + 15, y0 + r * row_height + 20), value, fill=0, font=font(font_size))
    return image
