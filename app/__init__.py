import logging
import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

load_dotenv()

db = SQLAlchemy()

# Global rate limiter — applied selectively per-route via decorator.
limiter = Limiter(
    key_func=lambda: _visitor_or_ip(),
    default_limits=[],
    storage_uri="memory://",
)


def _visitor_or_ip() -> str:
    """Rate-limit key: prefer visitor cookie, fall back to remote IP."""
    from flask import request
    vid = request.cookies.get("visitor_id") if request else None
    return vid or get_remote_address()


def create_app():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

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
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # 2 MB request cap

    db.init_app(app)
    limiter.init_app(app)

    # Same-origin by default; widen CORS only if frontend is hosted separately.
    cors_origins = os.getenv("CORS_ORIGINS", "").strip()
    if cors_origins:
        CORS(app, resources={r"/api/*": {"origins": cors_origins.split(",")}})
    else:
        CORS(app, resources={r"/api/*": {"origins": []}})

    # Initialize the AI provider chain (no-op if no keys set).
    from .ai_providers import init_providers
    providers = init_providers()
    app.logger.info("AI providers active: %s", [p.name for p in providers] or "NONE")

    with app.app_context():
        from . import models  # noqa: F401
        db.create_all()

        from .routes import main as main_bp
        app.register_blueprint(main_bp)

    return app
