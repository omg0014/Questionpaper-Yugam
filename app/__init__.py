import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

db = SQLAlchemy()

# Configure Gemini API
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")

    # -------------------------------
    # Database Configuration (MySQL / FreeDB)
    # -------------------------------
    DB_HOST = os.getenv("DB_HOST")
    DB_PORT = os.getenv("DB_PORT", "3306")
    DB_NAME = os.getenv("DB_NAME")
    DB_USER = os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("DB_PASSWORD")

    if all([DB_HOST, DB_NAME, DB_USER, DB_PASSWORD]):
        app.config["SQLALCHEMY_DATABASE_URI"] = (
            f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@"
            f"{DB_HOST}:{DB_PORT}/{DB_NAME}"
        )
        print("--- Using FreeDB MySQL ---")
    else:
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///dev.db"
        print("--- Using SQLite fallback (local dev) ---")

    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JSON_SORT_KEYS"] = False

    db.init_app(app)

    with app.app_context():
        from . import models  # noqa: F401
        db.create_all()

        from .routes import main as main_bp
        app.register_blueprint(main_bp)

    return app
