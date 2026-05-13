"""Prompt templates and input sanitization for the paper generator."""
import re

_INJECTION_PATTERNS = [
    re.compile(r"(?i)ignore\s+(all\s+)?(previous|prior|above)\s+instructions"),
    re.compile(r"(?i)disregard\s+(all\s+)?(previous|prior|above)\s+instructions"),
    re.compile(r"(?i)system\s*[:>]"),
    re.compile(r"(?i)assistant\s*[:>]"),
    re.compile(r"</?\s*(system|prompt|instruction)\s*>", re.IGNORECASE),
    re.compile(r"###\s*(system|instruction|prompt)", re.IGNORECASE),
]


def sanitize_user_text(text: str, max_len: int = 200) -> str:
    """Strip prompt-injection markers, control chars, and cap length."""
    if not text:
        return ""
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(text))
    for pat in _INJECTION_PATTERNS:
        cleaned = pat.sub("[redacted]", cleaned)
    cleaned = cleaned.strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rsplit(" ", 1)[0] + "…"
    return cleaned


def build_language_instruction(paper_language: str, subject: str) -> str:
    """Return the language directive to inject into the prompt."""
    subj_lower = (subject or "").lower()
    if paper_language == "hindi" and subj_lower != "english":
        return (
            "You MUST generate the entire question paper, including questions, "
            "options, answers, and explanations, strictly in Hindi using Unicode "
            "Devanagari characters."
        )
    return (
        "You MUST generate the entire question paper, including questions, "
        "options, answers, and explanations, strictly in English."
    )


_OUTPUT_FORMAT_BLOCK = """OUTPUT FORMAT REQUIREMENTS:
- Return ONLY a valid JSON array of question objects.
- Do NOT include any other text, explanations, or markdown formatting.
- Each question object MUST have these exact keys:
  - "type" (one of: "MCQ", "Short Answer", "Long Answer", "Fill in the Blanks", "Matching", "Case Study")
  - "question" (the question text as a string)
  - "options" (ONLY for "MCQ" type: exactly 4 options as a JSON array of strings)
  - "marks" (integer)
  - "difficulty" ("Easy", "Medium", or "Hard")
  - "answer" (correct answer; for MCQ provide the letter like "A" or "B")
  - "explanation" (brief explanation as a string)

Example MCQ:
{
  "type": "MCQ",
  "question": "What is the capital of France?",
  "options": ["London", "Berlin", "Paris", "Madrid"],
  "marks": 1,
  "difficulty": "Easy",
  "answer": "C",
  "explanation": "Paris is the capital of France."
}"""


def build_topic_prompt(
    *,
    board: str,
    school: str,
    class_: str,
    subject: str,
    topic: str,
    qdist_str: str,
    ddist: dict,
    language_instruction: str,
    paper_language: str,
) -> str:
    """Prompt for topic-based generation."""
    board_s = sanitize_user_text(board, 60)
    school_s = sanitize_user_text(school, 100)
    class_s = sanitize_user_text(str(class_), 10)
    subject_s = sanitize_user_text(subject, 60)
    topic_s = sanitize_user_text(topic, 200)

    return f"""You are an experienced {board_s} school teacher creating a question paper.
Your task is to create a comprehensive question paper focused EXCLUSIVELY on the topic: "{topic_s}".

School: {school_s}
Class: {class_s}
Subject: {subject_s}

{language_instruction}

CRITICAL INSTRUCTIONS:
1. Generate EXACTLY the number and types of questions specified below.
2. ALL questions MUST be directly related to the topic "{topic_s}".
3. Do NOT include any questions unrelated to this topic.
4. Follow the difficulty distribution as closely as possible.
5. ALL content MUST be in {paper_language.capitalize()} language.

Question Distribution Requirements:
{qdist_str}

Difficulty Distribution Target:
{ddist}

{_OUTPUT_FORMAT_BLOCK}

Begin generating the question paper now:
"""


def build_class_prompt(
    *,
    board: str,
    school: str,
    class_: str,
    subject: str,
    chapters: list,
    qdist_str: str,
    ddist: dict,
    language_instruction: str,
    paper_language: str,
) -> str:
    """Prompt for class/chapter-based generation."""
    board_s = sanitize_user_text(board, 60)
    school_s = sanitize_user_text(school, 100)
    class_s = sanitize_user_text(str(class_), 10)
    subject_s = sanitize_user_text(subject, 60)
    chapters_s = [sanitize_user_text(c, 100) for c in (chapters or [])]
    chapters_str = (
        f"Focus on these chapters: {', '.join(chapters_s)}." if chapters_s else ""
    )

    return f"""You are an experienced {board_s} school teacher creating a question paper.
Your task is to create a comprehensive question paper for Class {class_s}, Subject: {subject_s}.

School: {school_s}
{chapters_str}

{language_instruction}

CRITICAL INSTRUCTIONS:
1. Generate EXACTLY the number and types of questions specified below.
2. ALL questions MUST be appropriate for Class {class_s} {subject_s}.
3. Follow the difficulty distribution as closely as possible.
4. ALL content MUST be in {paper_language.capitalize()} language.

Question Distribution Requirements:
{qdist_str}

Difficulty Distribution Target:
{ddist}

{_OUTPUT_FORMAT_BLOCK}

Begin generating the question paper now:
"""
