import os
import io
import uuid
import datetime
from flask import (
    Flask, render_template, redirect, url_for, flash, request, send_file, abort, jsonify
)
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.utils import secure_filename
from PIL import Image
from config import DevConfig, ProdConfig
from forms import RegisterForm, LoginForm, UploadForm, ProfileForm, PlaylistForm, CommentForm
from models import db, User, Track, Follow, Favorite, Comment, Playlist, PlaylistTrack
from utils import (
    allowed_file, ensure_upload_folder,
    handle_avatar_upload, process_track_upload,
    get_file_stream_response, storage_delete
)

# choose config
ENV = os.environ.get("FLASK_ENV", "development")
config = ProdConfig if ENV == "production" else DevConfig

app = Flask(__name__)
app.config.from_object(config)

# extensions
db.init_app(app)
migrate = Migrate(app, db)
login_manager = LoginManager(app)
login_manager.login_view = "login"

# ensure upload folder
if app.config["STORAGE_MODE"] == "local":
    ensure_upload_folder(app.config["UPLOAD_FOLDER"])

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.context_processor
def inject_now():
    return {"now": datetime.datetime.utcnow()}

@app.route("/")
def index():
    page = request.args.get("page", 1, type=int)
    q = request.args.get("q", "").strip()
    query = Track.query.filter(Track.is_public.is_(True)).order_by(Track.created_at.desc())
    if q:
        query = query.filter(Track.title.ilike(f"%{q}%"))
    tracks = query.paginate(page=page, per_page=12)
    return render_template("index.html", tracks=tracks, q=q)

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    form = RegisterForm()
    if form.validate_on_submit():
        if User.query.filter_by(email=form.email.data).first():
            flash("Email already registered.", "warning")
            return render_template("register.html", form=form)
        user = User(
            username=form.username.data,
            email=form.email.data
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash("Welcome — your account is ready!", "success")
        return redirect(url_for("index"))
    return render_template("register.html", form=form)

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember.data)
            flash("Logged in", "success")
            return redirect(request.args.get("next") or url_for("index"))
        flash("Invalid credentials", "danger")
    return render_template("login.html", form=form)

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out", "info")
    return redirect(url_for("index"))

@app.route("/profile/<username>", methods=["GET", "POST"])
def profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    is_following = False
    if current_user.is_authenticated and current_user.id != user.id:
        is_following = Follow.query.filter_by(follower_id=current_user.id, followed_id=user.id).first() is not None
    form = ProfileForm()
    if current_user.is_authenticated and current_user.id == user.id and form.validate_on_submit():
        if form.avatar.data:
            handle_avatar_upload(current_user, form.avatar.data, app)
        current_user.bio = form.bio.data
        db.session.commit()
        flash("Profile updated", "success")
        return redirect(url_for("profile", username=current_user.username))
    tracks = Track.query.filter_by(owner_id=user.id).order_by(Track.created_at.desc()).all()
    return render_template("profile.html", profile_user=user, is_following=is_following, form=form, tracks=tracks)

@app.route("/follow/<int:user_id>", methods=["POST"])
@login_required
def follow(user_id):
    to_follow = User.query.get_or_404(user_id)
    if to_follow.id == current_user.id:
        return jsonify({"error": "cannot follow yourself"}), 400
    if Follow.query.filter_by(follower_id=current_user.id, followed_id=to_follow.id).first():
        return jsonify({"status": "already_following"})
    follow = Follow(follower_id=current_user.id, followed_id=to_follow.id)
    db.session.add(follow)
    db.session.commit()
    return jsonify({"status": "ok", "followers_count": to_follow.followers.count()})

@app.route("/unfollow/<int:user_id>", methods=["POST"])
@login_required
def unfollow(user_id):
    to_unfollow = User.query.get_or_404(user_id)
    follow = Follow.query.filter_by(follower_id=current_user.id, followed_id=to_unfollow.id).first()
    if follow:
        db.session.delete(follow)
        db.session.commit()
    return jsonify({"status": "ok", "followers_count": to_unfollow.followers.count()})

@app.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    form = UploadForm()
    if form.validate_on_submit():
        f = form.track.data
        if not allowed_file(f.filename, app.config["ALLOWED_EXTENSIONS"]):
            flash("File type not allowed.", "danger")
            return redirect(url_for("upload"))
        # secure & visible meta
        filename = secure_filename(f.filename)
        title = form.title.data or filename.rsplit(".", 1)[0]
        track = Track(owner_id=current_user.id, title=title, description=form.description.data)
        db.session.add(track)
        db.session.flush()  # get id
        try:
            # process upload: store original + generate mp3 + preview clip
            process_track_upload(track, f, app)
            db.session.commit()
            flash("Upload successful — transcoding & previews created.", "success")
            return redirect(url_for("track", track_id=track.id))
        except Exception as e:
            db.session.rollback()
            # cleanup any stored files if necessary
            storage_delete(track, app)
            app.logger.exception("Upload failed")
            flash("Upload failed: " + str(e), "danger")
    return render_template("upload.html", form=form)

@app.route("/track/<int:track_id>")
def track(track_id):
    track = Track.query.get_or_404(track_id)
    comments = Comment.query.filter_by(track_id=track_id).order_by(Comment.created_at.asc()).all()
    is_favorited = False
    if current_user.is_authenticated:
        is_favorited = Favorite.query.filter_by(user_id=current_user.id, track_id=track.id).first() is not None
    return render_template("track.html", track=track, comments=comments, is_favorited=is_favorited, comment_form=CommentForm())

@app.route("/stream/<int:track_id>")
def stream(track_id):
    """
    Serve transcoded mp3 if available, else original. Supports streaming via send_file from memory/file.
    For large-scale production use S3 signed URLs or proper file streaming with Range requests.
    """
    track = Track.query.get_or_404(track_id)
    # prefer mp3_stream (transcoded) field if available
    return get_file_stream_response(track, variant="mp3", app=app)

@app.route("/preview/<int:track_id>")
def preview(track_id):
    track = Track.query.get_or_404(track_id)
    return get_file_stream_response(track, variant="preview", app=app)

@app.route("/like/<int:track_id>", methods=["POST"])
@login_required
def like(track_id):
    track = Track.query.get_or_404(track_id)
    if track.likes.filter_by(user_id=current_user.id).first():
        return jsonify({"status": "already_liked"})
    track.likes.append(current_user)
    db.session.commit()
    return jsonify({"status": "ok", "likes_count": track.likes.count()})

@app.route("/unlike/<int:track_id>", methods=["POST"])
@login_required
def unlike(track_id):
    track = Track.query.get_or_404(track_id)
    if track.likes.filter_by(user_id=current_user.id).first():
        track.likes.remove(current_user)
        db.session.commit()
    return jsonify({"status": "ok", "likes_count": track.likes.count()})

@app.route("/favorite/<int:track_id>", methods=["POST"])
@login_required
def favorite(track_id):
    track = Track.query.get_or_404(track_id)
    if Favorite.query.filter_by(user_id=current_user.id, track_id=track.id).first():
        return jsonify({"status": "already_favorited"})
    fav = Favorite(user_id=current_user.id, track_id=track.id)
    db.session.add(fav)
    db.session.commit()
    return jsonify({"status": "ok"})

@app.route("/unfavorite/<int:track_id>", methods=["POST"])
@login_required
def unfavorite(track_id):
    fav = Favorite.query.filter_by(user_id=current_user.id, track_id=track_id).first()
    if fav:
        db.session.delete(fav)
        db.session.commit()
    return jsonify({"status": "ok"})

@app.route("/comment/<int:track_id>", methods=["POST"])
@login_required
def comment(track_id):
    form = CommentForm()
    if form.validate_on_submit():
        track = Track.query.get_or_404(track_id)
        c = Comment(track_id=track.id, user_id=current_user.id, body=form.body.data)
        db.session.add(c)
        db.session.commit()
        return redirect(url_for("track", track_id=track_id) + "#comments")
    return redirect(url_for("track", track_id=track_id))

@app.route("/playlist/create", methods=["GET", "POST"])
@login_required
def playlist_create():
    form = PlaylistForm()
    if form.validate_on_submit():
        p = Playlist(title=form.title.data, user_id=current_user.id, description=form.description.data)
        db.session.add(p)
        db.session.commit()
        flash("Playlist created", "success")
        return redirect(url_for("playlist_view", playlist_id=p.id))
    return render_template("playlist_form.html", form=form)

@app.route("/playlist/<int:playlist_id>")
def playlist_view(playlist_id):
    p = Playlist.query.get_or_404(playlist_id)
    return render_template("playlist.html", playlist=p)

@app.route("/playlist/<int:playlist_id>/add/<int:track_id>", methods=["POST"])
@login_required
def playlist_add_track(playlist_id, track_id):
    p = Playlist.query.get_or_404(playlist_id)
    if p.user_id != current_user.id:
        abort(403)
    if PlaylistTrack.query.filter_by(playlist_id=p.id, track_id=track_id).first() is None:
        pt = PlaylistTrack(playlist_id=p.id, track_id=track_id)
        db.session.add(pt)
        db.session.commit()
    return jsonify({"status": "ok"})

@app.route("/search")
def search():
    q = request.args.get("q", "")
    tracks = []
    if q:
        tracks = Track.query.filter(Track.title.ilike(f"%{q}%")).limit(20).all()
    return render_template("search.html", q=q, tracks=tracks)

# simple user settings
@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    form = ProfileForm(obj=current_user)
    if form.validate_on_submit():
        current_user.bio = form.bio.data
        if form.avatar.data:
            handle_avatar_upload(current_user, form.avatar.data, app)
        db.session.commit()
        flash("Settings saved", "success")
        return redirect(url_for("profile", username=current_user.username))
    return render_template("settings.html", form=form)

if __name__ == "__main__":
    app.run(debug=(ENV != "production"))
