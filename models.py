from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import Table, Column, Integer, ForeignKey, LargeBinary, Text
from sqlalchemy.orm import relationship

db = SQLAlchemy()

# many-to-many for likes (user <-> track)
likes_table = db.Table(
    "likes",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
    db.Column("track_id", db.Integer, db.ForeignKey("tracks.id"), primary_key=True),
)

class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, index=True, nullable=False)
    email = db.Column(db.String(255), unique=True, index=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    bio = db.Column(db.Text, default="")
    avatar_filename = db.Column(db.String(255), nullable=True)
    avatar_data = db.Column(db.LargeBinary, nullable=True)  # optional store avatar bytes in db
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tracks = db.relationship("Track", backref="owner", lazy="dynamic")
    playlists = db.relationship("Playlist", backref="owner", lazy="dynamic")

    # followers/following (self-referential)
    following = db.relationship(
        "Follow",
        foreign_keys="Follow.follower_id",
        backref="follower_user",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    followers = db.relationship(
        "Follow",
        foreign_keys="Follow.followed_id",
        backref="followed_user",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    favorites = db.relationship("Favorite", backref="user", lazy="dynamic")

    likes = db.relationship("Track", secondary=likes_table, back_populates="liked_by", lazy="dynamic")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Follow(db.Model):
    __tablename__ = "follows"
    id = db.Column(db.Integer, primary_key=True)
    follower_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    followed_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Track(db.Model):
    __tablename__ = "tracks"
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, default="")
    duration = db.Column(db.Integer, default=0)  # duration in seconds
    mime_type = db.Column(db.String(80), default="audio/mpeg")
    original_filename = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_public = db.Column(db.Boolean, default=True)

    # STORAGE OPTIONS:
    # If STORAGE_MODE == 'local' we store path strings.
    file_path = db.Column(db.String(1024), nullable=True)
    mp3_path = db.Column(db.String(1024), nullable=True)
    preview_path = db.Column(db.String(1024), nullable=True)

    # If STORAGE_MODE == 'postgres' we may store binary fields:
    original_file = db.Column(db.LargeBinary, nullable=True)
    mp3_file = db.Column(db.LargeBinary, nullable=True)
    preview_file = db.Column(db.LargeBinary, nullable=True)

    # For S3 we store keys:
    s3_key = db.Column(db.String(1024), nullable=True)
    s3_mp3_key = db.Column(db.String(1024), nullable=True)
    s3_preview_key = db.Column(db.String(1024), nullable=True)

    comments = db.relationship("Comment", backref="track", lazy="dynamic")
    favorites = db.relationship("Favorite", backref="track", lazy="dynamic")

    # likes relationship
    liked_by = db.relationship("User", secondary=likes_table, back_populates="likes", lazy="dynamic")

class Favorite(db.Model):
    __tablename__ = "favorites"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    track_id = db.Column(db.Integer, db.ForeignKey("tracks.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Comment(db.Model):
    __tablename__ = "comments"
    id = db.Column(db.Integer, primary_key=True)
    track_id = db.Column(db.Integer, db.ForeignKey("tracks.id"))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    body = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship("User")

class Playlist(db.Model):
    __tablename__ = "playlists"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    tracks = db.relationship("PlaylistTrack", backref="playlist", lazy="dynamic", cascade="all, delete-orphan")

class PlaylistTrack(db.Model):
    __tablename__ = "playlist_tracks"
    id = db.Column(db.Integer, primary_key=True)
    playlist_id = db.Column(db.Integer, db.ForeignKey("playlists.id"))
    track_id = db.Column(db.Integer, db.ForeignKey("tracks.id"))
    order = db.Column(db.Integer, default=0)
    track = db.relationship("Track")
