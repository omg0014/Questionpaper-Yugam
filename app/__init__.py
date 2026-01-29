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

    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        db_user = os.getenv("DB_USER")
        db_password = os.getenv("DB_PASSWORD")
        db_host = os.getenv("DB_HOST")
        db_port = os.getenv("DB_PORT", "3306")
        db_name = os.getenv("DB_NAME")

        if db_user and db_password and db_host and db_name:
            database_url = (
                f"mysql+pymysql://{db_user}:{db_password}"
                f"@{db_host}:{db_port}/{db_name}"
            )
        else:
            database_url = "sqlite:///app.db"

    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JSON_SORT_KEYS"] = False

    db.init_app(app)

    with app.app_context():
        from . import models
        db.create_all()

        from .routes import main as main_bp
        app.register_blueprint(main_bp)

    return app
