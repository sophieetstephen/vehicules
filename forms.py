
from flask_wtf import FlaskForm
from wtforms import (
    StringField,
    PasswordField,
    SubmitField,
    BooleanField,
    DateField,
    TextAreaField,
    SelectField,
    SelectMultipleField,
    HiddenField,
)
from wtforms.validators import DataRequired, Email, Length, EqualTo, Optional
from wtforms.widgets import CheckboxInput, ListWidget
from models import User

class MultiCheckboxField(SelectMultipleField):
    widget = ListWidget(prefix_label=False)
    option_widget = CheckboxInput()

class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Mot de passe", validators=[DataRequired()])
    submit = SubmitField("Se connecter")


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
    submit = SubmitField("Créer mon compte")


class ResetPasswordForm(FlaskForm):
    password = PasswordField(
        "Nouveau mot de passe", validators=[DataRequired(), Length(min=8)]
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
    submit = SubmitField("Enregistrer")

class NewRequestForm(FlaskForm):
    first_name = StringField("Prénom", validators=[DataRequired(), Length(max=60)])
    last_name = StringField("Nom", validators=[DataRequired(), Length(max=60)])
    user_lookup = StringField(
        "Réserver pour",
        validators=[Optional(), Length(max=120)],
        render_kw={"autocomplete": "off"},
    )
    user_id = HiddenField(validators=[Optional()])
    start_date = DateField("Date début", format="%Y-%m-%d", validators=[DataRequired()])
    start_slot = SelectField(
        "Créneau début",
        choices=[
            ("morning", "Matin"),
            ("afternoon", "Après-midi"),
            ("day", "Journée"),
        ],
        validators=[DataRequired()],
    )
    end_date = DateField(
        "Date fin (si plusieurs jours)",
        format="%Y-%m-%d",
        validators=[Optional()],
        render_kw={"required": False},
    )
    end_slot = SelectField(
        "Créneau fin",
        choices=[
            ("", "—"),
            ("morning", "Matin"),
            ("afternoon", "Après-midi"),
            ("day", "Journée"),
        ],
        default="",
        validators=[Optional()],
    )
    purpose = StringField("Motif", validators=[Length(max=200)])
    carpool = BooleanField("Covoiturage")
    carpool_with = StringField("Avec qui")
    carpool_with_ids = HiddenField()
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


class ContactForm(FlaskForm):
    message = TextAreaField("Message", validators=[DataRequired(), Length(max=1000)])
    submit = SubmitField("Envoyer")
