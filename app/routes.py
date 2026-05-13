import os
import json
import re
import uuid
import io
from datetime import datetime
from flask import Blueprint, request, jsonify, render_template, current_app, send_file, render_template_string, make_response, Response, stream_with_context
from pydantic import ValidationError
from sqlalchemy.sql.expression import func
from sqlalchemy.orm import joinedload
from docx import Document
from weasyprint import HTML
import pathlib
from reportlab.lib.pagesizes import A4
from reportlab.platypus import Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from .models import Question, Paper, PaperQuestion, Visitor, Board, Class, Subject, Chapter
from .ai_providers import generate_with_fallback, stream_with_fallback, ProviderError, available_providers
from .schemas import GenerateRequest, AIQuestion
from .prompts import build_topic_prompt, build_class_prompt, build_language_instruction
from . import db, limiter


main = Blueprint("main", __name__)


def _debug_enabled() -> bool:
    return os.getenv("FLASK_DEBUG", "").lower() in ("1", "true", "yes")


@main.route("/db-test")
def db_test():
    if not _debug_enabled():
        return jsonify({"error": "not found"}), 404
    try:
        from sqlalchemy import text
        db.session.execute(text("SELECT 1"))
        return "Database connected successfully."
    except Exception as e:
        return f"DB error: {e}", 500


@main.route("/debug-questions")
def debug_questions():
    if not _debug_enabled():
        return jsonify({"error": "not found"}), 404
    return {"count": Question.query.count()}





# In app/routes.py (After imports, before get_or_create_visitor)

# Helper function to clean and render simple math symbols for WeasyPrint/ReportLab
def render_simple_math(text):
    if not text:
        return ""
    
    # 1. Remove surrounding $ signs (which the AI uses for LaTeX)
    text = re.sub(r'^\s*\$', '', text)
    text = re.sub(r'\$\s*$', '', text)
    
    # 2. Replace common LaTeX commands with Unicode/HTML symbols
    text = text.replace(r'\times', '×')      # Multiplication symbol
    text = text.replace(r'^\circ', '°')       # Degree symbol (used in 40^\circ)
    text = text.replace(r'\circ', '°')        # Degree symbol
    text = text.replace(r'\le', '≤')
    text = text.replace(r'\ge', '≥')
    text = text.replace(r'\ne', '≠')
    
    # 3. Handle simple superscripts (e.g., 3^2 -> 3<sup>2</sup>)
    # This is a simplification; WeasyPrint supports <sup> tags.
    text = re.sub(r'(\d+)\^(\d+)', r'\1<sup>\2</sup>', text)
    
    # 4. Handle simple fractions: replace \frac{1}{3} with (1/3) or <sup>1</sup>&frasl;<sub>3</sub>
    # Using simple HTML for better readability in PDF
    text = re.sub(r'\\frac\{([^}]+)\}\{([^}]+)\}', r'<sup>\1</sup>&frasl;<sub>\2</sub>', text)
    
    return text







def get_or_create_visitor():
    """Get existing visitor from cookie or create new visitor"""
    visitor_id = request.cookies.get('visitor_id')
    
    if visitor_id:
        # Check if visitor exists in database
        visitor = Visitor.query.filter_by(visitor_id=visitor_id).first()
        if visitor:
            # Update last visit and increment visit count
            visitor.visit_count += 1
            db.session.commit()
            return visitor
    
    # Create new visitor
    visitor_id = str(uuid.uuid4())
    visitor = Visitor()
    visitor.visitor_id = visitor_id
    db.session.add(visitor)
    db.session.commit()
    
    return visitor




# In app/routes.py, replace your get_academic_data function with this

@main.route("/api/academic-data")
def get_academic_data():
    """
    Queries the database and formats the data to perfectly match
    the original hardcoded JavaScript object structure.
    """
    try:
        # THIS IS THE CHANGED LINE: Use joinedload for an efficient, single query
        all_boards = Board.query.options(
            joinedload(Board.classes).joinedload(Class.subjects).joinedload(Subject.chapters)
        ).all()

        # Initialize the two main dictionaries that our frontend expects
        subjects_data = {}
        chapters_data = {}

        for board in all_boards:
            subjects_data[board.name] = {}
            chapters_data[board.name] = {}
            sorted_classes = sorted(board.classes, key=lambda c: c.class_number)

            for class_ in sorted_classes:
                class_num_str = str(class_.class_number)
                subjects_data[board.name][class_num_str] = []
                chapters_data[board.name][class_num_str] = {}

                for subject in class_.subjects:
                    subjects_data[board.name][class_num_str].append({
                        "en": subject.name_en,
                        "hi": subject.name_hi
                    })
                    chapters_list = []
                    for chapter in subject.chapters:
                        chapters_list.append({
                            "en": chapter.title_en,
                            "hi": chapter.title_hi
                        })
                    chapters_data[board.name][class_num_str][subject.name_en] = chapters_list

        return jsonify({
            "subjects": subjects_data,
            "chapters": chapters_data
        })

    except Exception as e:
        current_app.logger.error(f"Failed to fetch and format academic data: {e}")
        return jsonify({"error": "Could not fetch academic data."}), 500





@main.route("/")
def index():
    response = make_response(render_template("index.html"))
    
    # Check if visitor cookie exists
    visitor_id = request.cookies.get('visitor_id')
    if not visitor_id:
        # Create new visitor and set cookie
        visitor = get_or_create_visitor()
        response.set_cookie('visitor_id', visitor.visitor_id, max_age=365*24*60*60)  # 1 year
    
    return response

# Helper function to normalize question types
def _normalize_qtype(label):
    label = (label or "").strip()
    if label in ["MCQ", "Multiple Choice"]: return "MCQ"
    if label in ["Fill in the Blanks", "Fill"]: return "Fill in the Blanks"
    if label in ["Short Answer", "Short"]: return "Short Answer"
    if label in ["Long Answer", "Long"]: return "Long Answer"
    if label in ["Matching", "Match", "Match the Following"]: return "Matching"
    if label in ["Case Study", "Case"]: return "Case Study"
    return label

def _build_qdist_string(qdist: dict) -> str:
    """Verbose, count-aware breakdown so the LLM is less likely to under-deliver."""
    parts = []
    grand_total_q = 0
    grand_total_marks = 0
    for qtype, info in qdist.items():
        if not isinstance(info, dict):
            continue
        count = int(info.get("count", 0) or 0)
        marks = int(info.get("marks", 0) or 0)
        if count > 0:
            parts.append(f"- EXACTLY {count} {qtype} question(s), each worth {marks} marks "
                         f"(subtotal: {count * marks} marks)")
            grand_total_q += count
            grand_total_marks += count * marks
    if grand_total_q:
        parts.append(f"\nGRAND TOTAL: {grand_total_q} questions, {grand_total_marks} marks. "
                     f"You MUST return exactly {grand_total_q} questions — no fewer.")
    return "\n".join(parts)


def _parse_ai_json(raw_text: str) -> list:
    """Parse the LLM's response into a list of question dicts.

    Handles raw JSON, fenced ```json blocks, and best-effort recovery.
    """
    if not raw_text:
        raise ValueError("AI returned empty response.")
    raw_text = raw_text.strip()
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        m = re.search(r"```(?:json)?\s*(.*?)```", raw_text, re.DOTALL)
        if m:
            data = json.loads(m.group(1))
        else:
            m2 = re.search(r"\[\s*\{.*\}\s*\]", raw_text, re.DOTALL)
            if not m2:
                raise ValueError("AI returned invalid JSON.")
            data = json.loads(m2.group(0))
    if isinstance(data, dict):
        for key in ("questions", "data", "items"):
            if key in data and isinstance(data[key], list):
                data = data[key]
                break
    if not isinstance(data, list):
        raise ValueError("AI response was not a JSON array of questions.")
    return data


def _validate_questions(raw_list: list, paper_language: str) -> list[dict]:
    """Validate each AI question through Pydantic; drop bad ones."""
    out = []
    for raw in raw_list:
        if not isinstance(raw, dict):
            continue
        try:
            q = AIQuestion(**raw).model_dump()
        except ValidationError as ve:
            current_app.logger.warning("Dropping malformed AI question: %s", ve)
            continue
        q["question_type"] = _normalize_qtype(q.get("type"))
        q["question_text"] = q.get("question", "")
        q["source"] = "AI"
        q["language"] = paper_language
        if q["question_type"] != "MCQ":
            q["options"] = None
        out.append(q)
    return out


# --- Smart backfill: AI retry -> loosened DB lookup -> typed placeholders ---


def _compute_shortfall(questions: list, qdist: dict) -> dict:
    """Returns {normalized_type: {needed, have, missing, marks, qtype_frontend}} for any type still short."""
    sf = {}
    for qtype_frontend, info in qdist.items():
        normalized = _normalize_qtype(qtype_frontend)
        needed = int(info.get("count", 0))
        marks = int(info.get("marks", 1))
        have = sum(1 for q in questions if q.get("question_type") == normalized)
        if have < needed:
            sf[normalized] = {
                "needed": needed, "have": have,
                "missing": needed - have, "marks": marks,
                "qtype_frontend": qtype_frontend,
            }
    return sf


def _retry_ai_for_missing(shortfall: dict, ctx: dict) -> list:
    """Targeted AI retry asking only for the missing items."""
    if not shortfall:
        return []
    parts = [
        f"- exactly {sf['missing']} {sf['qtype_frontend']} question(s), each worth {sf['marks']} marks"
        for sf in shortfall.values()
    ]
    scope_bits = []
    if ctx.get("topic"):
        scope_bits.append(f'focused on topic "{ctx["topic"]}"')
    elif ctx.get("chapters"):
        scope_bits.append(f"covering chapters: {', '.join(ctx['chapters'])}")
    scope = " ".join(scope_bits) or "from the general syllabus"
    retry_prompt = (
        f"You previously generated questions for a Class {ctx['class_']} {ctx['subject']} "
        f"({ctx['board']}) paper. I still need MORE questions. Generate ONLY these MISSING questions, "
        f"{scope}.\n\nMissing:\n" + "\n".join(parts) +
        f"\n\nLanguage: {ctx['paper_language']}.\n"
        "Return ONLY a JSON array. Each object: type, question, options (MCQ only — exactly 4), "
        "marks (integer), difficulty (Easy/Medium/Hard), answer, explanation."
    )
    try:
        text, used = generate_with_fallback(retry_prompt)
        current_app.logger.info("AI retry-for-missing succeeded via %s", used)
        raw = _parse_ai_json(text)
        return _validate_questions(raw, ctx["paper_language"])
    except Exception as e:
        current_app.logger.warning("AI retry-for-missing failed: %s", e)
        return []


def _smart_placeholder(qtype_frontend: str, marks: int, subject: str, class_: str,
                       paper_language: str, scope_hint: str = "") -> dict:
    """Typed placeholder respecting marks. Scope hint = topic or 'general syllabus'."""
    qtype_norm = _normalize_qtype(qtype_frontend)
    scope = scope_hint or f"Class {class_} {subject}"
    base = {
        "type": qtype_frontend,
        "question_type": qtype_norm,
        "marks": marks,
        "difficulty": "Medium",
        "source": "Fallback",
        "language": paper_language,
        "options": None,
        "answer": "See your textbook for the model answer.",
        "explanation": "Refer to the relevant chapter in your textbook.",
    }
    if qtype_norm == "MCQ":
        qtext = f"Which of the following best describes a key concept from {scope}?"
        return {**base, "question": qtext, "question_text": qtext,
                "options": ["Option A", "Option B", "Option C", "Option D"], "answer": "A"}
    if qtype_norm == "Fill in the Blanks":
        qtext = f"In {scope}, the concept of ________ plays an important role."
        return {**base, "question": qtext, "question_text": qtext}
    if qtype_norm == "Long Answer":
        qtext = f"Explain in detail an important topic from {scope}, including examples and applications."
        return {**base, "question": qtext, "question_text": qtext}
    if qtype_norm == "Matching":
        qtext = f"Match the following terms from {scope} with their correct definitions."
        return {**base, "question": qtext, "question_text": qtext}
    if qtype_norm == "Case Study":
        qtext = f"Read the following case study from {scope} and answer the questions that follow."
        return {**base, "question": qtext, "question_text": qtext}
    qtext = f"Briefly describe an important concept from {scope}."
    return {**base, "question": qtext, "question_text": qtext}


def _backfill_distribution(*, questions: list, qdist: dict, board: str, class_: str,
                            subject: str, chapters: list, topic: str,
                            paper_language: str) -> list:
    """Top up `questions` to meet per-type counts. AI retry -> DB (loosened) -> placeholder."""
    shortfall = _compute_shortfall(questions, qdist)
    if not shortfall:
        return questions

    current_app.logger.info(
        "Distribution shortfall before backfill: %s",
        {k: v["missing"] for k, v in shortfall.items()},
    )

    # 1) Targeted AI retry for the missing items.
    ctx = {"board": board, "class_": class_, "subject": subject,
           "topic": topic, "chapters": chapters, "paper_language": paper_language}
    retry_questions = _retry_ai_for_missing(shortfall, ctx)
    existing_texts = {q.get("question_text", "").strip().lower() for q in questions}
    for q in retry_questions:
        nt = q.get("question_type")
        if nt not in shortfall or shortfall[nt]["missing"] <= 0:
            continue
        text = (q.get("question_text") or "").strip().lower()
        if not text or text in existing_texts:
            continue
        # Force expected marks so totals match what the user asked for.
        q["marks"] = shortfall[nt]["marks"]
        questions.append(q)
        existing_texts.add(text)
        shortfall[nt]["missing"] -= 1
    shortfall = {k: v for k, v in shortfall.items() if v["missing"] > 0}
    if not shortfall:
        return questions

    # 2) DB lookup with progressive filter loosening.
    topic_present = bool(topic and topic.strip())
    chapter_id_list = []
    if chapters:
        chapter_objects = Chapter.query.filter(Chapter.title_en.in_(chapters)).all()
        chapter_id_list = [c.chapter_id for c in chapter_objects]

    def _build_base_query(ntype, marks=None, language=None):
        f = {"question_type": ntype}
        if marks is not None:
            f["marks"] = marks
        if language is not None:
            f["language"] = language
        q = Question.query.filter_by(**f)
        if chapter_id_list:
            return q.filter(Question.chapter_id.in_(chapter_id_list))
        if topic_present:
            return q.filter(Question.question_text.contains(topic))
        q = q.join(Chapter).join(Subject)
        if subject:
            q = q.filter(Subject.name_en == subject)
        if class_:
            q = q.join(Class).filter(Class.class_number == class_)
        return q

    for ntype, sf in list(shortfall.items()):
        if sf["missing"] <= 0:
            continue
        seen_ids = set()
        filter_variants = [
            dict(marks=sf["marks"], language=paper_language),  # exact
            dict(language=paper_language),                     # any marks, same lang
            dict(marks=sf["marks"]),                           # exact marks, any lang
            dict(),                                            # any marks, any lang
        ]
        for variant in filter_variants:
            if sf["missing"] <= 0:
                break
            try:
                rows = (
                    _build_base_query(ntype, **variant)
                    .order_by(func.rand())
                    .limit(sf["missing"] * 3)
                    .all()
                )
            except Exception as e:
                current_app.logger.warning("DB backfill query failed (%s, %s): %s", ntype, variant, e)
                rows = []
            for r in rows:
                if sf["missing"] <= 0:
                    break
                if r.id in seen_ids:
                    continue
                seen_ids.add(r.id)
                text = (r.question_text or "").strip().lower()
                if not text or text in existing_texts:
                    continue
                q_dict = r.as_dict()
                q_dict["source"] = "Database"
                q_dict["language"] = r.language or paper_language
                q_dict["question_type"] = ntype
                q_dict["marks"] = sf["marks"]  # honor user's requested marks
                q_dict["question_text"] = r.question_text
                questions.append(q_dict)
                existing_texts.add(text)
                sf["missing"] -= 1
        current_app.logger.info("After DB backfill type=%s missing=%d", ntype, sf["missing"])

    shortfall = {k: v for k, v in shortfall.items() if v["missing"] > 0}
    if not shortfall:
        return questions

    # 3) Typed placeholders for whatever is still missing.
    scope_hint = ""
    if topic_present:
        scope_hint = topic
    elif chapters:
        scope_hint = f"the chapter '{chapters[0]}' of Class {class_} {subject}"
    for ntype, sf in shortfall.items():
        for _ in range(sf["missing"]):
            questions.append(
                _smart_placeholder(sf["qtype_frontend"], sf["marks"], subject,
                                   class_, paper_language, scope_hint)
            )
        current_app.logger.info("Smart placeholders added: type=%s count=%d", ntype, sf["missing"])

    return questions


@main.route("/api/generate", methods=["POST"])
@limiter.limit("10 per hour")
def generate_paper():
    raw_payload = request.get_json(silent=True) or {}
    try:
        req = GenerateRequest(**raw_payload)
    except ValidationError as ve:
        return jsonify({"error": "Invalid request", "details": ve.errors()}), 400

    subject = req.subject
    class_ = req.class_
    board = req.schoolBoard
    school = req.schoolName or ""
    qdist = {k: v.model_dump() for k, v in req.questionDistribution.items()}
    ddist = req.difficultyDistribution
    exam_name = req.examName or ""
    paper_language = req.paperLanguage
    topic = req.topic or ""
    chapters = req.chapters
    questions: list = []

    visitor = get_or_create_visitor()
    topic_present = bool(topic and topic.strip())
    current_app.logger.info(
        "generate_paper subject=%s class=%s board=%s topic_present=%s providers=%s",
        subject, class_, board, topic_present,
        [p.name for p in available_providers()],
    )

    qdist_prompt_str = _build_qdist_string(qdist)
    language_instruction = build_language_instruction(paper_language, subject)

    if topic_present:
        prompt = build_topic_prompt(
            board=board, school=school, class_=class_, subject=subject,
            topic=topic, qdist_str=qdist_prompt_str, ddist=ddist,
            language_instruction=language_instruction, paper_language=paper_language,
        )
    else:
        prompt = build_class_prompt(
            board=board, school=school, class_=class_, subject=subject,
            chapters=chapters, qdist_str=qdist_prompt_str, ddist=ddist,
            language_instruction=language_instruction, paper_language=paper_language,
        )

    try:
        raw_text, provider_used = generate_with_fallback(prompt)
        current_app.logger.info("AI generation succeeded via provider=%s", provider_used)
        ai_questions_raw = _parse_ai_json(raw_text)
        questions = _validate_questions(ai_questions_raw, paper_language)
        
        # Track used question IDs to prevent duplicates
        used_question_hashes = set()
        
        balanced_questions = []
        for qtype_frontend, info in qdist.items():
            count_needed = int(info['count'])
            normalized_type = _normalize_qtype(qtype_frontend)
            # Filter questions of this type
            type_questions = [q for q in questions if q.get("question_type") == normalized_type]
            
            # Add questions to balanced list, avoiding duplicates
            added_count = 0
            for q in type_questions:
                # Check if we've already added enough questions of this type
                if added_count >= count_needed:
                    break
                    
                # Create a simple hash of the question text to detect duplicates
                question_hash = hash(q.get("question", "").strip().lower())
                if question_hash not in used_question_hashes:
                    balanced_questions.append(q)
                    used_question_hashes.add(question_hash)
                    added_count += 1
        
        questions = balanced_questions
        
        # PASTE THIS NEW BLOCK IN ITS PLACE:

        # Find a suitable chapter_id to associate these new questions with.
        first_chapter_id = None
        if not topic_present and chapters:
             # Find the first chapter that matches the user's selection
             first_chapter_object = Chapter.query.join(Subject).join(Class).join(Board).filter(
                Board.name == board,
                Class.class_number == class_,
                Subject.name_en == subject,
                Chapter.title_en == chapters[0]
            ).first()
             if first_chapter_object:
                 first_chapter_id = first_chapter_object.chapter_id

        # This block now correctly saves questions with a chapter_id
        processed_questions = []
        for q in questions: # Note: 'questions' here is the list from the AI
            q_type = _normalize_qtype(q.get("type"))
            q_text = q.get("question", "")
            
            # Only save to DB if we found a chapter to link it to
            if first_chapter_id:
                new_q = Question(
                    chapter_id=first_chapter_id,
                    question_type=q_type,
                    difficulty=q.get("difficulty"),
                    marks=q.get("marks"),
                    question_text=q_text,
                    options=q.get("options") if q_type == "MCQ" else None,
                    answer=q.get("answer", "Not provided"),
                    source="AI",
                    explanation=q.get("explanation", ""),
                    language=paper_language
                )
                db.session.add(new_q)
                db.session.flush() # Use flush to get the ID before committing
                q['id'] = new_q.id # Add the new database ID to the question object

            q['source'] = "AI"
            q['question_type'] = q_type
            q['question_text'] = q_text
            processed_questions.append(q)

        questions = processed_questions
        db.session.commit()

    except Exception as e:
        current_app.logger.error(f"AI generation failed: {e}. Falling back completely to DB.")
        db.session.rollback()
        questions = []

    # --- Smart backfill: AI retry -> DB (loosened) -> typed placeholders ---
    questions = _backfill_distribution(
        questions=questions, qdist=qdist, board=board, class_=class_,
        subject=subject, chapters=chapters, topic=topic, paper_language=paper_language,
    )
    paper_id = str(uuid.uuid4())[:8]
    pdf_filename = f"paper_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    word_filename = f"{paper_id}.docx"
    answer_key_filename = f"answer_key_{paper_id}.pdf"

    paper_entry = Paper()
    paper_entry.paper_id = paper_id
    paper_entry.exam_name = exam_name
    paper_entry.school_name = school
    paper_entry.board = board
    paper_entry.class_ = class_
    paper_entry.subject = subject
    paper_entry.total_questions = len(questions)
    paper_entry.total_marks = sum(int(q.get("marks", 0)) for q in questions)
    paper_entry.pdf_path = f"/static/papers/{pdf_filename}"
    paper_entry.word_path = f"/static/papers/{word_filename}"
    paper_entry.answer_key_path = f"/static/papers/{answer_key_filename}"
    paper_entry.visitor_id = visitor.visitor_id  # Link paper to visitor
    
    db.session.add(paper_entry)
    db.session.commit()

    for q in questions:
        pq = PaperQuestion()
        pq.paper_id = paper_id
        pq.question_id = q.get('id')
        pq.question_text = q.get("question_text")
        pq.type = q.get("question_type")
        pq.difficulty = q.get("difficulty")
        pq.marks = q.get("marks")
        pq.options = q.get("options") if q.get("options") else None
        pq.answer = q.get("answer", "Not provided")
        db.session.add(pq)
    db.session.commit()

    papers_dir = os.path.join(current_app.root_path, "static", "papers")
    os.makedirs(papers_dir, exist_ok=True)
    json_path = os.path.join(papers_dir, f"{paper_id}.json")

    summary = {
        "total_questions": len(questions),
        "total_marks": sum(int(q.get("marks", 0)) for q in questions)
    }

    type_order = ["MCQ", "Multiple Choice", "Fill in the Blanks", "Fill", "Short Answer", "Short", "Long Answer", "Long", "Matching", "Match", "Match the Following", "Case Study", "Case"]
    def get_type_order(q):
        t = (q.get("type") or q.get("question_type") or "").strip()
        try: return type_order.index(t)
        except ValueError: return len(type_order)
    questions_sorted = sorted(questions, key=get_type_order)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "paper_id": paper_id, "examName": exam_name, "schoolName": school,
            "schoolBoard": board, "class": class_, "subject": subject,
            "questions": questions_sorted, "summary": summary
        }, f, indent=2, ensure_ascii=False)


    # --- PDF GENERATION WITH WEASYPRINT (FINAL VERSION) ---
    
    # Get the absolute path to the local font file
    font_path = os.path.join(current_app.root_path, 'fonts', 'NotoSansDevanagari-Regular.ttf')
    font_url = pathlib.Path(font_path).as_uri() # Converts path to file:/// URI

    sections = {
        "Multiple Choice": [], "Fill in the Blanks": [], "Short Answer": [],
        "Long Answer": [], "Matching": [], "Case Study": []
    }
    section_titles = {
        "Multiple Choice": "Section A - Multiple Choice Questions",
        "Fill in the Blanks": "Section B - Fill in the Blanks",
        "Short Answer": "Section C - Short Answer Questions",
        "Long Answer": "Section D - Long Answer Questions",
        "Matching": "Section E - Matching Questions",
        "Case Study": "Section F - Case Study"
    }
    for q in questions_sorted:
        q_type = _normalize_qtype(q.get("question_type", ""))
        if q_type == "MCQ": q_type = "Multiple Choice"
        if q_type in sections:
            sections[q_type].append(q)

    # Define the HTML template for the PDF
    # ...existing code...

    html_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            @page {
                size: A4;
                margin: 25mm 20mm 25mm 20mm;
            }
            @font-face {
                font-family: 'Noto Sans Devanagari';
                src: url('{{ font_url }}');
            }
            html, body {
                font-family: 'Noto Sans Devanagari', sans-serif;
                font-size: 12pt;
                background: #fff;
            }
            .paper-container {
                width: 100%;
                margin: 0;
                padding: 0;
            }
            .paper-header {
                text-align: center;
                margin-bottom: 18px;
                border-bottom: 2px solid #222;
                padding-bottom: 8px;
            }
            .paper-header h1 { font-size: 22pt; margin: 0; }
            .paper-header h2 { font-size: 16pt; margin: 4px 0; font-weight: normal; }
            .paper-header h3 { font-size: 13pt; margin: 4px 0; font-weight: normal; }
            .details {
                display: flex;
                justify-content: space-between;
                margin-bottom: 18px;
                font-size: 11pt;
            }
            section {
                margin-bottom: 22px;
            }
            h4.section-title {
                font-size: 13pt;
                border-bottom: 1px solid #bbb;
                padding: 4px 0;
                margin-bottom: 12px;
                margin-top: 0;
            }
            ol.question-list {
                list-style-type: none;
                padding-left: 0;
                margin-top: 0;
            }
            li.question {
                margin-bottom: 16px;
            }
            .question-text {
                display: flex;
                justify-content: space-between;
            }
            .question-text .marks {
                font-weight: bold;
                white-space: nowrap;
                padding-left: 12px;
            }
            ol.options {
                list-style-type: lower-alpha;
                padding-left: 32px;
                margin-top: 7px;
                margin-bottom: 0;
            }
            .option {
                margin-bottom: 4px;
            }
        </style>
    </head>
    <body>
        <div class="paper-container">
            <div class="paper-header">
                <h1>{{ school }}</h1>
                <h2>{{ exam_name }}</h2>
                <h3>Class {{ class_ }} - {{ subject }}</h3>
            </div>
            <div class="details">
                <span>Date: {{ date }}</span>
            </div>

            {% set q_num = namespace(value=1) %}
            {% for sec_type, q_list in sections.items() %}
                {% if q_list %}
                <section>
                    <h4 class="section-title">{{ section_titles[sec_type] }}</h4>
                    <ol class="question-list">
                        {% for q in q_list %}
                        <li class="question">
                            <div class="question-text">
                                <span><b>Q{{ q_num.value }}.</b> {{ q.question_text | math_render | safe }}</span>
                                <span class="marks">({{ q.marks }} marks)</span>
                            </div>
                            {% if q.question_type == 'MCQ' and q.options %}
                            <ol class="options">
                                {% for opt in q.options %}
                                <li class="option">{{ opt | math_render | safe }}</li>
                                {% endfor %}
                            </ol>
                            {% endif %}
                        </li>
                        {% set q_num.value = q_num.value + 1 %}
                        {% endfor %}
                    </ol>
                </section>
                {% endif %}
            {% endfor %}
        </div>
    </body>
    </html>
    """


    
    def to_char_filter(n):
        return chr(97 + n)  # Convert to lowercase letters (a, b, c, d)
    
    env = current_app.jinja_env
    env.filters['to_char'] = to_char_filter
    env.filters['math_render'] = render_simple_math
    
    rendered_html = render_template_string(
        html_template, 
        font_url=font_url, # Pass the local font path to the template
        school=school,
        exam_name=exam_name or f"{board} Board Examination",
        class_=class_,
        subject=subject,
        date=datetime.now().strftime('%d-%m-%Y'),
        sections=sections,
        section_titles=section_titles
    )
    
    pdf_path = os.path.join(papers_dir, pdf_filename)
    HTML(string=rendered_html).write_pdf(pdf_path)


    return jsonify({
        "questions": [{
            "id": q.get("id"), "question_text": q.get("question_text"),
            "marks": q.get("marks"), "difficulty": q.get("difficulty"),
            "type": q.get("type") or q.get("question_type"), "source": q.get("source", "Database")
        } for q in questions_sorted],
        "summary": summary,
        "pdf_url": f"/static/papers/{pdf_filename}",
        "word_url": f"/api/download/word/{paper_id}",
        "answer_key_url": f"/api/download/answer_key/{paper_id}",
    })


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@main.route("/api/generate/stream", methods=["POST"])
@limiter.limit("10 per hour")
def generate_paper_stream():
    """Server-Sent Events endpoint: stream questions as the LLM produces them.

    Emits events:
      - phase   { phase: "connecting" | "generating" | "rendering" | "done" }
      - chunk   { text: "...partial llm output..." }
      - question{ index, question, provider }      (each parsed question)
      - error   { message }
      - done    { paper_id, pdf_url, word_url, answer_key_url, summary }
    """
    raw_payload = request.get_json(silent=True) or {}
    try:
        req = GenerateRequest(**raw_payload)
    except ValidationError as ve:
        return jsonify({"error": "Invalid request", "details": ve.errors()}), 400

    if not available_providers():
        return jsonify({"error": "No AI provider configured."}), 503

    visitor = get_or_create_visitor()
    visitor_id = visitor.visitor_id

    subject = req.subject
    class_ = req.class_
    board = req.schoolBoard
    school = req.schoolName or ""
    qdist = {k: v.model_dump() for k, v in req.questionDistribution.items()}
    ddist = req.difficultyDistribution
    exam_name = req.examName or ""
    paper_language = req.paperLanguage
    topic = req.topic or ""
    chapters = req.chapters
    topic_present = bool(topic and topic.strip())

    qdist_prompt_str = _build_qdist_string(qdist)
    language_instruction = build_language_instruction(paper_language, subject)
    if topic_present:
        prompt = build_topic_prompt(
            board=board, school=school, class_=class_, subject=subject,
            topic=topic, qdist_str=qdist_prompt_str, ddist=ddist,
            language_instruction=language_instruction, paper_language=paper_language,
        )
    else:
        prompt = build_class_prompt(
            board=board, school=school, class_=class_, subject=subject,
            chapters=chapters, qdist_str=qdist_prompt_str, ddist=ddist,
            language_instruction=language_instruction, paper_language=paper_language,
        )

    app_obj = current_app._get_current_object()

    def generator():
        with app_obj.app_context():
            try:
                yield _sse("phase", {"phase": "connecting"})
                buffer = ""
                provider_seen = None
                yielded_count = 0
                yield _sse("phase", {"phase": "generating"})
                try:
                    for chunk, provider_name in stream_with_fallback(prompt):
                        provider_seen = provider_name
                        buffer += chunk
                        yield _sse("chunk", {"text": chunk, "provider": provider_name})
                        # Best-effort progressive parse of completed top-level JSON objects.
                        new_count, parsed_qs = _extract_complete_questions(buffer, yielded_count)
                        for q in parsed_qs:
                            yield _sse("question", {"index": yielded_count, "question": q, "provider": provider_name})
                            yielded_count += 1
                        yielded_count = new_count
                except ProviderError as pe:
                    yield _sse("error", {"message": f"All providers failed: {pe}"})
                    return

                yield _sse("phase", {"phase": "rendering"})
                try:
                    ai_questions_raw = _parse_ai_json(buffer)
                    questions = _validate_questions(ai_questions_raw, paper_language)
                except Exception as parse_err:
                    current_app.logger.warning("Streaming parse failed, will rely on backfill: %s", parse_err)
                    questions = []

                # Top up to meet the requested distribution.
                questions = _backfill_distribution(
                    questions=questions, qdist=qdist, board=board, class_=class_,
                    subject=subject, chapters=chapters, topic=topic, paper_language=paper_language,
                )

                if not questions:
                    yield _sse("error", {"message": "Could not generate any questions."})
                    return

                paper_id, urls, summary = _persist_and_render_paper(
                    questions=questions,
                    board=board, class_=class_, subject=subject,
                    school=school, exam_name=exam_name,
                    paper_language=paper_language, visitor_id=visitor_id,
                )
                questions_payload = [{
                    "question_text": q.get("question_text") or q.get("question"),
                    "question": q.get("question_text") or q.get("question"),
                    "marks": q.get("marks"),
                    "difficulty": q.get("difficulty"),
                    "type": q.get("type") or q.get("question_type"),
                    "question_type": q.get("question_type"),
                    "options": q.get("options"),
                    "answer": q.get("answer"),
                } for q in questions]
                yield _sse("done", {
                    "paper_id": paper_id,
                    "summary": summary,
                    "provider": provider_seen,
                    "questions": questions_payload,
                    **urls,
                })
            except Exception as e:
                current_app.logger.exception("stream generator failed")
                yield _sse("error", {"message": str(e)})

    return Response(
        stream_with_context(generator()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


_QUESTION_OBJ_RE = re.compile(r"\{[^{}]*?\"question\"\s*:\s*\"[^\"]*\"[^{}]*?\}", re.DOTALL)


def _extract_complete_questions(buffer: str, already_yielded: int):
    """Best-effort extractor for completed top-level JSON objects in a streaming buffer.

    Returns (new_yielded_count, list_of_newly_parsed_dicts).
    Very forgiving — failures just mean we wait for more data.
    """
    matches = _QUESTION_OBJ_RE.findall(buffer)
    out = []
    for raw in matches[already_yielded:]:
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict) and "question" in obj:
                out.append(obj)
        except Exception:
            continue
    return already_yielded + len(out), out


_SECTION_TITLES = {
    "english": {
        "Multiple Choice":    "Section A — Multiple Choice Questions",
        "Fill in the Blanks": "Section B — Fill in the Blanks",
        "Short Answer":       "Section C — Short Answer Questions",
        "Long Answer":        "Section D — Long Answer Questions",
        "Matching":           "Section E — Match the Following",
        "Case Study":         "Section F — Case Study",
    },
    "hindi": {
        "Multiple Choice":    "खंड A — बहुविकल्पीय प्रश्न",
        "Fill in the Blanks": "खंड B — रिक्त स्थान भरें",
        "Short Answer":       "खंड C — लघु उत्तरीय प्रश्न",
        "Long Answer":        "खंड D — दीर्घ उत्तरीय प्रश्न",
        "Matching":           "खंड E — मिलान करें",
        "Case Study":         "खंड F — केस अध्ययन",
    },
}

_PDF_LABELS = {
    "english": {
        "q_prefix":     "Q",
        "marks_one":    "mark",
        "marks_many":   "marks",
        "date":         "Date",
        "class":        "Class",
        "answer_key":   "Answer Key",
        "answer":       "Answer",
        "explanation":  "Explanation",
    },
    "hindi": {
        "q_prefix":     "प्र.",
        "marks_one":    "अंक",
        "marks_many":   "अंक",
        "date":         "दिनांक",
        "class":        "कक्षा",
        "answer_key":   "उत्तर कुंजी",
        "answer":       "उत्तर",
        "explanation":  "व्याख्या",
    },
}


def _section_titles_for(paper_language: str) -> dict:
    return _SECTION_TITLES.get((paper_language or "english").lower(), _SECTION_TITLES["english"])


def _pdf_labels_for(paper_language: str) -> dict:
    return _PDF_LABELS.get((paper_language or "english").lower(), _PDF_LABELS["english"])


def _persist_and_render_paper(
    *, questions, board, class_, subject, school, exam_name, paper_language, visitor_id,
):
    """Persist paper to DB and render PDF/JSON/DOCX-deferred. Returns (paper_id, urls, summary)."""
    paper_id = str(uuid.uuid4())[:8]
    pdf_filename = f"paper_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    word_filename = f"{paper_id}.docx"
    answer_key_filename = f"answer_key_{paper_id}.pdf"

    summary = {
        "total_questions": len(questions),
        "total_marks": sum(int(q.get("marks", 0)) for q in questions),
    }

    paper_entry = Paper()
    paper_entry.paper_id = paper_id
    paper_entry.exam_name = exam_name
    paper_entry.school_name = school
    paper_entry.board = board
    paper_entry.class_ = class_
    paper_entry.subject = subject
    paper_entry.total_questions = summary["total_questions"]
    paper_entry.total_marks = summary["total_marks"]
    paper_entry.pdf_path = f"/static/papers/{pdf_filename}"
    paper_entry.word_path = f"/static/papers/{word_filename}"
    paper_entry.answer_key_path = f"/static/papers/{answer_key_filename}"
    paper_entry.visitor_id = visitor_id
    db.session.add(paper_entry)
    db.session.commit()

    for q in questions:
        pq = PaperQuestion()
        pq.paper_id = paper_id
        pq.question_id = q.get("id")
        pq.question_text = q.get("question_text") or q.get("question")
        pq.type = q.get("question_type")
        pq.difficulty = q.get("difficulty")
        pq.marks = q.get("marks")
        pq.options = q.get("options") if q.get("options") else None
        pq.answer = q.get("answer", "Not provided")
        db.session.add(pq)
    db.session.commit()

    papers_dir = os.path.join(current_app.root_path, "static", "papers")
    os.makedirs(papers_dir, exist_ok=True)
    json_path = os.path.join(papers_dir, f"{paper_id}.json")

    type_order = ["MCQ", "Multiple Choice", "Fill in the Blanks", "Fill", "Short Answer", "Short",
                  "Long Answer", "Long", "Matching", "Match", "Match the Following", "Case Study", "Case"]
    def get_type_order(q):
        t = (q.get("type") or q.get("question_type") or "").strip()
        try:
            return type_order.index(t)
        except ValueError:
            return len(type_order)

    questions_sorted = sorted(questions, key=get_type_order)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "paper_id": paper_id, "examName": exam_name, "schoolName": school,
            "schoolBoard": board, "class": class_, "subject": subject,
            "questions": questions_sorted, "summary": summary,
        }, f, indent=2, ensure_ascii=False)

    # Render PDF
    fonts_dir = os.path.join(current_app.root_path, "fonts")
    font_url_regular = pathlib.Path(os.path.join(fonts_dir, "NotoSansDevanagari-Regular.ttf")).as_uri()
    bold_path = os.path.join(fonts_dir, "NotoSansDevanagari-Bold.ttf")
    font_url_bold = pathlib.Path(bold_path).as_uri() if os.path.exists(bold_path) else font_url_regular
    sections = {"Multiple Choice": [], "Fill in the Blanks": [], "Short Answer": [],
                "Long Answer": [], "Matching": [], "Case Study": []}
    section_titles = _section_titles_for(paper_language)
    labels = _pdf_labels_for(paper_language)
    for q in questions_sorted:
        qt = _normalize_qtype(q.get("question_type", ""))
        if qt == "MCQ":
            qt = "Multiple Choice"
        if qt in sections:
            sections[qt].append(q)

    env = current_app.jinja_env
    env.filters["math_render"] = render_simple_math
    rendered_html = render_template_string(
        _PAPER_HTML_TEMPLATE,
        font_url_regular=font_url_regular,
        font_url_bold=font_url_bold,
        school=school,
        exam_name=exam_name or f"{board} Board Examination",
        class_=class_, subject=subject,
        date=datetime.now().strftime("%d-%m-%Y"),
        sections=sections, section_titles=section_titles, labels=labels,
        lang_attr="hi" if paper_language == "hindi" else "en",
    )
    pdf_path = os.path.join(papers_dir, pdf_filename)
    HTML(string=rendered_html).write_pdf(pdf_path)

    urls = {
        "pdf_url": f"/static/papers/{pdf_filename}",
        "word_url": f"/api/download/word/{paper_id}",
        "answer_key_url": f"/api/download/answer_key/{paper_id}",
    }
    return paper_id, urls, summary


_PAPER_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="{{ lang_attr }}">
<head>
<meta charset="UTF-8">
<style>
@page { size: A4; margin: 22mm 18mm; }

/* Register BOTH weights so bold runs don't fall back to a non-Devanagari face. */
@font-face {
  font-family: 'NotoDev';
  src: url('{{ font_url_regular }}') format('truetype');
  font-weight: 400;
  font-style: normal;
}
@font-face {
  font-family: 'NotoDev';
  src: url('{{ font_url_bold }}') format('truetype');
  font-weight: 700;
  font-style: normal;
}

html, body {
  font-family: 'NotoDev', 'Noto Sans Devanagari', sans-serif;
  font-size: 12pt;
  line-height: 1.55;          /* Devanagari needs extra vertical room */
  background: #fff;
  color: #1a1a1a;
}

.paper-header { text-align: center; margin-bottom: 14px; border-bottom: 2px solid #222; padding-bottom: 8px; }
.paper-header h1 { font-size: 20pt; margin: 0; font-weight: 700; }
.paper-header h2 { font-size: 14pt; margin: 4px 0; font-weight: 400; }
.paper-header h3 { font-size: 12pt; margin: 4px 0; font-weight: 400; color: #444; }

.details { display: flex; justify-content: space-between; margin-bottom: 14px; font-size: 11pt; color: #333; }

section { margin-bottom: 18px; page-break-inside: auto; }
h4.section-title {
  font-size: 12pt;
  font-weight: 700;
  border-bottom: 1px solid #bbb;
  padding: 4px 0;
  margin: 14px 0 10px;
}

ol.question-list { list-style-type: none; padding-left: 0; margin-top: 0; }

li.question {
  margin-bottom: 12px;
  page-break-inside: avoid;
}

.question-text {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 14px;
}
.question-text .q-body { flex: 1; }
.question-text .q-body b { font-weight: 700; margin-right: 4px; }
.question-text .marks {
  font-weight: 700;
  white-space: nowrap;
  padding-left: 12px;
  font-size: 10.5pt;
  color: #555;
}

ol.options {
  list-style-type: lower-alpha;
  padding-left: 28px;
  margin: 6px 0 0;
}
ol.options li {
  margin-bottom: 2px;
  padding-left: 4px;
}
</style>
</head>
<body>
<div class="paper-container">
  <div class="paper-header">
    <h1>{{ school }}</h1>
    <h2>{{ exam_name }}</h2>
    <h3>{{ labels.class }} {{ class_ }} &middot; {{ subject }}</h3>
  </div>
  <div class="details">
    <span>{{ labels.date }}: {{ date }}</span>
  </div>
  {% set q_num = namespace(value=1) %}
  {% for sec_type, q_list in sections.items() %}
    {% if q_list %}
    <section>
      <h4 class="section-title">{{ section_titles[sec_type] }}</h4>
      <ol class="question-list">
        {% for q in q_list %}
        <li class="question">
          <div class="question-text">
            <span class="q-body"><b>{{ labels.q_prefix }}{{ q_num.value }}.</b> {{ q.question_text | math_render | safe }}</span>
            <span class="marks">({{ q.marks }} {{ labels.marks_one if q.marks == 1 else labels.marks_many }})</span>
          </div>
          {% if q.question_type == 'MCQ' and q.options %}
          <ol class="options">
            {% for opt in q.options %}
            <li>{{ opt | math_render | safe }}</li>
            {% endfor %}
          </ol>
          {% endif %}
        </li>
        {% set q_num.value = q_num.value + 1 %}
        {% endfor %}
      </ol>
    </section>
    {% endif %}
  {% endfor %}
</div>
</body>
</html>
"""


def _set_run_font(run, font_name: str = "Nirmala UI", size_pt: float = 11.0, bold: bool = False):
    """Apply a Devanagari-capable font to a python-docx run (both Latin and East-Asian/Indic ranges)."""
    from docx.shared import Pt
    from docx.oxml.ns import qn
    run.font.name = font_name
    run.font.size = Pt(size_pt)
    run.bold = bold
    rPr = run._r.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        from docx.oxml import OxmlElement
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    for attr in ("ascii", "hAnsi", "cs", "eastAsia"):
        rFonts.set(qn(f"w:{attr}"), font_name)


@main.route("/api/download/word/<paper_id>", methods=["GET"])
def download_word(paper_id):
    json_path = os.path.join(current_app.root_path, "static", "papers", f"{paper_id}.json")
    if not os.path.exists(json_path):
        return jsonify({"error": "Paper not found"}), 404
    with open(json_path, "r", encoding="utf-8") as f:
        paper = json.load(f)

    is_hindi = any((q.get("language") or "").lower() == "hindi" for q in paper.get("questions", []))
    paper_language = "hindi" if is_hindi else "english"
    font_name = "Nirmala UI" if is_hindi else "Calibri"
    labels = _pdf_labels_for(paper_language)

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = font_name
    from docx.oxml.ns import qn
    style.element.rPr.rFonts.set(qn("w:cs"), font_name)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), font_name)

    title = doc.add_paragraph()
    title_run = title.add_run(paper.get("examName") or ("प्रश्न पत्र" if is_hindi else "Question Paper"))
    _set_run_font(title_run, font_name, 18, bold=True)
    title.alignment = 1

    meta = doc.add_paragraph()
    _set_run_font(meta.add_run(f"{paper.get('schoolName', '')}"), font_name, 12, bold=True)
    meta.alignment = 1
    sub = doc.add_paragraph()
    sub_text = (f"{labels['class']} {paper.get('class', '')}  ·  {paper.get('subject', '')}  ·  "
                f"{'बोर्ड' if is_hindi else 'Board'}: {paper.get('schoolBoard', '')}")
    _set_run_font(sub.add_run(sub_text), font_name, 11)
    sub.alignment = 1

    doc.add_paragraph()

    # Group questions by section so they appear under translated section headings.
    section_order = ["MCQ", "Multiple Choice", "Fill in the Blanks",
                     "Short Answer", "Long Answer", "Matching", "Case Study"]
    section_key = {
        "MCQ": "Multiple Choice", "Multiple Choice": "Multiple Choice",
        "Fill in the Blanks": "Fill in the Blanks",
        "Short Answer": "Short Answer", "Long Answer": "Long Answer",
        "Matching": "Matching", "Case Study": "Case Study",
    }
    section_titles = _section_titles_for(paper_language)
    grouped = {k: [] for k in section_titles.keys()}
    for q in paper.get("questions", []):
        sk = section_key.get(_normalize_qtype(q.get("question_type", "")))
        if sk:
            grouped[sk].append(q)

    q_counter = 1
    for sec_key, q_list in grouped.items():
        if not q_list:
            continue
        h = doc.add_paragraph()
        _set_run_font(h.add_run(section_titles[sec_key]), font_name, 13, bold=True)

        for q in q_list:
            p = doc.add_paragraph()
            _set_run_font(p.add_run(f"{labels['q_prefix']}{q_counter}. "), font_name, 11, bold=True)
            _set_run_font(p.add_run(q.get("question_text") or q.get("question") or ""), font_name, 11)
            marks = int(q.get("marks", 0) or 0)
            marks_label = labels["marks_one"] if marks == 1 else labels["marks_many"]
            _set_run_font(p.add_run(f"   ({marks} {marks_label})"), font_name, 10, bold=True)

            if _normalize_qtype(q.get("question_type", "")) == "MCQ":
                for idx, opt in enumerate(q.get("options") or [], start=1):
                    op = doc.add_paragraph()
                    _set_run_font(op.add_run(f"   ({chr(96+idx)}) "), font_name, 11, bold=True)
                    _set_run_font(op.add_run(str(opt)), font_name, 11)
            q_counter += 1

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return send_file(
        buf,
        as_attachment=True,
        download_name=f"paper_{paper_id}.docx",
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

_ANSWER_KEY_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="{{ lang_attr }}">
<head>
<meta charset="UTF-8">
<style>
@page { size: A4; margin: 22mm 18mm; }
@font-face {
  font-family: 'NotoDev';
  src: url('{{ font_url_regular }}') format('truetype');
  font-weight: 400;
}
@font-face {
  font-family: 'NotoDev';
  src: url('{{ font_url_bold }}') format('truetype');
  font-weight: 700;
}
html, body {
  font-family: 'NotoDev', 'Noto Sans Devanagari', sans-serif;
  font-size: 11.5pt;
  line-height: 1.55;
  color: #1a1a1a;
}
.header { text-align: center; border-bottom: 2px solid #222; padding-bottom: 8px; margin-bottom: 14px; }
.header h1 { font-size: 18pt; margin: 0; font-weight: 700; }
.header h2 { font-size: 12pt; margin: 4px 0; font-weight: 400; color: #444; }
.meta { font-size: 10.5pt; color: #333; margin-bottom: 14px; }
.entry { margin-bottom: 14px; page-break-inside: avoid; }
.entry .q { font-weight: 700; }
.entry .a { margin-top: 4px; padding-left: 12px; }
.entry .a .label { font-weight: 700; color: #0a6e54; }
.entry .e { margin-top: 4px; padding-left: 12px; color: #444; font-size: 10.5pt; }
.entry .e .label { font-weight: 700; }
hr.sep { border: 0; border-top: 1px dashed #ccc; margin: 10px 0; }
</style>
</head>
<body>
  <div class="header">
    <h1>{{ labels.answer_key }} — {{ exam_name }}</h1>
    <h2>{{ school }}</h2>
  </div>
  <div class="meta">{{ labels.class }} {{ class_ }} &middot; {{ subject }} &middot; {{ labels.date }}: {{ date }}</div>
  {% for q in questions %}
    <div class="entry">
      <div class="q">{{ labels.q_prefix }}{{ loop.index }}. {{ q.question_text | math_render | safe }}</div>
      {% if q.question_type == 'MCQ' and q.options %}
        <ol type="a" style="margin: 4px 0 4px 24px;">
          {% for opt in q.options %}<li>{{ opt | math_render | safe }}</li>{% endfor %}
        </ol>
      {% endif %}
      <div class="a"><span class="label">{{ labels.answer }}:</span> {{ q.answer | math_render | safe }}</div>
      {% if q.explanation %}
        <div class="e"><span class="label">{{ labels.explanation }}:</span> {{ q.explanation | math_render | safe }}</div>
      {% endif %}
    </div>
    <hr class="sep">
  {% endfor %}
</body>
</html>
"""


@main.route("/api/download/answer_key/<paper_id>", methods=["GET"])
def download_answer_key(paper_id):
    json_path = os.path.join(current_app.root_path, "static", "papers", f"{paper_id}.json")
    if not os.path.exists(json_path):
        return jsonify({"error": "Paper not found"}), 404

    with open(json_path, "r", encoding="utf-8") as f:
        paper = json.load(f)

    # Detect paper language from any question entry (defaults to English).
    paper_language = "english"
    for q in paper.get("questions", []):
        if (q.get("language") or "").lower() == "hindi":
            paper_language = "hindi"
            break
    lang = "hi" if paper_language == "hindi" else "en"

    fonts_dir = os.path.join(current_app.root_path, "fonts")
    font_url_regular = pathlib.Path(os.path.join(fonts_dir, "NotoSansDevanagari-Regular.ttf")).as_uri()
    bold_path = os.path.join(fonts_dir, "NotoSansDevanagari-Bold.ttf")
    font_url_bold = pathlib.Path(bold_path).as_uri() if os.path.exists(bold_path) else font_url_regular

    env = current_app.jinja_env
    env.filters["math_render"] = render_simple_math

    rendered_html = render_template_string(
        _ANSWER_KEY_HTML_TEMPLATE,
        questions=paper.get("questions", []),
        exam_name=paper.get("examName") or ("परीक्षा" if paper_language == "hindi" else "Exam"),
        school=paper.get("schoolName") or "",
        class_=paper.get("class") or "",
        subject=paper.get("subject") or "",
        date=datetime.now().strftime("%d-%m-%Y"),
        font_url_regular=font_url_regular,
        font_url_bold=font_url_bold,
        lang_attr=lang,
        labels=_pdf_labels_for(paper_language),
    )

    pdf_bytes = HTML(string=rendered_html).write_pdf()
    buf = io.BytesIO(pdf_bytes)
    buf.seek(0)
    return send_file(
        buf,
        as_attachment=True,
        download_name=f"answer_key_{paper_id}.pdf",
        mimetype="application/pdf",
    )



