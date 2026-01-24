import os
import urllib.parse
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
    db_user = os.getenv("DB_USER")
    db_pass_raw = os.getenv("DB_PASSWORD")
    db_host = os.getenv("DB_HOST")
    db_name = os.getenv("DB_NAME")
    db_port = os.getenv("DB_PORT", "3306")

    if db_user and db_pass_raw and db_host and db_name:
        # URL-encode the password in case it contains special characters
        db_pass = urllib.parse.quote_plus(db_pass_raw)
        
        # *** DEBUG: Print the final URI for verification ***
        final_uri = f"mysql+pymysql://{db_user}:***@{db_host}:{db_port}/{db_name}"
        print(f"--- Railway MySQL Configuration on HOST: {db_host} ---")
        print(f"--- Final SQLAlchemy URI (Excluding Password): {final_uri} ---")
        
        # Use the constructed URI for the app
        app.config["SQLALCHEMY_DATABASE_URI"] = (
            f"mysql+pymysql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
        )
    else:
        # Fallback to SQLite (only for local development/testing)
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///dev.db"
        print("--- Using Local SQLite (or falling back) Configuration ---")
    # --- Database Configuration END ---

    # These lines must be at the same indentation level as the 'if/else' block
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JSON_SORT_KEYS"] = False

    db.init_app(app)

    with app.app_context():
        # Code inside the context block (indented one more level)
        from . import models  # noqa: F401
        
        # This is where the connection attempt happens
        db.create_all()
        
        from .routes import main as main_bp
        app.register_blueprint(main_bp)

    return app
