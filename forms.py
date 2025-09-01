
from flask_wtf import FlaskForm
from wtforms import (
    StringField,
    PasswordField,
    SubmitField,
    BooleanField,
    DateTimeLocalField,
    TextAreaField,
    SelectField,
    SelectMultipleField,
)
from wtforms.validators import DataRequired, Email, Length, EqualTo
from wtforms.widgets import CheckboxInput, ListWidget
from models import User

class MultiCheckboxField(SelectMultipleField):
    widget = ListWidget(prefix_label=False)
    option_widget = CheckboxInput()

class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Mot de passe", validators=[DataRequired()])
    submit = SubmitField("Se connecter")


class FirstLoginForm(FlaskForm):
    first_name = StringField("Prénom", validators=[DataRequired(), Length(max=60)])
    last_name = StringField("Nom", validators=[DataRequired(), Length(max=60)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField(
        "Mot de passe", validators=[DataRequired(), Length(min=8)]
    )
    password2 = PasswordField(
        "Confirmer le mot de passe",
        validators=[DataRequired(), EqualTo("password", message="Les mots de passe doivent correspondre."), Length(min=8)],
    )
    submit = SubmitField("Créer mon compte")


class RegisterForm(FlaskForm):
    first_name = StringField("Prénom", validators=[DataRequired(), Length(max=60)])
    last_name = StringField("Nom", validators=[DataRequired(), Length(max=60)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField(
        "Mot de passe", validators=[DataRequired(), Length(min=8)]
    )
    password2 = PasswordField(
        "Confirmer le mot de passe",
        validators=[
            DataRequired(),
            EqualTo(
                "password",
                message="Les mots de passe doivent correspondre.",
            ),
        ],
    )
    team_code = StringField("Code d'équipe", validators=[DataRequired(), Length(max=60)])
    submit = SubmitField("Créer mon compte")

class NewRequestForm(FlaskForm):
    first_name = StringField("Prénom", validators=[DataRequired(), Length(max=60)])
    last_name = StringField("Nom", validators=[DataRequired(), Length(max=60)])
    start_at = DateTimeLocalField("Début", format="%Y-%m-%dT%H:%M", validators=[DataRequired()])
    end_at = DateTimeLocalField("Fin", format="%Y-%m-%dT%H:%M", validators=[DataRequired()])
    purpose = StringField("Motif", validators=[Length(max=200)])
    carpool = BooleanField("Covoiturage")
    carpool_with = StringField("Avec qui")
    notes = TextAreaField("Précisions", validators=[Length(max=1000)])
    submit = SubmitField("Envoyer la demande")


class UserForm(FlaskForm):
    first_name = StringField("Prénom", validators=[DataRequired(), Length(max=60)])
    last_name = StringField("Nom", validators=[DataRequired(), Length(max=60)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=120)])
    role = SelectField(
        "Rôle",
        choices=[
            (User.ROLE_USER, "user"),
            (User.ROLE_ADMIN, "admin"),
            (User.ROLE_SUPERADMIN, "superadmin"),
        ],
    )
    submit = SubmitField("Enregistrer")


class NotificationSettingsForm(FlaskForm):
    recipients = MultiCheckboxField("Notifier", choices=[])
    submit = SubmitField("Enregistrer")
