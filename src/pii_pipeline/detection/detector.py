"""
Integration layer for PII detection.

This module combines the results from three detectors:
- Detector A: regex-based rules, phone-number validation, and Presidio.
- Detector B: supplementary GLiNER-based person detection.
- Detector C: complete Indian addresses from a TinyBERT address NER model.

The model spans (person names, model addresses) are then cleaned:
- model spans in OCR text that extraction flags as unreliable are ignored;
- a model span is cut where it runs into an email, phone or ID, so one
  table row does not become one giant "name";
- a name span is split where a new initial starts another name
  ("D. R. Okonjo A. V. Chatterjee"), table and role words are trimmed
  from its edges ("C | E. Bertucci", "R. Quintanilla Dir"), and spans
  that cannot be names are dropped;
- a one-word name is kept only when two detectors agree on it, and where
  detectors split names differently the finer split wins;
- a model address holding a date is dropped.
Finally every repeat of a multi-word name found in a file is redacted too.

The results are combined into a single list of Entity objects.
Exact duplicates are removed using the source file, block index,
character offsets, and PII category.

Note:
- Entities with overlapping spans are not automatically merged.
- Different PII categories at the same span are preserved.
- Deduplication does not guarantee that every prediction is correct.
"""

import re
from collections import defaultdict
from dataclasses import replace

from pii_pipeline.schemas import TextBlock, Entity
from pii_pipeline.extraction.validation import LOW_OCR_CONFIDENCE
from pii_pipeline.detection.patterns import find_patterns
from pii_pipeline.detection.detector_b import detect_with_gliner
from pii_pipeline.detection.detector_address import detect_indian_addresses


# Types produced by the NER models. Everything else (regex, checksum,
# phone library) is precise and serves as an anchor a model span must
# not run across.
_MODEL_TYPES = {"PERSON", "ADDRESS"}

# Role, status and table-heading words that sit next to names in tables
# and slides. Trimmed from the edges of a name span; a span made only of
# them is not a name ("Business Owner", "CHIEF RISK OFFICER").
_NOT_NAME = {
    # roles and titles
    "chief", "officer", "director", "dir", "manager", "mgr", "head", "lead",
    "owner", "president", "vp", "svp", "evp", "ceo", "cfo", "cro", "cio",
    "coo", "cto", "ciso", "chair", "chairman", "chairperson", "secretary",
    "analyst", "engineer", "administrator", "admin", "consultant", "contact",
    "primary", "secondary", "business", "vendor", "supplier", "customer",
    "client", "user", "internal", "external", "team", "group", "committee",
    "board", "member", "staff", "employee", "executive", "senior", "junior",
    "deputy", "assistant", "associate", "partner", "principal", "specialist",
    "coordinator", "representative", "sponsor", "approver", "reviewer",
    "author", "editor", "counsel", "general",
    # RACI
    "responsible", "accountable", "consulted", "informed",
    # status and risk ratings
    "high", "low", "medium", "moderate", "critical", "elevated", "severe",
    "minor", "major", "zero", "open", "closed", "pending", "approved",
    "overdue", "none",
    # table headings
    "name", "task", "title", "role", "date", "status", "department",
    "division", "divisional", "function", "region", "comments", "comment",
    "notes", "signature", "page", "version", "policy", "risk", "control",
    "total",
    # document and process nouns ("Onboarding Workflow", "Data Protection")
    "workflow", "process", "procedure", "assessment", "review", "report",
    "plan", "programme", "program", "framework", "standard", "register",
    "questionnaire", "template", "form", "system", "module", "portal",
    "login", "response", "security", "protection", "information", "data",
    "onboarding", "offboarding", "training", "management", "compliance",
    "governance", "privacy", "audit", "incident",
}

# A date never sits inside an address; a model "address" holding one is a
# table row ("15/08/2026 applied, Mumbai").
_DATE = re.compile(r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b")

# Function words never appear inside a name ("Contains Any Response",
# "The Data Protection Officer"). "Will" and "May" are left out: they
# are also first names.
_FUNCTION_WORDS = {
    "the", "a", "an", "of", "and", "or", "for", "to", "in", "on", "at", "by",
    "with", "any", "all", "no", "not", "this", "that", "these", "those",
    "our", "your", "their", "its", "is", "are", "be", "if",
}

# An initial such as "A." or "L.-E.".
_INITIAL = re.compile(r"(?:[A-Z]\.-?)+")


def _is_junk(token: str, mixed_case: bool, last: bool = False) -> bool:
    """True if `token` cannot be the first (or, with `last`, last) word of a name."""
    word = token.strip(".,;:()[]|-–—'\"")
    return (
        not any(c.isalpha() for c in word)        # "|", "-"
        or any(c.isdigit() for c in word)         # "EMP-38104", "30/09/2026"
        or word[0].islower()                      # "gap,", "internal"
        or word.lower() in _NOT_NAME
        or (word.lower() in _FUNCTION_WORDS and not _INITIAL.fullmatch(token))  # not "A."
        or (len(word) == 1 and not token.endswith("."))   # RACI letter "C"
        # An acronym after a mixed-case name ("... Chatterjee RC"); an
        # all-caps name like "PRIYA NAIR" keeps its words, and a leading
        # "KC" or "DK" is a first name.
        or (last and mixed_case and word.isupper() and len(word) > 1 and "." not in token)
    )


def _outside_anchors(entity: Entity, anchors: list[Entity], text: str) -> Entity | None:
    """Cut a model span where it runs into a precise detection.

    A name keeps its first remaining piece ("Naomi K. Osadebe EMP-41077
    IAM Engineer" -> "Naomi K. Osadebe"). A model address that runs into
    an ID or phone is a table row, not an address, and is dropped.
    Returns the entity unchanged when it touches no anchor.
    """
    hits = sorted(
        (a for a in anchors if a.start < entity.end and entity.start < a.end),
        key=lambda a: a.start,
    )
    if not hits:
        return entity
    if entity.pii_type != "PERSON":
        return None

    pieces, cursor = [], entity.start
    for anchor in hits:
        if anchor.start > cursor:
            pieces.append((cursor, anchor.start))
        cursor = max(cursor, anchor.end)
    if cursor < entity.end:
        pieces.append((cursor, entity.end))

    # Strip whitespace and separators left at the cut.
    stripped = []
    for start, end in pieces:
        while start < end and not text[start].isalnum():
            start += 1
        while end > start and not (text[end - 1].isalnum() or text[end - 1] == "."):
            end -= 1
        if start < end:
            stripped.append((start, end))

    if not stripped:
        return None
    start, end = stripped[0]
    return replace(entity, start=start, end=end, value=text[start:end])


def _clean_person(entity: Entity, text: str) -> list[Entity]:
    """Split a name span into names, trim non-name edge words, drop non-names."""
    tokens = [
        (entity.start + m.start(), entity.start + m.end(), m.group())
        for m in re.finditer(r"\S+", text[entity.start:entity.end])
    ]

    # A new initial after a finished name starts another name:
    # "D. R. Okonjo A. V. Chatterjee", but not "Naomi K. Osadebe".
    # A separator ends one: "Siddharth Gaikwad, Srinivas Teppa".
    segments, current = [], []
    for token in tokens:
        if current and (
            current[-1][2][-1] in ",;|"
            or (
                len(current) >= 2
                and _INITIAL.fullmatch(token[2])
                and not _INITIAL.fullmatch(current[-1][2])
            )
        ):
            segments.append(current)
            current = []
        current.append(token)
    if current:
        segments.append(current)

    trimmed = []
    for segment in segments:
        # An all-caps run of 4+ words is a heading ("MEASURE TARGET MEASURE OWNER").
        if len(segment) >= 4 and all(t[2].isupper() for t in segment):
            continue
        mixed_case = any(not t[2].isupper() for t in segment)
        while segment and _is_junk(segment[0][2], mixed_case):
            segment = segment[1:]
        while segment and _is_junk(segment[-1][2], mixed_case, last=True):
            segment = segment[:-1]
        # Table cells list names with no separator ("Chris Ott Melisa
        # Cardozo DK Koran"): an even run of 4+ capitalised words with no
        # initials is read as two-word names.
        if (
            len(segment) >= 4
            and len(segment) % 2 == 0
            and all(t[2][0].isupper() and not _INITIAL.fullmatch(t[2]) for t in segment)
        ):
            trimmed.extend(segment[i:i + 2] for i in range(0, len(segment), 2))
        elif segment:
            trimmed.append(segment)

    cleaned = []
    for segment in trimmed:
        start, end = segment[0][0], segment[-1][1]
        # Drop edge punctuation, keeping the dot of a final initial.
        while start < end and not text[start].isalnum():
            start += 1
        while end > start and text[end - 1] in ",;:()[]|-–—'\"":
            end -= 1
        if text[end - 1] == "." and not _INITIAL.fullmatch(segment[-1][2]):
            end -= 1

        if any(
            t[2].strip(".,;:()").lower() in _FUNCTION_WORDS and not _INITIAL.fullmatch(t[2])
            for t in segment
        ):
            continue
        # "WR", "VP", "Y": too short or an acronym to be a one-word name.
        if len(segment) == 1:
            word = segment[0][2].strip(".")
            if len(word) <= 2 or word.isupper():
                continue

        cleaned.append(replace(entity, start=start, end=end, value=text[start:end]))
    return cleaned


def _clean_block(block: TextBlock, candidates: list[Entity]) -> list[Entity]:
    """Apply the anchor cut, name cleanup and one-word agreement to one block."""
    anchors = [
        e for e in candidates
        if e.pii_type not in _MODEL_TYPES or e.detector.startswith("regex")
    ]

    # Extraction flags OCR below this as unreliable; names the models find
    # there are mostly misread words ("Pee Leder Fobesligy").
    unreliable = block.ocr_confidence is not None and block.ocr_confidence < LOW_OCR_CONFIDENCE

    cleaned = []
    for entity in candidates:
        if entity.pii_type in _MODEL_TYPES and not entity.detector.startswith("regex"):
            if unreliable or (entity.pii_type == "ADDRESS" and _DATE.search(entity.value)):
                continue
            entity = _outside_anchors(entity, anchors, block.text)
            if entity is None:
                continue
        if entity.pii_type == "PERSON":
            cleaned.extend(_clean_person(entity, block.text))
        else:
            cleaned.append(entity)

    # A one-word name ("Tutu", "Optiv") is kept only when another detector
    # found exactly the same span.
    persons = [(e.start, e.end, e.detector) for e in cleaned if e.pii_type == "PERSON"]
    cleaned = [
        e for e in cleaned
        if e.pii_type != "PERSON"
        or len(e.value.split()) > 1
        or any((s, t) == (e.start, e.end) and d != e.detector for s, t, d in persons)
    ]

    # Where detectors split names differently, the finer split wins: a span
    # overlapping two or more names from another detector ("Burney Jyoti
    # Karwal" vs "KC Burney" + "Jyoti Karwal") would merge them into one.
    persons = {(e.start, e.end, e.detector) for e in cleaned if e.pii_type == "PERSON"}
    return [
        e for e in cleaned
        if e.pii_type != "PERSON"
        or len({(s, t) for s, t, d in persons
                if d != e.detector and s < e.end and e.start < t}) < 2
    ]


def _propagate_names(blocks: list[TextBlock], entities: list[Entity]) -> list[Entity]:
    """Redact every repeat, in the same file, of a multi-word name found in it.

    The models miss some occurrences of a name they found elsewhere; an
    unredacted repeat would leak it.
    """
    names: dict[str, dict[str, Entity]] = defaultdict(dict)
    for e in entities:
        if e.pii_type == "PERSON" and len(e.value.split()) > 1:
            names[e.file].setdefault(e.value, e)

    taken: dict[tuple[str, int], list[tuple[int, int]]] = defaultdict(list)
    for e in entities:
        taken[(e.file, e.block_index)].append((e.start, e.end))

    added = []
    for block in blocks:
        spans = taken[(block.file, block.index)]
        for value, source in names[block.file].items():
            for m in re.finditer(r"(?<!\w)" + re.escape(value) + r"(?!\w)", block.text):
                if any(s < m.end() and m.start() < t for s, t in spans):
                    continue
                spans.append((m.start(), m.end()))
                added.append(replace(
                    source, block_index=block.index, start=m.start(), end=m.end(),
                    detector="propagated",
                ))
    return entities + added


def detect(blocks: list[TextBlock]) -> list[Entity]:
    """
    Detect PII across multiple text blocks using all three detectors.

    Args:
        blocks: Text blocks produced by the extraction stage.

    Returns:
        A list of detected Entity objects with duplicate detections
        removed. Character offsets refer to each block's original text.

    Detector A identifies structured PII and person-name candidates.
    Detector B supplements these results with GLiNER predictions
    for person names.
    Detector C finds whole Indian addresses, so the full address is
    redacted rather than only some of its parts.
    """

    # Store the final set of detected entities.
    entities: list[Entity] = []

    # Track entity identities that have already been added.
    # Including the file and block index prevents identical text in
    # different locations from being incorrectly treated as a duplicate.
    # Including pii_type preserves different classifications at the same span.
    seen: set[tuple[str, int, int, int, str]] = set()

    for block in blocks:

        # ---------------------------------------------------------
        # Detector A: structured and rule-based PII detection
        # ---------------------------------------------------------

        # Run regex rules, phone-number validation, contextual DOB
        # detection, and Presidio-based person-name detection.
        candidates = find_patterns(block)

        # ---------------------------------------------------------
        # Detector B: supplementary GLiNER detection
        # ---------------------------------------------------------

        # Run GLiNER on this block and append its accepted predictions.
        # Detector B finds person names; it supplements rather than
        # replaces Detector A.
        candidates.extend(detect_with_gliner([block]))

        # ---------------------------------------------------------
        # Detector C: complete Indian addresses
        # ---------------------------------------------------------

        # Run the address NER model; it merges house, road, locality,
        # city, state and PIN code into one ADDRESS span.
        candidates.extend(detect_indian_addresses([block]))

        # ---------------------------------------------------------
        # Clean model spans, then remove exact duplicates
        # ---------------------------------------------------------

        for entity in _clean_block(block, candidates):

            # Define an entity's identity using its source location,
            # character span, and PII category.
            # Confidence and detector name are intentionally excluded,
            # so the same entity found by both detectors is deduplicated.
            key = (
                entity.file,
                entity.block_index,
                entity.start,
                entity.end,
                entity.pii_type,
            )

            # Skip an entity if the same identity has already been added.
            if key in seen:
                continue

            # Record this identity before adding the entity to the results.
            seen.add(key)
            entities.append(entity)

    return _propagate_names(blocks, entities)
