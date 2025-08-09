from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, TextAreaField, FileField, SubmitField
from wtforms.validators import DataRequired, Email, Length, EqualTo, Optional
from flask_wtf.file import FileAllowed, FileRequired

class RegisterForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(3, 80)])
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired(), Length(6, 128)])
    password2 = PasswordField("Confirm Password", validators=[DataRequired(), EqualTo("password")])
    submit = SubmitField("Sign up")

class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])
    remember = BooleanField("Remember me")
    submit = SubmitField("Sign in")

class UploadForm(FlaskForm):
    title = StringField("Title", validators=[Optional(), Length(max=255)])
    description = TextAreaField("Description", validators=[Optional(), Length(max=2000)])
    track = FileField("Upload track", validators=[FileRequired(), FileAllowed(["mp3", "wav", "flac", "m4a", "ogg", "aac"], "Audio files only!")])
    submit = SubmitField("Upload")

class ProfileForm(FlaskForm):
    avatar = FileField("Avatar", validators=[Optional(), FileAllowed(["jpg", "jpeg", "png"], "Images only!")])
    bio = TextAreaField("Bio", validators=[Optional(), Length(max=1000)])
    submit = SubmitField("Save")

class PlaylistForm(FlaskForm):
    title = StringField("Title", validators=[DataRequired(), Length(max=255)])
    description = TextAreaField("Description", validators=[Optional(), Length(max=1000)])
    submit = SubmitField("Create")

class CommentForm(FlaskForm):
    body = TextAreaField("Comment", validators=[DataRequired(), Length(max=1000)])
    submit = SubmitField("Comment")
