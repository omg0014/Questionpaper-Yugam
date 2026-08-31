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
    # Internal choice: print `count` questions but require only `attemptAny` of
    # them ("attempt any 4 of 6"). None/0 means every question is compulsory.
    attemptAny: Optional[int] = Field(default=None, ge=1, le=50)

    @field_validator("attemptAny")
    @classmethod
    def _check_attempt(cls, v, info):
        # A choice that equals or exceeds the printed count is not a choice.
        count = (info.data or {}).get("count")
        if not v or count is None or v >= count:
            return None
        return v


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

    # "Matching" questions carry their Column A / Column B items here rather than
    # in `options`, so a match question can be rendered as a real two-column table.
    pairs: Optional[list[list[str]]] = None
    # "Case Study" questions carry the stimulus passage and its sub-questions.
    passage: Optional[str] = Field(default=None, max_length=4000)
    sub_questions: Optional[list[str]] = None

    @field_validator("difficulty")
    @classmethod
    def _check_diff(cls, v: str) -> str:
        v = (v or "Medium").strip().title()
        return v if v in _ALLOWED_DIFFICULTIES else "Medium"

    @field_validator("answer", "explanation", mode="before")
    @classmethod
    def _flatten_text(cls, v):
        """Accept a list or dict where a string is expected.

        A Case Study with three sub-questions comes back with three answers, so
        models legitimately send `answer` as a list. Rejecting that dropped the
        whole question and replaced a good case study with placeholder text.
        """
        if v is None:
            return v
        if isinstance(v, dict):
            v = [f"{k}: {val}" for k, val in v.items()]
        if isinstance(v, (list, tuple)):
            parts = []
            for n, item in enumerate(v, 1):
                if isinstance(item, dict):
                    item = "; ".join(f"{k}: {val}" for k, val in item.items())
                text = str(item).strip()
                if text:
                    parts.append(text if len(v) == 1 else f"({n}) {text}")
            v = "\n".join(parts)
        return str(v)[:3900]

    @field_validator("pairs", mode="before")
    @classmethod
    def _coerce_pairs(cls, v):
        """Accept [[l, r], ...] or [{"left": l, "right": r}, ...] and normalise to lists.

        LLMs alternate freely between these shapes (and between term/definition,
        item/match naming), so accept them all rather than dropping the question.
        """
        if not v:
            return None
        out = []
        for item in v:
            left = right = None
            if isinstance(item, dict):
                keys = {k.lower(): val for k, val in item.items()}
                for lk in ("left", "term", "item", "column_a", "a", "question"):
                    if lk in keys:
                        left = keys[lk]
                        break
                for rk in ("right", "definition", "match", "column_b", "b", "answer"):
                    if rk in keys:
                        right = keys[rk]
                        break
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                left, right = item[0], item[1]
            if left is None or right is None:
                continue
            out.append([str(left).strip()[:300], str(right).strip()[:300]])
        return out[:6] or None

    @field_validator("sub_questions", mode="before")
    @classmethod
    def _trim_sub_questions(cls, v):
        if not v:
            return None
        cleaned = [str(s).strip()[:500] for s in v if str(s).strip()]
        return cleaned[:6] or None

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
