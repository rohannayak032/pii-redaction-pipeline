"""
Integration layer for PII detection.

This module combines the results from three detectors:
- Detector A: regex-based rules, phone-number validation, and Presidio.
- Detector B: supplementary GLiNER-based person and address detection.
- Detector C: complete Indian addresses from a TinyBERT address NER model.

The results are combined into a single list of Entity objects.
Exact duplicates are removed using the source file, block index,
character offsets, and PII category.

Note:
- Entities with overlapping spans are not automatically merged.
- Different PII categories at the same span are preserved.
- Deduplication does not guarantee that every prediction is correct.
"""

from pii_pipeline.schemas import TextBlock, Entity
from pii_pipeline.detection.patterns import find_patterns
from pii_pipeline.detection.detector_b import detect_with_gliner
from pii_pipeline.detection.detector_address import detect_indian_addresses


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
    for person names and address components.
    Detector C finds whole Indian addresses, so the full address is
    redacted rather than only the components GLiNER spots.
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
        # Detector B currently focuses on person names and address
        # components; it supplements rather than replaces Detector A.
        candidates.extend(detect_with_gliner([block]))

        # ---------------------------------------------------------
        # Detector C: complete Indian addresses
        # ---------------------------------------------------------

        # Run the address NER model; it merges house, road, locality,
        # city, state and PIN code into one ADDRESS span.
        candidates.extend(detect_indian_addresses([block]))

        # ---------------------------------------------------------
        # Merge results and remove exact duplicates
        # ---------------------------------------------------------

        for entity in candidates:

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

    return entities
