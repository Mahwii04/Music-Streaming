import os
from pathlib import Path

BASE_DIR = Path(__file__).parent

class BaseConfig:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_MAX_CONTENT_LENGTH = 200 * 1024 * 1024  # 200 MB upload limit
    ALLOWED_EXTENSIONS = {"mp3", "wav", "flac", "m4a", "ogg", "aac"}
    AVATAR_MAX_SIZE = (512, 512)

    # storage_mode: "local", "s3", or "postgres"
    STORAGE_MODE = os.environ.get("STORAGE_MODE", "local")

    # local storage
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", str(BASE_DIR / "uploads"))

    # s3 settings (only used if STORAGE_MODE == 's3')
    S3_BUCKET = os.environ.get("S3_BUCKET")
    S3_REGION = os.environ.get("S3_REGION")
    AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")

    # ffmpeg/pydub settings
    PREVIEW_DURATION = int(os.environ.get("PREVIEW_DURATION", 30))  # preview length in seconds
    TRANSCODE_BITRATE = os.environ.get("TRANSCODE_BITRATE", "192k")

class DevConfig(BaseConfig):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DEV_DATABASE_URL", "sqlite:///" + str(BASE_DIR / "dev.db")
    )

class ProdConfig(BaseConfig):
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")  # expects Postgres URI
    # ensure upload folder exists for local mode
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "/var/www/flask_music/uploads")
