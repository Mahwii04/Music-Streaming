import os
import io
import uuid
import logging
from pathlib import Path
from pydub import AudioSegment
import ffmpeg
from PIL import Image
from werkzeug.utils import secure_filename
from models import db, Track, User
from sqlalchemy.exc import SQLAlchemyError
import boto3

logger = logging.getLogger(__name__)

def allowed_file(filename, allowed):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed

def ensure_upload_folder(folder):
    Path(folder).mkdir(parents=True, exist_ok=True)

def handle_avatar_upload(user, file_storage, app):
    """Resize and save avatar. Depending on storage mode, save bytes to DB or a local file or S3."""
    img = Image.open(file_storage.stream)
    img.thumbnail(app.config["AVATAR_MAX_SIZE"])
    out = io.BytesIO()
    img.save(out, format="PNG")
    out.seek(0)
    filename = f"avatar_{user.id}_{uuid.uuid4().hex}.png"
    if app.config["STORAGE_MODE"] == "postgres":
        user.avatar_data = out.getvalue()
        user.avatar_filename = filename
    elif app.config["STORAGE_MODE"] == "s3":
        s3 = boto3.client(
            "s3",
            aws_access_key_id=app.config["AWS_ACCESS_KEY_ID"],
            aws_secret_access_key=app.config["AWS_SECRET_ACCESS_KEY"],
            region_name=app.config.get("S3_REGION")
        )
        key = f"avatars/{filename}"
        s3.put_object(Bucket=app.config["S3_BUCKET"], Key=key, Body=out.getvalue(), ContentType="image/png")
        user.avatar_filename = key
    else:
        out_path = Path(app.config["UPLOAD_FOLDER"]) / "avatars"
        out_path.mkdir(parents=True, exist_ok=True)
        file_path = out_path / filename
        with open(file_path, "wb") as fh:
            fh.write(out.getvalue())
        user.avatar_filename = str(file_path)
    db.session.commit()

def process_track_upload(track, file_storage, app):
    """
    Save original and create MP3 transcoded version and preview clip.
    Behavior depends on app.config['STORAGE_MODE'] (local, s3, postgres).
    """
    # load into AudioSegment via pydub (which uses ffmpeg)
    filename = secure_filename(file_storage.filename)
    ext = filename.rsplit(".", 1)[1].lower()
    orig_bytes = file_storage.read()
    # determine duration via pydub
    audio = AudioSegment.from_file(io.BytesIO(orig_bytes), format=ext)
    duration_ms = len(audio)
    track.duration = int(duration_ms / 1000)
    track.original_filename = filename
    # create mp3 (transcode)
    mp3_io = io.BytesIO()
    audio.export(mp3_io, format="mp3", bitrate=app.config["TRANSCODE_BITRATE"])
    mp3_io.seek(0)
    # create preview (clip)
    preview_len = int(app.config.get("PREVIEW_DURATION", 30)) * 1000
    preview_seg = audio[:preview_len]
    preview_io = io.BytesIO()
    preview_seg.export(preview_io, format="mp3", bitrate=app.config["TRANSCODE_BITRATE"])
    preview_io.seek(0)

    mode = app.config["STORAGE_MODE"]
    if mode == "postgres":
        track.original_file = orig_bytes
        track.mp3_file = mp3_io.getvalue()
        track.preview_file = preview_io.getvalue()
    elif mode == "s3":
        s3 = boto3.client(
            "s3",
            aws_access_key_id=app.config["AWS_ACCESS_KEY_ID"],
            aws_secret_access_key=app.config["AWS_SECRET_ACCESS_KEY"],
            region_name=app.config.get("S3_REGION")
        )
        key_base = f"tracks/{track.owner_id}/{uuid.uuid4().hex}"
        s3.put_object(Bucket=app.config["S3_BUCKET"], Key=key_base + "/original." + ext, Body=orig_bytes, ContentType="audio/" + ext)
        s3.put_object(Bucket=app.config["S3_BUCKET"], Key=key_base + "/stream.mp3", Body=mp3_io.getvalue(), ContentType="audio/mpeg")
        s3.put_object(Bucket=app.config["S3_BUCKET"], Key=key_base + "/preview.mp3", Body=preview_io.getvalue(), ContentType="audio/mpeg")
        track.s3_key = key_base + "/original." + ext
        track.s3_mp3_key = key_base + "/stream.mp3"
        track.s3_preview_key = key_base + "/preview.mp3"
    else:
        # local filesystem
        base = Path(app.config["UPLOAD_FOLDER"]) / str(track.owner_id)
        base.mkdir(parents=True, exist_ok=True)
        orig_path = base / f"{uuid.uuid4().hex}_orig.{ext}"
        with open(orig_path, "wb") as fh:
            fh.write(orig_bytes)
        mp3_path = base / f"{uuid.uuid4().hex}_stream.mp3"
        with open(mp3_path, "wb") as fh:
            fh.write(mp3_io.getvalue())
        preview_path = base / f"{uuid.uuid4().hex}_preview.mp3"
        with open(preview_path, "wb") as fh:
            fh.write(preview_io.getvalue())
        track.file_path = str(orig_path)
        track.mp3_path = str(mp3_path)
        track.preview_path = str(preview_path)
    # set mime
    track.mime_type = "audio/mpeg"
    db.session.add(track)
    db.session.flush()

def get_file_stream_response(track, variant="mp3", app=None):
    """
    variant: 'mp3' or 'original' or 'preview'
    Returns a Flask response streaming the appropriate file.
    """
    mode = app.config["STORAGE_MODE"]
    if mode == "postgres":
        if variant == "mp3" and track.mp3_file:
            return send_file(io.BytesIO(track.mp3_file), mimetype="audio/mpeg", as_attachment=False, download_name=f"{track.title}.mp3")
        elif variant == "preview" and track.preview_file:
            return send_file(io.BytesIO(track.preview_file), mimetype="audio/mpeg", as_attachment=False, download_name=f"{track.title}_preview.mp3")
        elif track.original_file:
            # try detect original mime
            return send_file(io.BytesIO(track.original_file), mimetype=track.mime_type or "application/octet-stream", as_attachment=False, download_name=track.original_filename)
    elif mode == "s3":
        s3 = boto3.client(
            "s3",
            aws_access_key_id=app.config["AWS_ACCESS_KEY_ID"],
            aws_secret_access_key=app.config["AWS_SECRET_ACCESS_KEY"],
            region_name=app.config.get("S3_REGION")
        )
        key = None
        if variant == "mp3":
            key = track.s3_mp3_key or track.s3_key
        elif variant == "preview":
            key = track.s3_preview_key or track.s3_mp3_key
        else:
            key = track.s3_key
        if not key:
            abort(404)
        obj = s3.get_object(Bucket=app.config["S3_BUCKET"], Key=key)
        body = obj["Body"].read()
        content_type = obj.get("ContentType", "audio/mpeg")
        return send_file(io.BytesIO(body), mimetype=content_type, as_attachment=False, download_name=track.title)
    else:
        # local paths
        path = None
        if variant == "mp3":
            path = track.mp3_path or track.file_path
        elif variant == "preview":
            path = track.preview_path or track.mp3_path
        else:
            path = track.file_path
        if not path or not os.path.exists(path):
            abort(404)
        return send_file(path, mimetype=track.mime_type or "audio/mpeg", as_attachment=False, download_name=os.path.basename(path))

def storage_delete(track, app):
    """Remove files from storage when rollback/failed upload cleanup needed."""
    mode = app.config["STORAGE_MODE"]
    try:
        if mode == "local":
            for p in (track.file_path, track.mp3_path, track.preview_path, getattr(track, "avatar_filename", None)):
                if p and os.path.exists(p):
                    os.remove(p)
        elif mode == "s3":
            s3 = boto3.client(
                "s3",
                aws_access_key_id=app.config["AWS_ACCESS_KEY_ID"],
                aws_secret_access_key=app.config["AWS_SECRET_ACCESS_KEY"],
                region_name=app.config.get("S3_REGION")
            )
            keys = [k for k in (track.s3_key, track.s3_mp3_key, track.s3_preview_key) if k]
            for k in keys:
                s3.delete_object(Bucket=app.config["S3_BUCKET"], Key=k)
        else:
            # postgres: null out binary fields
            track.original_file = None
            track.mp3_file = None
            track.preview_file = None
            db.session.commit()
    except Exception as e:
        logger.exception("Error cleaning storage: %s", e)
