# AI Question Paper Generator

A Flask-based web application that generates customized school question papers using AI (Google Gemini API) combined with a structured question bank database. The system supports multiple educational boards, subjects, and languages, with automated PDF and Word document generation.

## Overview

This application helps educators create standardized examination papers by leveraging both AI-generated questions and a curated database of questions organized by board, class, subject, and chapter. It provides fine-grained control over question distribution, difficulty levels, and supports both English and Hindi languages.

### Target Users

- School teachers and exam coordinators
- Educational institutions (CBSE, ICSE, State Boards)
- Content creators for educational platforms

### Core Functionality

1. AI-powered question generation using Google Gemini API
2. Database-driven question bank with hierarchical organization
3. Customizable question papers by type, difficulty, and marks
4. Multi-format export (PDF, Word, Answer Key)
5. Visitor tracking and paper history
6. Multi-language support (English and Hindi with Devanagari font)

## Features

### Question Paper Generation

- **Topic-based generation**: Create papers focused on specific topics
- **Chapter-based generation**: Select multiple chapters from curriculum
- **Question type distribution**: Control mix of MCQ, Short Answer, Long Answer, Fill in the Blanks, Matching, and Case Study questions
- **Difficulty balancing**: Specify distribution across Easy, Medium, and Hard questions
- **Marks allocation**: Configure marks per question type

### Document Generation

- **PDF generation**: Professional formatting using WeasyPrint with Devanagari font support
- **Word documents**: DOCX format for easy editing
- **Answer keys**: Separate PDF with correct answers and explanations
- **Math symbol rendering**: Basic LaTeX-to-Unicode conversion for mathematical expressions

### Database Architecture

Hierarchical organization:
- Boards (CBSE, ICSE, etc.)
- Classes (1-12)
- Subjects (Math, Science, English, Hindi, etc.)
- Chapters (individual curriculum topics)
- Questions (with metadata: type, difficulty, marks, language)

### AI Fallback System

- Primary: Google Gemini Flash Latest
- Fallback 1: Google Gemini Pro Latest
- Fallback 2: Google Gemini 2.0 Flash
- Database fallback: Retrieve questions from local database when AI fails
- Emergency fallback: Generate basic placeholder questions if all else fails

### Visitor Tracking

- Cookie-based session tracking
- Visit count and paper generation history
- Anonymous visitor identification

## Tech Stack

### Backend

- **Framework**: Flask 3.1.0
- **Database ORM**: SQLAlchemy 2.0.38 with Flask-SQLAlchemy 3.2.0
- **Database**: MySQL (PyMySQL driver) with SQLite fallback
- **AI Integration**: Google Generative AI SDK (google-generativeai 0.8.6)

### Document Generation

- **PDF**: WeasyPrint 66.0 (with Cairo, Pango, and librsvg dependencies)
- **Word**: python-docx 1.2.0
- **Fonts**: Noto Sans Devanagari for Hindi support

### Deployment

- **WSGI Server**: Gunicorn 23.0.0 (configured with gthread workers)
- **Containerization**: Docker (Debian Bookworm slim base)
- **Platform**: Render-ready (with Dockerfile and Railway config examples)

### Additional Dependencies

- Jinja2 3.1.5 (templating)
- Alembic 1.16.5 (database migrations)
- python-dotenv 1.0.1 (environment configuration)

## Setup Instructions

### Prerequisites

- Python 3.13.7 or compatible version
- MySQL database (local or cloud-hosted)
- Google Gemini API key

### Local Development Setup

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd deploying-paper-generator-render-main
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   venv\Scripts\activate  # Windows
   # source venv/bin/activate  # Linux/Mac
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**
   
   Create a `.env` file in the project root:
   ```env
   DB_USER=root
   DB_PASSWORD=your_password
   DB_PORT=3306
   DB_HOST=localhost
   DB_NAME=question_paper_db
   
   GOOGLE_API_KEY=your_gemini_api_key_here
   ```

5. **Set up the database**
   
   Create the MySQL database:
   ```sql
   CREATE DATABASE question_paper_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   ```
   
   Run the visitors table SQL script:
   ```bash
   mysql -u root -p question_paper_db < visitors_table.sql
   ```
   
   The application will auto-create other tables on first run via SQLAlchemy.

6. **Populate the question bank**
   
   You need to manually populate the following tables with your curriculum data:
   - `boards` (educational boards)
   - `classes` (class numbers linked to boards)
   - `subjects` (subjects with English and Hindi names)
   - `chapters` (curriculum chapters)
   - `questions` (question bank with all metadata)

7. **Run the application**
   ```bash
   python run.py
   ```
   
   The server will start at `http://localhost:5000` in debug mode.

## Environment Variables

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `DB_USER` | MySQL username | `root` |
| `DB_PASSWORD` | MySQL password | `secure_password` |
| `DB_HOST` | MySQL host address | `localhost` or `yourdb.proxy.rlwy.net` |
| `DB_PORT` | MySQL port | `3306` |
| `DB_NAME` | Database name | `question_paper_db` |
| `GOOGLE_API_KEY` | Google Gemini API key | `AIzaSy...` |

### Optional Variables

- If database variables are not set, the application falls back to SQLite (`dev.db`)

## Database

### Schema Overview

**Core Tables:**

- `boards`: Educational boards (CBSE, ICSE, etc.)
- `classes`: Class levels (1-12) linked to boards
- `subjects`: Subjects with bilingual names (English/Hindi)
- `chapters`: Curriculum chapters with bilingual titles
- `questions`: Question bank with type, difficulty, marks, language

**Paper Management:**

- `visitors`: Anonymous visitor tracking via cookies
- `papers`: Generated paper metadata (exam name, school, timestamps, file paths)
- `paper_questions`: Join table linking papers to questions

### Database Migration Notes

- The application uses SQLAlchemy's `db.create_all()` for automatic table creation
- For production, consider using Alembic migrations for better version control
- The `visitors_table.sql` script includes foreign key constraints linking papers to visitors

### Character Encoding

Ensure MySQL uses UTF-8 for proper Hindi/Devanagari character support:
```sql
ALTER DATABASE question_paper_db CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci;
```
