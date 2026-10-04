import re
from typing import List


def chunk_paragraphs(text: str, max_chars: int = 3000) -> List[str]:
    """
    Memecah naskah panjang jadi potongan berbasis paragraf, tiap potongan paling banyak max_chars.
    Paragraf tidak dipotong di tengah kecuali satu paragraf sendiri sudah lebih panjang dari batas,
    dan saat itu dipotong di akhir kalimat terdekat supaya kutipan tetap utuh.
    """
    clean = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not clean:
        return []

    paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", clean)]
    pieces: List[str] = []
    for para in filter(None, paragraphs):
        while len(para) > max_chars:
            cut = para.rfind(". ", 0, max_chars)
            cut = cut + 1 if cut > max_chars // 2 else max_chars
            pieces.append(para[:cut].strip())
            para = para[cut:].strip()
        if para:
            pieces.append(para)

    chunks: List[str] = []
    for piece in pieces:
        if chunks and len(chunks[-1]) + 2 + len(piece) <= max_chars:
            chunks[-1] += "\n\n" + piece
        else:
            chunks.append(piece)
    return chunks
