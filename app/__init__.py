import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

db = SQLAlchemy()
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")

    # --- Database Configuration START ---
    database_url = os.getenv("DATABASE_URL")

    if database_url:
        app.config["SQLALCHEMY_DATABASE_URI"] = database_url
        print("--- Using PostgreSQL via DATABASE_URL ---")
    else:
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///dev.db"
        print("--- Using SQLite fallback ---")
    # --- Database Configuration END ---

    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JSON_SORT_KEYS"] = False

    db.init_app(app)

    with app.app_context():
        from . import models  # noqa: F401
        db.create_all()

        from .routes import main as main_bp
        app.register_blueprint(main_bp)

    return app
