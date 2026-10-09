"""Build a synthetic DOCX that exercises every place text can hide."""

from __future__ import annotations

import io
from pathlib import Path

import docx
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.opc.packuri import PackURI
from docx.opc.part import Part
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn

from . import fake as f

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NSDECL = (
    f'xmlns:w="{W}" '
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
    'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:v="urn:schemas-microsoft-com:vml" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
)


def _textbox_run(text: str):
    """A floating text box as Word writes it: DrawingML choice + VML fallback."""
    return parse_xml(f"""
<w:r {NSDECL}><mc:AlternateContent>
  <mc:Choice Requires="wps"><w:drawing><wp:anchor><wp:docPr id="50" name="Text Box 1"/>
    <a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">
      <wps:wsp><wps:txbx><w:txbxContent><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:txbxContent></wps:txbx></wps:wsp>
    </a:graphicData></a:graphic></wp:anchor></w:drawing></mc:Choice>
  <mc:Fallback><w:pict><v:shape><v:textbox><w:txbxContent><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:txbxContent></v:textbox></v:shape></w:pict></mc:Fallback>
</mc:AlternateContent></w:r>""")


def _xml_part(document, partname: str, content_type: str, xml: str, reltype: str) -> str:
    part = Part(PackURI(partname), content_type, xml.encode("utf-8"), document.part.package)
    return document.part.relate_to(part, reltype)


def _hyperlink(paragraph, url: str, text: str) -> None:
    rid = paragraph.part.relate_to(url, RT.HYPERLINK, is_external=True)
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), rid)
    run = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = text
    run.append(t)
    link.append(run)
    paragraph._p.append(link)


def build_docx(path: Path) -> Path:
    document = docx.Document()
    cp = document.core_properties
    cp.author, cp.last_modified_by, cp.title = f.PERSON_AUTHOR, f.PERSON_LAST_MODIFIED, "Synthetic review"

    # --- body: heading, paragraph with insert-tracked run, list item, link
    document.add_heading(f"Review of {f.PERSON_HEADING}", level=1)
    para = document.add_paragraph(f"Prepared for {f.PERSON_BODY} ({f.EMAIL_BODY}), SSN {f.SSN}.")
    ins = parse_xml(f'<w:ins {NSDECL} w:id="1" w:author="x"><w:r><w:t xml:space="preserve"> Phone {f.PHONE}.</w:t></w:r></w:ins>')
    para._p.append(ins)
    deleted = parse_xml(f'<w:del {NSDECL} w:id="2" w:author="x"><w:r><w:delText>removed words</w:delText></w:r></w:del>')
    para._p.append(deleted)
    document.add_paragraph(f"Escalate to {f.PERSON_LIST}", style="List Bullet")
    link_para = document.add_paragraph("Questions? ")
    _hyperlink(link_para, f"mailto:{f.EMAIL_HIDDEN_LINK}", "email the team")

    # --- footnote + endnote references (parts added below)
    ref = document.add_paragraph("See note")
    ref._p.append(parse_xml(f'<w:r {NSDECL}><w:footnoteReference w:id="1"/></w:r>'))

    # --- table: header row flag, vertical + horizontal merges, nested table
    table = document.add_table(rows=4, cols=3)
    for c, label in enumerate(["Employee ID", "Name", "Department"]):
        table.cell(0, c).text = label
    table.rows[0]._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))
    table.cell(1, 0).text, table.cell(1, 1).text, table.cell(1, 2).text = f.EMP_1, f.PERSON_BODY, "Finance"
    table.cell(2, 0).text, table.cell(2, 1).text = f.EMP_2, f.PERSON_TABLE_2
    table.cell(1, 2).merge(table.cell(2, 2))                  # vertical merge
    merged = table.cell(3, 0).merge(table.cell(3, 1))           # horizontal merge
    merged.text = f"Reviewed by {f.PERSON_MERGED}"
    table.cell(3, 2).text = "Audit"
    nested = table.cell(2, 1).add_table(rows=2, cols=2)
    nested.cell(0, 0).text, nested.cell(0, 1).text = "Backup", "Phone"
    nested.cell(1, 0).text, nested.cell(1, 1).text = f.PERSON_NESTED, f.PHONE

    # --- text box (choice + fallback copy) and an image with text + alt text
    box_para = document.add_paragraph("Anchor paragraph")
    box_para._p.append(_textbox_run(f"Text box contact: {f.PERSON_TEXTBOX}"))
    image = f.text_image([f"Badge holder: {f.PERSON_IMAGE}", f"ID {f.EMP_2}"])
    document.add_picture(io.BytesIO(f.png_bytes(image)))
    document.inline_shapes[-1]._inline.docPr.set("descr", f"Photo of {f.PERSON_ALT}")
    tiny = f.text_image(["x"], size=(20, 20))
    document.add_picture(io.BytesIO(f.png_bytes(tiny)))     # must be skipped (too small)

    # --- comment
    run = document.add_paragraph("Commented sentence.").runs[0]
    document.add_comment(run, text=f"Ask {f.PERSON_COMMENT_BODY}", author=f.PERSON_COMMENT_AUTHOR, initials="MW")

    # --- sections: own header in s1, own + first-page header in s2, s3 linked
    s1 = document.sections[0]
    s1.header.paragraphs[0].text = f"Owner {f.PERSON_HEADER_S1}"
    s1.footer.paragraphs[0].text = f"Printed by {f.PERSON_FOOTER}"
    s2 = document.add_section()
    document.add_paragraph("Section two body")
    s2.header.is_linked_to_previous = False
    s2.header.paragraphs[0].text = f"Owner {f.PERSON_HEADER_S2}"
    s2.different_first_page_header_footer = True
    s2.first_page_header.paragraphs[0].text = f"Cover {f.PERSON_FIRST_PAGE}"
    document.add_section()                                    # linked to previous: no duplicates
    document.add_paragraph("Section three body")

    # --- footnotes / endnotes parts
    _xml_part(document, "/word/footnotes.xml",
              "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml",
              f'<w:footnotes {NSDECL}>'
              '<w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:footnote>'
              f'<w:footnote w:id="1"><w:p><w:r><w:t>Source: {f.PERSON_FOOTNOTE}</w:t></w:r></w:p></w:footnote>'
              '</w:footnotes>', RT.FOOTNOTES)
    _xml_part(document, "/word/endnotes.xml",
              "application/vnd.openxmlformats-officedocument.wordprocessingml.endnotes+xml",
              f'<w:endnotes {NSDECL}>'
              f'<w:endnote w:id="1"><w:p><w:r><w:t>Contact {f.PERSON_ENDNOTE}</w:t></w:r></w:p></w:endnote>'
              '</w:endnotes>', RT.ENDNOTES)

    # --- orphan header part (referenced by no section): only the sweep finds it
    _xml_part(document, "/word/header99.xml",
              "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml",
              f'<w:hdr {NSDECL}><w:p><w:r><w:t>Orphan {f.PERSON_ORPHAN}</w:t></w:r></w:p></w:hdr>', RT.HEADER)

    # --- extended properties: company
    for part in document.part.package.iter_parts():
        if str(part.partname) == "/docProps/app.xml":
            part._blob = part.blob.replace(b"</Properties>", f"<Company>{f.COMPANY}</Company></Properties>".encode())

    document.save(str(path))
    return path
