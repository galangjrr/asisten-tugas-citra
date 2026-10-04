import os
from typing import List, Dict, Any, Optional
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER, TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from xml.sax.saxutils import escape
from tools.citation_formatter import build_academic_reference_data


from tools.paths import STORAGE_DIR


def create_assignment_pdf(
    title: str,
    sections: List[Dict[str, Any]],
    references: List[Dict[str, Any]],
    output_filename: str = "Tugas_Kuliah.pdf",
    language: Optional[str] = None,
    identity_lines: Optional[List[str]] = None
) -> str:
    """Merakit naskah tugas lengkap menjadi berkas PDF format A4 rapi."""
    os.makedirs(STORAGE_DIR, exist_ok=True)
    file_path = os.path.join(STORAGE_DIR, output_filename)

    # Batas tepi kertas A4 standar akademis
    doc = SimpleDocTemplate(
        file_path,
        pagesize=A4,
        leftMargin=4.0 * cm,
        rightMargin=3.0 * cm,
        topMargin=4.0 * cm,
        bottomMargin=3.0 * cm,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        name="AcademicTitle",
        fontName="Times-Bold",
        fontSize=14,
        leading=18,
        alignment=TA_CENTER,
        spaceAfter=20,
    )

    heading_style = ParagraphStyle(
        name="AcademicHeading",
        fontName="Times-Bold",
        fontSize=12,
        leading=16,
        alignment=TA_LEFT,
        spaceBefore=14,
        spaceAfter=6,
        keepWithNext=True,
    )

    body_style = ParagraphStyle(
        name="AcademicBody",
        fontName="Times-Roman",
        fontSize=12,
        leading=18,
        alignment=TA_JUSTIFY,
        firstLineIndent=20,
        spaceAfter=8,
    )

    ref_style = ParagraphStyle(
        name="AcademicRef",
        fontName="Times-Roman",
        fontSize=10,
        leading=14,
        alignment=TA_JUSTIFY,
        leftIndent=20,
        firstLineIndent=-20,
        spaceAfter=6,
    )

    story = []

    # Judul
    story.append(Paragraph(title.upper(), title_style))
    story.append(Spacer(1, 15))

    # Identitas mahasiswa di bawah judul. Di-escape karena ReportLab membaca teks sebagai markup.
    if identity_lines:
        identity_style = ParagraphStyle(name="Identity", fontName="Times-Roman", fontSize=12, leading=16)
        for line in identity_lines:
            story.append(Paragraph(escape(line), identity_style))
        story.append(Spacer(1, 15))

    # Bab dan Subbab
    for section in sections:
        heading = section.get("heading", "")
        content = section.get("content", "")

        if heading and heading.strip():
            story.append(Paragraph(heading, heading_style))

        paragraphs = content.split("\n\n")
        for para in paragraphs:
            # Baris tunggal dipertahankan agar dialog terjemahan tetap satu giliran per baris
            para_clean = para.strip().replace("\n", "<br/>")
            if para_clean:
                story.append(Paragraph(para_clean, body_style))

    # Daftar Pustaka / References
    if language:
        is_en_doc = language.lower().startswith("en")
    else:
        sample_text = (title + " " + " ".join(s.get("content", "")[:200] for s in sections[:2])).lower()
        is_en_doc = any(w in sample_text.split() for w in ["the", "and", "is", "of", "to", "in", "that", "this", "urban", "living"])
    ref_title_text = "REFERENCES" if is_en_doc else "DAFTAR PUSTAKA"

    if references:
        story.append(Spacer(1, 10))
        story.append(Paragraph(ref_title_text, heading_style))

    for ref in references:
        ref_data = build_academic_reference_data(ref, is_en=is_en_doc)

        author_esc = escape(ref_data["authors"])
        year_esc = escape(ref_data["year"])
        title_esc = escape(ref_data["title"])
        venue_esc = escape(ref_data["venue"])
        details_esc = escape(ref_data["pub_details"])
        doi_esc = escape(ref_data["doi"])

        venue_html = f" <i>{venue_esc}</i>" if venue_esc else ""
        if venue_esc and details_esc:
            details_html = f", {details_esc}."
        elif venue_esc:
            details_html = "."
        elif details_esc:
            details_html = f" {details_esc}."
        else:
            details_html = ""

        doi_html = f" {doi_esc}" if doi_esc else ""

        author_lead = author_esc.rstrip(".") + "."
        cit = f"{author_lead} ({year_esc}). {title_esc}.{venue_html}{details_html}{doi_html}"
        story.append(Paragraph(cit, ref_style))

    doc.build(story)
    return file_path
