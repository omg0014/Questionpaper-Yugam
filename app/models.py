from . import db

# app/models.py

# New model for the 'Boards' table
class Board(db.Model):
    __tablename__ = "boards"
    board_id = db.Column(db.Integer, primary_key=True) # CHANGED from id
    name = db.Column(db.String(50), nullable=False, unique=True)
    classes = db.relationship("Class", backref="board", lazy=True, cascade="all, delete-orphan")

# New model for the 'Classes' table
class Class(db.Model):
    __tablename__ = "classes"
    class_id = db.Column(db.Integer, primary_key=True) # CHANGED from id
    board_id = db.Column(db.Integer, db.ForeignKey("boards.board_id"), nullable=False) # CHANGED foreign key target
    class_number = db.Column(db.Integer, nullable=False)
    subjects = db.relationship("Subject", backref="class_", lazy=True, cascade="all, delete-orphan")

# New model for the 'Subjects' table
class Subject(db.Model):
    __tablename__ = "subjects"
    subject_id = db.Column(db.Integer, primary_key=True) # CHANGED from id
    class_id = db.Column(db.Integer, db.ForeignKey("classes.class_id"), nullable=False) # CHANGED foreign key target
    name_en = db.Column(db.String(100), nullable=False)
    name_hi = db.Column(db.String(100), nullable=False)
    chapters = db.relationship("Chapter", backref="subject", lazy=True, cascade="all, delete-orphan")

# New model for the 'Chapters' table
class Chapter(db.Model):
    __tablename__ = "chapters"
    chapter_id = db.Column(db.Integer, primary_key=True) # CHANGED from id
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.subject_id"), nullable=False) # CHANGED foreign key target
    chapter_number = db.Column(db.Integer)
    title_en = db.Column(db.String(255), nullable=False)
    title_hi = db.Column(db.String(255), nullable=False)
    questions = db.relationship("Question", backref="chapter", lazy=True)

# MODIFIED Question model
class Question(db.Model):
    __tablename__ = "questions"
    id = db.Column(db.Integer, primary_key=True)
    chapter_id = db.Column(db.Integer, db.ForeignKey("chapters.chapter_id"), nullable=False) # CHANGED foreign key target

    # ... keep the rest of the Question model fields the same ...
    question_type = db.Column(db.String(50))
    difficulty = db.Column(db.String(20))
    marks = db.Column(db.Integer)
    question_text = db.Column(db.Text)
    options = db.Column(db.JSON, default=[])
    answer = db.Column(db.Text)
    source = db.Column(db.String(50))
    explanation = db.Column(db.Text)
    language = db.Column(db.String(20), default='english', nullable=False)

    def as_dict(self):
        return {
            "id": self.id,
            "board": self.chapter.subject.class_.board.name,
            "class_": self.chapter.subject.class_.class_number,
            "subject": self.chapter.subject.name_en,
            "chapter": self.chapter.title_en,
            # ... keep the rest of the as_dict method the same ...
            "question_type": self.question_type,
            "difficulty": self.difficulty,
            "marks": self.marks,
            "question_text": self.question_text,
            "options": self.options or [],
            "answer": self.answer,
            "source": self.source,
            "explanation": self.explanation,
            "language": self.language
        }

# ... keep the Visitor, Paper, and PaperQuestion models as they are ...

# Keep your Visitor, Paper, and PaperQuestion models as they were.
# (Code for those models goes here)
class Visitor(db.Model):
    # ... (no changes needed here)
    __tablename__ = "visitors"
    id = db.Column(db.Integer, primary_key=True)
    visitor_id = db.Column(db.String(50), unique=True, nullable=False)
    first_visit = db.Column(db.DateTime, server_default=db.func.now())
    last_visit = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    visit_count = db.Column(db.Integer, default=1)
    papers = db.relationship("Paper", backref="visitor", lazy=True)


class Paper(db.Model):
    # ... (no changes needed here)
    __tablename__ = "papers"
    id = db.Column(db.Integer, primary_key=True)
    paper_id = db.Column(db.String(50), unique=True)
    exam_name = db.Column(db.String(100))
    school_name = db.Column(db.String(100))
    board = db.Column(db.String(50))
    class_ = db.Column(db.String(10))
    subject = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    total_questions = db.Column(db.Integer)
    total_marks = db.Column(db.Integer)
    pdf_path = db.Column(db.String(255))
    word_path = db.Column(db.String(255))
    answer_key_path = db.Column(db.String(255))
    visitor_id = db.Column(db.String(50), db.ForeignKey('visitors.visitor_id'), nullable=True)
    questions = db.relationship("PaperQuestion", back_populates="paper", cascade="all, delete-orphan")


class PaperQuestion(db.Model):
    # ... (no changes needed here)
    __tablename__ = "paper_questions"
    id = db.Column(db.Integer, primary_key=True)
    paper_id = db.Column(db.String(50), db.ForeignKey("papers.paper_id", ondelete="CASCADE"))
    question_id = db.Column(db.Integer)
    question_text = db.Column(db.Text)
    type = db.Column(db.String(50))
    difficulty = db.Column(db.String(20))
    marks = db.Column(db.Integer)
    options = db.Column(db.JSON, default=[])
    answer = db.Column(db.Text)
    paper = db.relationship("Paper", back_populates="questions")