from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    gemini_configured: bool
    version: str = "1.0.0"


class PaperItem(BaseModel):
    id: str
    title: str
    authors: List[str]
    year: Optional[int] = None
    venue: Optional[str] = None
    doi: Optional[str] = None
    pdf_url: Optional[str] = None
    abstract: Optional[str] = None
    scholar_url: Optional[str] = None


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=3, description="Topik atau kata kunci tugas kuliah")
    limit: int = Field(default=5, ge=1, le=10)


class SearchResponse(BaseModel):
    success: bool
    total: int
    query_used: str = ""
    message: str = ""
    papers: List[PaperItem]


class AnswerSpec(BaseModel):
    """Bentuk jawaban yang diminta dosen, hasil deteksi lembar soal yang bisa dikoreksi pengguna."""
    question_count: Optional[int] = Field(None, ge=1, le=50)
    answer_type: Optional[Literal["uraian", "terjemahan", "jawaban_singkat", "esai", "makalah", "jawaban_bernomor"]] = None
    needs_citations: Optional[bool] = None
    answer_language: Optional[Literal["id", "en"]] = None
    word_limit: Optional[int] = Field(None, ge=50, le=10000)


class GenerateRequest(BaseModel):
    topic: str = Field(..., min_length=3)
    format_type: str = Field(default="otomatis", description="otomatis, esai, makalah, mengalir, atau bernomor")
    target_length: str = Field(default="sedang", description="ringkas, sedang, panjang, atau kustom")
    target_words: int = Field(default=1000, ge=200, le=5000, description="Target jumlah kata total")
    paragraph_depth: str = Field(default="standar", description="ringkas atau elaboratif")
    tone: str = Field(default="akademis formal")
    # Kosong berarti tugas dikerjakan tanpa rujukan, misal soal terjemahan
    paper_ids: List[str] = Field(default_factory=list)
    custom_instructions: Optional[str] = None
    answer_spec: Optional[AnswerSpec] = None


class EvidenceItem(BaseModel):
    paper_id: str
    title: str
    authors: str
    year: Optional[int] = None
    venue: Optional[str] = None
    doi: Optional[str] = None
    has_full_pdf: bool = True
    citation_count: int = 0
    snippets: List[dict] = []


class GenerateResponse(BaseModel):
    success: bool
    task_id: str
    title: str
    word_count: int
    sections: List[dict]
    references: List[dict]
    evidence: Optional[List[EvidenceItem]] = None


class ManualModuleRequest(BaseModel):
    module_title: str = Field(..., min_length=3, description="Kode dan Judul Modul BMP UT atau Diktat")
    author: Optional[str] = "Universitas Terbuka"
    year: Optional[int] = 2023
    page_or_kb: Optional[str] = "Modul 1, KB 1"
    content_text: str = Field(..., min_length=15, description="Teks hasil salin dari Ruang Baca Virtual")


class UTCourseDetail(BaseModel):
    kode: str
    nama: str
    edisi: str
    formatted_title: str


class UTCourseLookupResponse(BaseModel):
    found: bool
    exact: bool = False
    course: Optional[UTCourseDetail] = None
    suggestions: List[UTCourseDetail] = []


class ExtractScreenshotRequest(BaseModel):
    image_base64: Optional[str] = Field(None, description="Base64 encoded image dari clipboard atau file")
    image_data: Optional[str] = Field(None, description="Alias image_base64")
    mime_type: Optional[str] = "image/png"

    @property
    def raw_data(self) -> str:
        return (self.image_base64 or self.image_data or "").strip()


class ExtractScreenshotResponse(BaseModel):
    success: bool
    extracted_text: str = ""
    message: str = ""


class ParseQuestionDocRequest(BaseModel):
    filename: str
    file_base64: str


class ParseQuestionDocResponse(BaseModel):
    success: bool
    filename: str = ""
    file_type: str = ""
    text: str = ""
    questions: Optional[str] = ""
    detected_guidelines: Optional[str] = ""
    char_count: int = 0
    detected_course_code: Optional[str] = None
    word_count_hint: Optional[int] = None
    answer_spec: Optional[AnswerSpec] = None
    answer_spec_source: Optional[str] = None
    message: str = ""





