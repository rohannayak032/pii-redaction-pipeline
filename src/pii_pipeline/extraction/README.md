# Extraction module

Part of the **PII Redaction Pipeline**. Turns PDF (digital, scanned or mixed),
DOCX and PPTX files into `TextBlock`s in reading order, so detection and
redaction can run on them. Anything not extracted cannot be detected, so the
module is built for **maximum recall**, then **structure**, then **traceability**.

Everything runs locally. No document text is printed, logged, or put in an
exception or warning.

## 1. Setup

Python 3.12, from the repository root:

```bash
py -3.12 -m venv .venv          # Windows (python3.12 -m venv .venv elsewhere)
.venv/Scripts/pip install -r requirements.txt
```

OCR needs the **Tesseract** program (a local binary, not a web service):

| Where | How |
|---|---|
| Windows | Install from the UB Mannheim build; default path `C:\Program Files\Tesseract-OCR` is found automatically |
| Colab / Debian / Ubuntu | `apt-get install -y tesseract-ocr` |
| macOS | `brew install tesseract` |
| Anywhere | Set `TESSERACT_CMD` to the full path of the `tesseract` executable |

Optional: `PII_OCR_LANG` (default `eng`) selects Tesseract language packs.
If OCR is needed and Tesseract is missing, `OCRUnavailableError` is raised. OCR
is never silently skipped.

## 2. Public API

```python
from pii_pipeline.extraction import extract_document, extract_document_detailed

blocks = extract_document("policy.pdf")            # list[TextBlock], warnings via warnings.warn

result = extract_document_detailed("deck.pptx")    # ExtractionResult
result.blocks     # tuple[TextBlock, ...]  (index 0..n-1, reading order)
result.meta       # tuple[BlockMeta, ...]  aligned with blocks; positions only, no text
result.warnings   # tuple[ExtractionWarning, ...]  code + location + reason, no text
```

Errors: `UnsupportedFileError` (unknown type, legacy `.doc`/`.ppt`,
password-protected), `OCRUnavailableError`, `ExtractionError` (damaged file).
Library exceptions are never chained, because their messages can quote content.
For local debugging only, `PII_EXTRACTION_DEBUG=1` re-raises the original error.

`BlockMeta` holds `kind`, `source` (`native` / `ocr` / `xml`), `page` (page or
slide), `hidden`, `bbox` + `bbox_unit` (`pt`, `px` or `emu`), `table_id`,
`row_index`, `cells` = `(column, start, end)` and `words` =
`(start, end, bbox, confidence)`. All offsets are into the final
`TextBlock.text`, so an `Entity` can be traced back to a page, cell or box.

### Command line (your own machine only)

```bash
python -m pii_pipeline.extraction sample.pdf                               # counts + warnings, no text
python -m pii_pipeline.extraction sample.pdf --out data/extracted/x.jsonl  # full text, data/ only
```

`--out` refuses any path outside a `data/` folder (git-ignored). Never paste
that output into chats, tickets or AI assistants.

## 3. Architecture

```
dispatcher  ->  pdf_extract / docx_extract / pptx_extract  ->  RawBlocks
                 (all share ocr/, tables, ordering, ooxml, metadata)
            ->  pipeline: normalize -> render spans -> deduplicate -> number
            ->  validation: contract checks (raise) + completeness checks (warn)
            ->  TextBlocks + BlockMeta + warnings
```

| File | Purpose |
|---|---|
| `__init__.py` | public API |
| `dispatcher.py` | file type from content (magic bytes / package layout), not the extension |
| `base.py` | `Piece`, `RawBlock`, `BlockMeta`, `ExtractionResult`, errors, warnings |
| `normalize.py` | offset-safe text cleanup |
| `ordering.py` | recursive XY-cut reading order |
| `tables.py` | one block per row, with header labels |
| `deduplication.py` | geometry/location-based duplicate removal |
| `validation.py` | contract checks, warning codes |
| `pipeline.py` | assembly of RawBlocks into TextBlocks |
| `metadata.py` | document properties (OOXML core/app, PDF info) |
| `ooxml.py` | shared DOCX/PPTX helpers: safe XML parsing, charts, SmartArt, sweep |
| `ocr/` | Tesseract engine, preprocessing, ruled-table detection |
| `pdf_extract/` | per-page native / scanned extraction, annotations, forms, links |
| `docx_extract/` | body walk, tables, drawings, headers/footers, notes, comments |
| `pptx_extract/` | shapes and groups, tables, notes, comments, masters |
| `__main__.py` | command line |
| `tests/` | pytest suite; `tests/fixtures/` builds synthetic files at test time |

## 4. Developer report

### 4.1 Libraries and why

| Library | Used for | Why |
|---|---|---|
| PyMuPDF | PDF text layer with word boxes, `find_tables`, rendering, images, annotations, form fields, metadata | Fast, local, one library for all PDF needs |
| Tesseract + pytesseract | OCR with word confidence and boxes (TSV), orientation detection (OSD) | Local, mature, light; already in the team requirements |
| OpenCV + numpy | deskew, contrast, denoise, thresholds, ruled-table grid | Standard, fast image ops |
| python-docx, python-pptx | package/part/relationship handling, sections, slides, placeholders | Reliable OOXML packaging |
| lxml | our own XML walks (safe parser: no entities, no network) | The libraries skip text in insertions, content controls, text boxes, comments |
| Pillow | image decoding | |

PaddleOCR and OCRmyPDF were not chosen: they need a much heavier runtime
(Paddle, Ghostscript) for little gain on typed business documents.

### 4.2 Reading order

* **PDF native pages / OCR pages:** recursive XY-cut over paragraph, table and
  image boxes. Each step cuts once at the widest empty gap. A vertical cut
  (columns) wins only if it is wider than the best horizontal gap AND the two
  sides are not the same rows side by side, so a `Label    Value` form is read
  row by row, while a two-column article is read column by column.
* **DOCX:** document order of the XML body (paragraphs, tables, content
  controls); each paragraph's text boxes, images, charts and SmartArt follow it.
* **PPTX:** title placeholders first, then XY-cut over shapes in slide
  coordinates (group children converted through the group transform and kept
  together), then footer/date placeholders. Speaker notes and comments follow
  each slide.
* Ties break by input position, so the output is deterministic.

Order of non-flow content: DOCX → headers/footers, footnotes, endnotes,
comments, sweep, properties after the body. PPTX → master/layout text, sweep,
properties after the slides. PDF → annotations, form fields, link targets
after each page's content; properties at the end.

### 4.3 Tables

One logical row per block, with the header as context:

```
Employee ID: EMP-00101 | Name: Ava Stone | Department: Finance
```

* Header found from the file when possible (DOCX `w:tblHeader`, PPTX
  `firstRow`, PDF external header), else the first row if it is short,
  distinct, has no digits or `@`. The header row is not emitted separately.
* Empty cells are omitted; merged cells counted once; nested tables become
  their own rows (`table 1, row 3, nested table 1, row 2`).
* `BlockMeta.cells` gives the exact span of each cell value, and
  `table_id` / `row_index` give the row. Header labels are injected text,
  which matters for evaluation (see §6).

### 4.4 OCR and fallback

Per page, the PDF text layer is used if it has real text (at least 3 letters
or digits, not mostly undecodable glyphs). Otherwise the page is rendered at
300 DPI (capped at 40 megapixels) and OCR'd. On text-layer pages, embedded
images are also OCR'd. OCR blocks that mostly sit on text-layer words (text
drawn over an image) are dropped as duplicates.

The OCR chain (`ocr/`) runs these steps:

1. skip blank images
2. correct orientation (OSD, 90/180/270)
3. deskew (projection-profile search up to ±10°)
4. upscale small text towards ~30 px
5. CLAHE contrast + median denoise
6. detect ruled tables and OCR them cell by cell, then mask those areas
7. full-page OCR (`--oem 1 --psm 3`)

If mean confidence is below 0.6, the full-page pass is retried with adaptive
thresholding and with no thresholding, and the best result is kept.
Low-confidence words are always kept. `TextBlock.ocr_confidence` is the mean
word confidence, and `BlockMeta.words` has per-word confidence and boxes.

### 4.5 Hidden content covered

| Format | Covered |
|---|---|
| PDF | text outside the crop box, invisible OCR layers, annotations/comments (+ author), form-field values, link targets not shown on the page, info-dictionary properties; embedded attachments are flagged |
| DOCX | insertions, content controls, fields, hyperlinks, link targets, text boxes (DrawingML and VML, no duplicate from `mc:Fallback`), images (OCR + alt text), charts, SmartArt, headers/footers for every section (default / first page / even), footnotes, endnotes, comments (+ author), core + app properties |
| PPTX | groups (recursive), placeholders, tables, pictures (OCR + alt text), charts, SmartArt, footer placeholders, speaker notes and other notes-page text, legacy and modern comments (+ author), hidden slides (marked), master/layout/notes-master text, core + app properties |
| DOCX + PPTX | **safety-net sweep**: every text node (`w:t`, `a:t`) in the package that no extractor used is emitted as `other text (<part>)` with an `UNCLAIMED_TEXT` warning |

Deleted tracked-change text is not extracted, because it is not part of the
document's content.

### 4.6 Warning codes

| Code | Meaning |
|---|---|
| `NO_TEXT_EXTRACTED` | a non-empty file produced no blocks |
| `EMPTY_FILE` | the file has 0 bytes |
| `PAGE_NO_TEXT` | a PDF page produced no blocks (detail says if it looks blank) |
| `LOW_OCR_CONFIDENCE` | a block's mean OCR confidence is below 0.6 |
| `LOW_COVERAGE` | a scanned page has visible ink but very few characters were read |
| `SKIPPED_IMAGE` | images not OCR'd (EMF/WMF, under 50×50 px, linked, unreadable) |
| `UNCLAIMED_TEXT` | the sweep found text outside known structures |
| `UNSUPPORTED_OBJECT` | embedded OLE objects / attached files whose content is not extracted |
| `EXTENSION_MISMATCH` | the content type differs from the file extension |

### 4.7 Known limitations

* Borderless tables in images are read as text lines, without cell structure.
* DOCX has no fixed page numbers, so DOCX locations use section and paragraph position.
* EMF/WMF images and OLE objects are not OCR'd/opened (they are reported).
* Values inside a chart's embedded workbook that the chart does not display are not read.
* OCR boxes are exact on upright images; after rotation/deskew they refer to the corrected image.
* Handwriting and very low-quality scans depend on Tesseract and may need a human check (see the warnings).
* Text normalization folds look-alike characters (dashes, fullwidth, zero-width) but does not fix OCR errors.

### 4.8 Tests

`python -m pytest src/pii_pipeline/extraction/tests` covers these areas. All
files are synthetic and built at test time, and OCR tests are skipped if
Tesseract is missing.

* **Unit:** normalization, XY-cut (columns vs. forms), header detection, cell
  spans, render, deduplication, contract checks.
* **PDF:** digital, scanned, mixed native/scan, native and scanned ruled
  tables, image on a digital page, multi-page, rotated 90°, skewed 3°, blank
  page, encrypted file, annotations, form fields, link targets, metadata.
* **DOCX:** headings, lists, tracked changes, hidden link, table header +
  merges + nested table, text box once, image OCR + alt text, skipped tiny
  image, headers/footers over 3 sections, footnote, endnote, comment, orphan
  part found by the sweep, metadata, reading order, determinism.
* **PPTX:** title first, nested groups in visual order, footer, speaker notes,
  legacy and modern comments, table header, merged cells, picture OCR + alt
  text, chart, hidden slide, master text, no template prompts, sweep,
  metadata, determinism.
* **Safety:** no `print`, `logging` or network imports in the module; nothing
  planted is printed, logged or warned; CLI shows no text; `--out` only inside
  `data/`; errors carry no content; unsupported, legacy, ZIP, empty and
  renamed files are handled.

## 5. Proposed shared-schema change (not applied)

`schemas.py` was not modified. Positions currently travel in the parallel
`BlockMeta` list. Proposal for the team (open as an issue): add one optional
field so traceability survives without a side channel:

```python
@dataclass
class TextBlock:
    ...
    meta: dict | None = None   # page, bbox, bbox_unit, kind, source, hidden,
                               # table_id, row_index, cells, words (no text)
```

It is backwards compatible (defaults to `None`). Redaction's `TraceRecord`
could then report page and box for each finding.

## 6. Notes for other roles

* **Detection:** every block is cleaned text on one line. Table rows contain
  injected header labels (`Name: …`), which help NER and context rules.
  `ocr_confidence` and `BlockMeta.words` let you lower thresholds on OCR text.
* **Redaction:** `location` strings never contain shape or field names (only
  numbers), so they are safe for the report. Offsets follow the contract.
* **Evaluation:** match ground truth by value span within a block, not by
  whole-block text, because header labels are added to table rows. The
  `kind`/`source` in `BlockMeta` allow per-source metrics (native vs. OCR).
* **Application:** call `extract_document_detailed` and show
  `result.warnings` to the user. They are safe to display.
