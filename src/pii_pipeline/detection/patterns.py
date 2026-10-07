import re
from pii_pipeline.schemas import TextBlock, Entity

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def find_patterns(block: TextBlock) -> list[Entity]:
    found = []
    for m in EMAIL.finditer(block.text):
        found.append(Entity(
            file=block.file,
            block_index=block.index,
            start=m.start(),
            end=m.end(),
            pii_type="EMAIL",
            confidence=0.9,
            detector="regex.email",
            value=m.group(),
        ))
    return found