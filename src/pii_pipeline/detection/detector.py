"""PII detection: takes TextBlocks, returns Entities.

Ported from my earlier standalone implementation and refactored to follow
this repo's schemas.py. Detection only: replacing the PII with placeholders
is done by the redaction module, so nothing here changes the text.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from math import isfinite

from presidio_analyzer import (
    AnalyzerEngine,
    Pattern,
    PatternRecognizer,
    RecognizerRegistry,
    RecognizerResult,
)

from pii_pipeline.schemas import TextBlock, Entity

# ---------------------------------------------------------------------------
# Engine: created once, when this module is first imported
# ---------------------------------------------------------------------------
registry = RecognizerRegistry()
registry.load_predefined_recognizers()
analyzer = AnalyzerEngine(registry=registry)


def _add(entity, name, regex, score):
    """Register one regex rule for one entity type."""
    analyzer.registry.add_recognizer(
        PatternRecognizer(
            supported_entity=entity,
            patterns=[Pattern(name=name, regex=regex, score=score)],
        )
    )


# ---------------------------------------------------------------------------
# Regex rules
# ---------------------------------------------------------------------------
# Phone numbers: Indian / international, and numbers with a bracketed area code
_add(
    "PHONE_NUMBER", "indian_int_phone",
    r"(?:\+?91[\s.-]*)?[6-9]\d{4}[\s.-]*\d{5}|\+?\d{1,3}[\s.-]?\(?\d{1,4}\)?[\s.-]?\d{3,5}[\s.-]?\d{4,5}",
    1.0,
)
_add(
    "PHONE_NUMBER", "bracketed_area_code_phone",
    r"\+?\d{1,3}[ .-]?\(\d{2,4}\)[ .-]?\d{3,4}(?:[ .-]\d{3,4})?",
    1.0,
)

# LinkedIn / URL
_add(
    "URL", "custom_url_pattern",
    r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w\-]+/?|(?:https?://|www\.)[a-zA-Z0-9.\-]+(?::\d+)?(?:/[^\s]*)?",
    1.0,
)

# Email with ANY top-level domain (the built-in one rejects unknown TLDs)
_add(
    "EMAIL_ADDRESS", "any_tld_email",
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
    1.0,
)

# "A. Okonkwo-Bell", "E. Bertucci": initial + surname, which spaCy often misses
_add(
    "PERSON", "initial_surname",
    r"\b[A-Z]\.[ \t]?(?!(?:The|This|That|These|Those|In|If|It|For|To|On|At|As|An|And|But|Or|We|Our|You|Please|Each|All|Any|Once|When|Where|Which|Not|No|Yes|Note|See|Use|Add|Click|Select|Enter|Set|Open|Ensure|After|Before|Then|Also)\b)[A-Z][a-z]+(?:['-][A-Z][a-z]+)*\b",
    0.95,
)

# Identifiers (also matter for OCR'd scans, where the NER model sees less context)
# US SSN in 3-2-4 form. The built-in rule rejects 9xx numbers, common in test data.
_add("US_SSN", "ssn_3_2_4", r"\b\d{3}-\d{2}-\d{4}\b", 0.9)
# Indian PAN, e.g. AQBPR7741L
_add("IN_PAN", "pan", r"\b[A-Z]{5}\d{4}[A-Z]\b", 0.9)
# Passport numbers when introduced by the word "passport"
analyzer.registry.add_recognizer(
    PatternRecognizer(
        supported_entity="PASSPORT",
        patterns=[Pattern(name="passport_ctx", regex=r"\b[A-Z]{1,2}\d{6,9}\b", score=0.9)],
        context=["passport"],
    )
)
# Employee / director / vendor identifiers: EMP-38104, DIR-0042, MER-IN-4471
_add("EMPLOYEE_ID", "emp_id", r"(?<![A-Za-z0-9])EMP-(?:[A-Z]{2}-)?\d{3,5}(?!\d)", 0.9)
_add("DIRECTOR_ID", "dir_id", r"(?<![A-Za-z0-9])DIR-(?:[A-Z]{2}-)?\d{3,5}(?!\d)", 0.9)
_add("VENDOR_ID", "vendor_id", r"(?<![A-Za-z0-9])MER-(?:[A-Z]{2}-)?\d{3,5}(?!\d)", 0.9)

# Street addresses: "88 Willowbank Court, Hoboken, NJ 07030"
_add(
    "STREET_ADDRESS", "us_street_address",
    r"\b\d{1,5}[ \t]+(?:[A-Z][A-Za-z.'-]+[ \t]+){1,3}"
    r"(?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Court|Ct|Crescent|Drive|Dr|Boulevard|Blvd|Way|Place|Pl|Terrace|Square)\b\.?"
    r"(?:,?[ \t]*(?:Apartment|Apt|Suite|Ste|Unit|Floor)[ \t]*[\w-]+)?"
    r"(?:,[ \t]*[A-Z][A-Za-z.' -]+)?"
    r"(?:,[ \t]*[A-Z]{2}[ \t]+\d{5}(?:-\d{4})?)?",
    0.85,
)

# Names introduced by a title: "Ms Prieto-Ramos", "Dr. Jane Smith"
_add(
    "PERSON", "titled_name",
    r"\b(?:Mr|Mrs|Ms|Miss|Mx|Dr|Prof)\.?[ \t]+[A-Z][a-z]+(?:[-'][A-Z][a-z]+)*(?:[ \t]+[A-Z][a-z]+(?:[-'][A-Z][a-z]+)*)?\b",
    0.9,
)

# A name directly followed by an ID: "Gregor Halvorsen (EMP-35440)"
_add(
    "PERSON", "name_before_emp_id",
    r"\b[A-Z][a-z]+(?:[ \t]+[A-Z]\.){0,2}[ \t]+[A-Z][a-z]+(?:[-'][A-Z][a-z]+)*(?=[ \t]*[\(\u2014,-]*[ \t]*(?:EMP|DIR|MER)-)",
    0.9,
)

# Fragments of phone numbers left behind when a table cell wraps over lines
_add("PHONE_NUMBER", "phone_prefix_no_tail_a", r"\+\d{1,3}[ ]?\(\d{2,4}\)(?![ \t.-]*\d)", 0.8)
_add("PHONE_NUMBER", "phone_prefix_no_tail_b", r"\+\d{1,3}[ ]\d{2,3}(?![ \t.-]*\d)", 0.7)
_add("PHONE_NUMBER", "phone_prefix_no_tail_c", r"\+\d{3,4}(?![ \t.-]*\d)", 0.7)
_add("PHONE_NUMBER", "phone_tail_dash", r"(?<![\w-])\d{3}-\d{4}(?![\w-])", 0.7)
_add("PHONE_NUMBER", "phone_prefix_fragment",
     r"\+\d{1,3}[ ]?\(?\d{2,5}\)?(?=[ \t]{2,}\S|[ \t]*$)", 0.8)
_add("PHONE_NUMBER", "phone_tail_fragment_a", r"(?m)^[ \t]*\d{3}[ -]\d{4}[ \t]*(?=\s|$)", 0.7)
_add("PHONE_NUMBER", "phone_tail_fragment_c", r"(?m)^[ \t]*\d{5}[ \t]*(?=\s|$)", 0.6)
_add("PHONE_NUMBER", "phone_tail_fragment_b", r"(?m)^[ \t]*\d{4}[ ]?\d{4}[ \t]*(?=\s|$)", 0.7)

# ---------------------------------------------------------------------------
# Word lists and settings used by the false-positive filters
# ---------------------------------------------------------------------------
# Frequency words that the date recognizer wrongly tags as DATE_TIME
FREQUENCY_WORDS = {
    "annual", "annually", "quarterly", "monthly", "weekly", "daily",
    "yearly", "biannual", "semi-annual", "semiannual", "biannually",
}

# Product / company / UI words that the NER model wrongly labels as PERSON.
# Add your own organisation and tool names here.
NON_PERSON_TERMS = {
    "optiv", "torii", "ironclad", "onetrust", "cadence", "oracle", "navigate",
    "click", "select", "choose", "enter", "assign", "open", "email", "cloud",
    "saas", "response", "operator", "trigger", "condition", "action", "task",
    "control", "risk", "rule", "vendor", "tier", "category", "workflow",
    "contains", "template", "questionnaire", "assessment", "stage", "name",
    "confidential", "appendix", "section", "launching", "review", "reject", "greater",
    "ned", "completes", "rcsa", "limit", "miss", "loss", "engineer",
    "ii", "leaver", "account", "critical", "high", "iam", "uplift",
    "pending", "contract", "negative", "rate", "mumbai", "office",
    "unsupported", "components", "actionability", "legacy", "platform",
    "above", "threshold", "reconciliation", "process", "impact",
    "tolerance", "sent", "offshore", "customer", "redress", "custo",
    "meridian", "staffing", "northwind", "analytics", "veritrace", "halloran",
}

MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|"
    "november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
)
MONTH_RE = re.compile(r"\b(" + MONTHS + r")\b", re.IGNORECASE)
NUMERIC_DATE_RE = re.compile(
    r"\b((19|20)\d{2}[/.\-](0[1-9]|1[0-2])[/.\-](0[1-9]|[12]\d|3[01])|"
    r"(0[1-9]|[12]\d|3[01])[/.\-](0[1-9]|1[0-2])[/.\-](19|20)\d{2})\b"
)
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
SECTION_WORD_RE = re.compile(
    r"(appendix|section|figure|table|step|scenario|part|annex|question)\s*$",
    re.IGNORECASE,
)
INITIAL_NAME_RE = re.compile(r"^[A-Z]\.\s?[A-Z]")

# Broad countries are not worth redacting
COUNTRY_WHITELIST = {
    "us", "usa", "united states", "canada", "uk", "united kingdom",
    "india", "germany", "finland",
}

EMAIL_LOCAL_RE = re.compile(r"\b([A-Za-z])\.?([A-Za-z][A-Za-z'\-]+)@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
NAME_PAIR_RE = re.compile(r"\b([A-Z][\w'-]+)[ \t]+([A-Z][\w'-]+)\b")

DURATION_RE = re.compile(
    r"\b(\d+\+?\s*(years?|months?|yrs?)|nearly\s*\d+\s*years?)\b", re.IGNORECASE
)
STANDALONE_YEAR_RE = re.compile(r"^\b(19|20)\d{2}\b$")
PHONE_DIGITS_RE = re.compile(r"^\+?\d[\d\s.-]{7,14}\d$")

# Entity types we ask Presidio for
SUPPORTED_ENTITIES = [
    "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "PERSON", "LOCATION",
    "IP_ADDRESS", "DATE_TIME", "URL", "US_SSN", "IN_PAN", "PASSPORT",
    "EMPLOYEE_ID", "DIRECTOR_ID", "VENDOR_ID", "STREET_ADDRESS",
]

# Presidio's names -> the names used in this pipeline
TYPE_MAP = {
    "EMAIL_ADDRESS": "EMAIL",
    "PHONE_NUMBER": "PHONE",
    "US_SSN": "SSN",
    "DATE_TIME": "DATE",
    "STREET_ADDRESS": "LOCATION",
    "CREDIT_CARD": "CREDIT_CARD",
    "PERSON": "PERSON",
    "LOCATION": "LOCATION",
    "IP_ADDRESS": "IP_ADDRESS",
    "URL": "URL",
    "IN_PAN": "IN_PAN",
    "PASSPORT": "PASSPORT",
    "EMPLOYEE_ID": "EMPLOYEE_ID",
    "DIRECTOR_ID": "DIRECTOR_ID",
    "VENDOR_ID": "VENDOR_ID",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def normalize_text(text: str) -> str:
    """Replace hidden non-breaking spaces and similar characters with a normal
    space. One character in, one character out, so offsets stay valid."""
    return re.sub(r"[\xa0\u200b\u200e\u200f\u202f]", " ", text)


def looks_like_real_date(entity_text: str) -> bool:
    """Keep DATE_TIME only for calendar dates (month names, 12/05/1990,
    2026-01-04). Durations like '14 Days' or 'quarterly' are not PII."""
    if MONTH_RE.search(entity_text) or NUMERIC_DATE_RE.search(entity_text):
        return True
    return bool(YEAR_RE.search(entity_text) and len(entity_text.split()) > 1)


def names_from_emails(text: str, hint_text: str | None = None) -> list[RecognizerResult]:
    """Directory-style documents list 'p.raghunathan@corp.com' next to
    'Priyanka Raghunathan'. Use the emails as a hint to find full names that
    the NER model misses."""
    keys = {}
    for m in EMAIL_LOCAL_RE.finditer(hint_text if hint_text is not None else text):
        initial, surname = m.group(1).lower(), m.group(2).lower().replace("-", "")
        keys[surname] = initial
    results = []
    if not keys:
        return results
    for m in NAME_PAIR_RE.finditer(text):
        first, last = m.group(1), m.group(2)
        initial = keys.get(last.lower().replace("-", ""))
        if initial and first.lower().startswith(initial):
            results.append(RecognizerResult("PERSON", m.start(), m.end(), 0.95))
    return results


def filter_false_positives(results: list[RecognizerResult], text: str) -> list[RecognizerResult]:
    """Drop findings that are not really PII (dates, locations, person names)."""
    filtered = []
    for res in results:
        span = text[res.start:res.end].strip()
        low = span.lower()

        # Spans that run across a line break swallow headings / neighbouring lines
        if res.entity_type in ("PERSON", "LOCATION") and "\n" in span:
            continue

        if res.entity_type == "LOCATION":
            if any(tok in NON_PERSON_TERMS for tok in re.findall(r"[A-Za-z']+", low)):
                continue
            if re.search(r"[\"\u201c\u201d]", span):
                continue
            if (
                low in ("geographies", "global", "world")
                or low in COUNTRY_WHITELIST
                or (low.startswith("the ") and low[4:] in COUNTRY_WHITELIST)
            ):
                continue

        if res.entity_type == "PERSON":
            tokens = re.findall(r"[A-Za-z']+", low)
            # identifiers like QRC_CL_1.3, or words that are really UI/product terms
            if "_" in span or any(ch.isdigit() for ch in span) or span.endswith("-"):
                continue
            if any(tok in NON_PERSON_TERMS for tok in tokens):
                continue
            # "Appendix C. The ..." is not a person
            if INITIAL_NAME_RE.match(span) and SECTION_WORD_RE.search(
                text[max(0, res.start - 20):res.start]
            ):
                continue

        if res.entity_type == "URL" and re.fullmatch(r"[A-Z]{1,4}\.[A-Z]{1,4}", span):
            continue  # rule IDs such as WR.MP / WR.SV

        if res.entity_type == "PASSPORT":
            context_start = max(0, res.start - 40)
            context = text[context_start:res.start]
            if not re.search(r"\bpassport\b[^\r\n]{0,40}$", context, re.IGNORECASE):
                continue

        if res.entity_type == "DATE_TIME":
            # policy / incident reference codes, e.g. PBR-2026-003
            if re.search(r"(?:PBR|ACC|ISS|INC|GRP|RSK|CTL)-\d{4}", span, re.IGNORECASE):
                continue
            # short month-year tokens without a 4-digit year, e.g. Feb-79
            if re.match(
                r"^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[-/\s]\d{2}$",
                span, re.IGNORECASE,
            ):
                continue
            if low in FREQUENCY_WORDS:
                continue
            # work-experience durations ("25+ years") and phone-digit artifacts
            if DURATION_RE.search(span) or PHONE_DIGITS_RE.match(span):
                continue
            if STANDALONE_YEAR_RE.match(span):
                continue
            if not looks_like_real_date(span):
                continue

        filtered.append(res)
    return filtered


def filter_overlapping_results(results: list[RecognizerResult]) -> list[RecognizerResult]:
    """Remove exact same-type duplicates; leave overlapping findings intact."""
    unique: dict[tuple[str, int, int], RecognizerResult] = {}
    for result in results:
        key = (result.entity_type, result.start, result.end)
        previous = unique.get(key)
        if previous is None or result.score > previous.score:
            unique[key] = result
    return sorted(
        unique.values(),
        key=lambda r: (r.start, r.end, r.entity_type),
    )


# ---------------------------------------------------------------------------
# The one function the rest of the pipeline calls
# ---------------------------------------------------------------------------
def detect(blocks: Sequence[TextBlock]) -> list[Entity]:
    """Find PII in every block.

    Offsets (start, end) are relative to the block's own text, with end
    excluded, so block.text[e.start:e.end] == e.value.
    """
    # Text of each whole file: emails on one page help find names on another.
    parts: dict[str, list[str]] = {}
    for b in blocks:
        parts.setdefault(b.file, []).append(b.text)
    hints = {f: normalize_text("\n".join(p)) for f, p in parts.items()}

    origin: dict[int, str] = {}  # id(result) -> which step found it

    # Pass 1: analyse every block and remember the names found in each file
    analysed = []
    known_people: dict[str, set[str]] = {}
    for b in blocks:
        text = normalize_text(b.text)
        if len(text) != len(b.text):
            raise ValueError("normalize_text changed the length; offsets would drift")
        if not text.strip():
            continue

        results = list(analyzer.analyze(
            text=text,
            entities=SUPPORTED_ENTITIES,
            language="en",
            score_threshold=0.2,
        ))
        for r in results:
            origin[id(r)] = "presidio"

        hinted = names_from_emails(text, hints[b.file])
        for r in hinted:
            origin[id(r)] = "email-hint"
        results += hinted

        # Trim stray spaces / newlines from the edges of each span
        for r in results:
            while r.start < r.end and text[r.start].isspace():
                r.start += 1
            while r.end > r.start and text[r.end - 1].isspace():
                r.end -= 1

        valid = filter_false_positives(results, text)

        people = known_people.setdefault(b.file, set())
        for r in valid:
            if r.entity_type == "PERSON":
                people.add(text[r.start:r.end].strip())

        analysed.append((b, text, valid))

    # Pass 2: name consistency, overlap removal, convert to Entity
    entities: list[Entity] = []
    for b, text, valid in analysed:
        # If a name was found anywhere in this file, flag every other
        # occurrence of it too (the NER model is inconsistent).
        for name in known_people[b.file]:
            if len(name) < 5 or "\n" in name:
                continue
            pattern = r"(?<![\w])" + re.escape(name) + r"(?![\w])"
            for m in re.finditer(pattern, text):
                r = RecognizerResult("PERSON", m.start(), m.end(), 0.9)
                origin[id(r)] = "name-consistency"
                valid.append(r)

        for r in filter_overlapping_results(valid):
            if not (0 <= r.start < r.end <= len(b.text)):
                continue
            score = float(r.score)
            if not isfinite(score):
                continue
            entities.append(Entity(
                file=b.file,
                block_index=b.index,
                start=r.start,
                end=r.end,
                pii_type=TYPE_MAP[r.entity_type],
                confidence=min(max(score, 0.0), 1.0),
                detector=f"presidio.{origin.get(id(r), 'presidio')}",
                value=b.text[r.start:r.end],
            ))
    return entities
