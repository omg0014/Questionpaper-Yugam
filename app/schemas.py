"""Pydantic schemas for request/response validation."""
from typing import Optional
from pydantic import BaseModel, Field, field_validator, ConfigDict


_ALLOWED_LANGS = {"english", "hindi"}
_ALLOWED_DIFFICULTIES = {"Easy", "Medium", "Hard"}
_ALLOWED_QTYPES = {
    "MCQ",
    "Multiple Choice",
    "Short Answer",
    "Short",
    "Long Answer",
    "Long",
    "Fill in the Blanks",
    "Fill",
    "Matching",
    "Match",
    "Match the Following",
    "Case Study",
    "Case",
}


class QuestionTypeDist(BaseModel):
    model_config = ConfigDict(extra="ignore")
    count: int = Field(ge=0, le=50)
    marks: int = Field(ge=0, le=20)


class GenerateRequest(BaseModel):
    """Validated payload for /api/generate."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    subject: str = Field(min_length=1, max_length=60)
    class_: str = Field(alias="class", min_length=1, max_length=10)
    schoolBoard: str = Field(min_length=1, max_length=60)
    schoolName: Optional[str] = Field(default="", max_length=100)
    examName: Optional[str] = Field(default="", max_length=100)
    paperLanguage: str = Field(default="english")
    topic: Optional[str] = Field(default="", max_length=200)
    chapters: list[str] = Field(default_factory=list, max_length=30)
    questionDistribution: dict[str, QuestionTypeDist] = Field(default_factory=dict)
    difficultyDistribution: dict[str, int] = Field(default_factory=dict)

    @field_validator("paperLanguage")
    @classmethod
    def _check_lang(cls, v: str) -> str:
        v = (v or "english").lower()
        if v not in _ALLOWED_LANGS:
            return "english"
        return v

    @field_validator("class_")
    @classmethod
    def _check_class(cls, v: str) -> str:
        v = str(v).strip()
        try:
            num = int(v)
            if not 1 <= num <= 12:
                raise ValueError("class must be 1-12")
            return str(num)
        except (TypeError, ValueError):
            return v

    @field_validator("chapters")
    @classmethod
    def _trim_chapters(cls, v: list[str]) -> list[str]:
        return [str(c)[:100] for c in v if c]

    @field_validator("questionDistribution")
    @classmethod
    def _check_qdist(cls, v: dict) -> dict:
        return {k: val for k, val in v.items() if k in _ALLOWED_QTYPES}


class AIQuestion(BaseModel):
    """Validated single question from AI output."""

    model_config = ConfigDict(extra="ignore")

    type: str = Field(min_length=1, max_length=40)
    question: str = Field(min_length=1, max_length=4000)
    options: Optional[list[str]] = None
    marks: int = Field(default=1, ge=0, le=20)
    difficulty: str = Field(default="Medium")
    answer: str = Field(default="Not provided", max_length=2000)
    explanation: str = Field(default="", max_length=4000)

    @field_validator("difficulty")
    @classmethod
    def _check_diff(cls, v: str) -> str:
        v = (v or "Medium").strip().title()
        return v if v in _ALLOWED_DIFFICULTIES else "Medium"

    @field_validator("options")
    @classmethod
    def _trim_options(cls, v):
        if not v:
            return None
        import re
        # Strip leading "A.", "A)", "a.", "1.", "(a)", "(A)" prefixes the LLM often adds —
        # otherwise we get "a. A. लाइसोसोम" in the PDF (template auto-numbers via <ol>).
        prefix = re.compile(r"^\s*\(?[a-dA-D1-4]\)?\s*[.):\-]\s+")
        cleaned = [prefix.sub("", str(o)).strip()[:500] for o in v]
        cleaned = [o for o in cleaned if o]
        return cleaned[:6] or None
