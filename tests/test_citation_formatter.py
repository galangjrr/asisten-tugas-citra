import pytest
from tools.citation_formatter import (
    format_single_author_apa,
    format_authors_apa,
    format_doi_url,
    build_academic_reference_data
)


def test_format_single_author_apa():
    assert format_single_author_apa("Willa Cather") == "Cather, W."
    assert format_single_author_apa("Budi Santoso") == "Santoso, B."
    assert format_single_author_apa("John Maynard Keynes") == "Keynes, J. M."
    assert format_single_author_apa("Cather, Willa") == "Cather, W."
    assert format_single_author_apa("Universitas Terbuka") == "Universitas Terbuka"
    assert format_single_author_apa("Kementerian Kesehatan RI") == "Kementerian Kesehatan RI"
    assert format_single_author_apa("Soekarno") == "Soekarno"
    assert format_single_author_apa("") == "Anonim"


def test_format_authors_apa():
    assert format_authors_apa(["Willa Cather"]) == "Cather, W."
    assert format_authors_apa(["Budi Santoso", "Dewi Sartika"]) == "Santoso, B., & Sartika, D."
    assert format_authors_apa(["Ahmad Dahlan", "Budi Santoso", "Dewi Sartika"]) == "Dahlan, A., Santoso, B., & Sartika, D."
    assert format_authors_apa([]) == "Anonim"


def test_format_doi_url():
    assert format_doi_url("10.1234/test.01") == "https://doi.org/10.1234/test.01"
    assert format_doi_url("https://doi.org/10.1234/test.01") == "https://doi.org/10.1234/test.01"
    assert format_doi_url("") == ""


def test_build_academic_reference_data_journal():
    ref = {
        "authors": ["Budi Santoso", "Siti Aminah"],
        "year": 2022,
        "title": "Pengaruh Kecerdasan Buatan Terhadap Kinerja Belajar Mahasiswa",
        "venue": "Jurnal Teknologi Pendidikan Indonesia",
        "volume": "14",
        "issue": "2",
        "pages": "115-128",
        "doi": "10.5555/jtpi.2022.14.2"
    }

    data = build_academic_reference_data(ref, is_en=False)
    assert data["authors"] == "Santoso, B., & Aminah, S."
    assert data["year"] == "2022"
    assert data["pub_details"] == "14(2), 115-128"
    assert data["doi"] == "https://doi.org/10.5555/jtpi.2022.14.2"
    assert "Santoso, B., & Aminah, S. (2022)." in data["full_text"]
    assert "Jurnal Teknologi Pendidikan Indonesia, 14(2), 115-128." in data["full_text"]
    assert "https://doi.org/10.5555/jtpi.2022.14.2" in data["full_text"]


def test_build_academic_reference_data_lecturer_material():
    ref = {
        "authors": ["Willa Cather"],
        "year": 1896,
        "title": "A Burglar's Christmas",
        "venue": "Harper's Bazaar",
        "page_info": "Modul 3, hlm. 12-25"
    }

    data = build_academic_reference_data(ref, is_en=False)
    assert data["authors"] == "Cather, W."
    assert data["year"] == "1896"
    assert data["pub_details"] == "Modul 3, hlm. 12-25"
    assert "Cather, W. (1896). A Burglar's Christmas. Harper's Bazaar, Modul 3, hlm. 12-25." in data["full_text"]


def test_build_academic_reference_data_institutional():
    ref = {
        "authors": ["Universitas Terbuka"],
        "year": 2020,
        "title": "Manajemen (EKMA4116)",
        "venue": "Penerbit Universitas Terbuka"
    }

    data = build_academic_reference_data(ref, is_en=False)
    assert data["authors"] == "Universitas Terbuka"
    assert "Universitas Terbuka. (2020). Manajemen (EKMA4116). Penerbit Universitas Terbuka." in data["full_text"]
