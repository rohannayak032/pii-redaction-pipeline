from pii_pipeline.schemas import TextBlock, Entity
from pii_pipeline.detection.patterns import find_patterns


def detect(blocks: list[TextBlock]) -> list[Entity]:
    entities: list[Entity] = []
    for block in blocks:
        entities.extend(find_patterns(block))
    return entities