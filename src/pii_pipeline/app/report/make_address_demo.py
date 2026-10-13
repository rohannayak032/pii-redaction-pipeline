"""Write data/sample_addresses.docx: a synthetic document with Indian addresses for the demo.

Every person, house, building and e-mail is invented (e-mails use the reserved example.com domain);
localities, cities, states and PIN codes are real places so the addresses look realistic. No phone
numbers: any 10-digit Indian mobile number could belong to someone.

    python src/pii_pipeline/app/report/make_address_demo.py           # write the file
    python src/pii_pipeline/app/report/make_address_demo.py --check   # also run extraction + detection on it
"""
import sys
from pathlib import Path

import docx

OUT = Path(__file__).resolve().parents[4] / "data" / "sample_addresses.docx"

SENTENCES = [
    ("Ananya Raghavan, our new branch manager, will receive all deliveries at {} from Monday.",
     "Flat 7B, Saffron Heights, 12th Cross, Indiranagar, Bengaluru, Karnataka 560038"),
    ("Please send the signed agreement to Vikram Desai at {} before the end of the month.",
     "House No. 221, Gulmohar Lane, Sector 15, Vashi, Navi Mumbai, Maharashtra 400703"),
    ("The Hyderabad warehouse moved to {} and the old site is closed.",
     "Plot 46, Lotus Enclave, Road No. 3, Banjara Hills, Hyderabad, Telangana 500034"),
    ("Meera Iyer asked that her payslips be posted to {} instead of the office.",
     "D-118, Neelkanth Apartments, Mayur Vihar Phase 1, East Delhi, Delhi 110091"),
]
TABLE = [
    ("Karthik Subramanian", "Field Engineer", "No. 9, Kamaraj Street, T. Nagar, Chennai, Tamil Nadu 600017",
     "karthik.subramanian@example.com"),
    ("Priya Kulkarni", "Accounts Executive", "B-302, Riverstone Residency, Baner Road, Pune, Maharashtra 411045",
     "priya.kulkarni@example.com"),
    ("Arjun Banerjee", "Logistics Lead", "14/2, Lake View Colony, Salt Lake Sector 2, Kolkata, West Bengal 700091",
     "arjun.banerjee@example.com"),
    ("Sneha Rathore", "HR Partner", "Villa 33, Palm Grove, Vaishali Nagar, Jaipur, Rajasthan 302021",
     "sneha.rathore@example.com"),
]
ADDRESSES = [a for _, a in SENTENCES] + [row[2] for row in TABLE]


def write(path: Path = OUT) -> Path:
    d = docx.Document()
    d.add_heading("Northwind Logistics India - Branch Onboarding Register", 1)
    d.add_paragraph("SYNTHETIC DEMO DATA. Every name, address and e-mail in this document is invented "
                    "to test PII redaction.")
    d.add_heading("Correspondence notes", 2)
    for sentence, address in SENTENCES:
        d.add_paragraph(sentence.format(address))
    d.add_paragraph("The Pune and Chennai teams meet every quarter; no visit is planned for Kolkata this year.")
    d.add_heading("Employee address register", 2)
    table = d.add_table(rows=1, cols=4)
    table.style = "Table Grid"
    for cell, text in zip(table.rows[0].cells, ("Employee", "Role", "Correspondence address", "E-mail")):
        cell.text = text
    for row in TABLE:
        for cell, text in zip(table.add_row().cells, row):
            cell.text = text
    path.parent.mkdir(parents=True, exist_ok=True)
    d.save(path)
    return path


def check(path: Path) -> None:
    """Every address must sit inside one ADDRESS detection (the redaction then removes all of it)."""
    from pii_pipeline.detection.detector import detect
    from pii_pipeline.extraction import extract_document

    blocks = extract_document(path)
    entities = detect(blocks)
    missed = 0
    for address in ADDRESSES:
        block = next(b for b in blocks if address in b.text)
        start = block.text.index(address)
        covered = any(e.pii_type == "ADDRESS" and e.block_index == block.index
                      and e.start <= start and start + len(address) <= e.end for e in entities)
        missed += not covered
        print(f"{'ok  ' if covered else 'MISS'} {address}")
    by_detector = {d: sum(e.detector == d for e in entities) for d in sorted({e.detector for e in entities})}
    print(f"{len(ADDRESSES) - missed}/{len(ADDRESSES)} addresses fully covered; detections by detector: {by_detector}")
    assert missed == 0


if __name__ == "__main__":
    out = write()
    print(f"wrote {out}")
    if "--check" in sys.argv:
        check(out)
