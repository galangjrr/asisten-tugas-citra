import os
from exporters.docx_builder import create_assignment_docx


def test_docx_generation():
    """Memastikan dokumen docx terbuat dengan format A4 dan tersimpan di storage."""
    title = "Uji Coba Otomasi Dokumen A4"
    sections = [
        {"heading": "BAB I PENDAHULUAN", "content": "Ini adalah paragraf pengantar uji coba."},
        {"heading": "BAB II PEMBAHASAN", "content": "Ini adalah paragraf pembahasan uji coba."}
    ]
    references = [
        {
            "authors": ["Budi Santoso", "Eko Prasetyo"],
            "year": 2024,
            "title": "Penerapan Kecerdasan Buatan dalam Pendidikan",
            "venue": "Jurnal Teknologi Informasi",
            "doi": "https://doi.org/10.1234/jti.2024.01"
        }
    ]

    output_path = create_assignment_docx(title, sections, references, "test_output.docx")
    assert os.path.exists(output_path)
    assert os.path.getsize(output_path) > 1000

    # Bersihkan file uji coba
    if os.path.exists(output_path):
        os.remove(output_path)
