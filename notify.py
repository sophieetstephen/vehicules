from email.message import EmailMessage
import smtplib
from config import Config

def send_mail_msmtp(subject: str, body: str, to_addrs, sender: str = "", profile: str = "gmail"):
    """Send an email using Gmail's SMTP service.

    The signature mirrors the previous msmtp-based helper to avoid breaking
    existing calls or tests. The ``profile`` argument is kept for backward
    compatibility but ignored.
    """

    if isinstance(to_addrs, str):
        to_list = [to_addrs]
    else:
        to_list = list(to_addrs)

    # L'adresse d'expediteur etait ecrite en dur alors que l'identifiant de
    # connexion vient du .env : changer de compte Gmail sans toucher a cette
    # ligne aurait fait refuser tous les envois.
    expediteur = (sender or Config.MAIL_DEFAULT_SENDER or Config.MAIL_USERNAME
                  or "gestionvehiculestomer@gmail.com")

    msg = EmailMessage()
    msg["From"] = expediteur
    msg["To"] = ", ".join(to_list)
    msg["Subject"] = subject
    msg.set_content(body)

    server = Config.MAIL_SERVER or "smtp.gmail.com"
    port = Config.MAIL_PORT or (465 if not Config.MAIL_USE_TLS else 587)

    try:
        if Config.MAIL_USE_TLS:
            with smtplib.SMTP(server, port) as smtp:
                smtp.starttls()
                smtp.login(Config.MAIL_USERNAME, Config.MAIL_PASSWORD)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP_SSL(server, port) as smtp:
                smtp.login(Config.MAIL_USERNAME, Config.MAIL_PASSWORD)
                smtp.send_message(msg)
        return True, "sent"
    except Exception as e:
        return False, f"smtp error: {e}"


def check_mail_login(timeout: int = 6):
    """Vérifier que le compte d'envoi est toujours accepté, sans rien envoyer.

    On se connecte et on s'authentifie, puis on referme. C'est exactement ce
    qui échoue quand Google révoque une clé d'application, et personne ne
    reçoit de message inutile.

    Le délai est court : ce contrôle a lieu pendant l'affichage de l'accueil
    d'un administrateur, qui ne doit pas rester bloqué sur un serveur muet.

    Retourne ``(ok, détail)``.
    """

    server = Config.MAIL_SERVER or "smtp.gmail.com"
    port = Config.MAIL_PORT or (465 if not Config.MAIL_USE_TLS else 587)

    try:
        if Config.MAIL_USE_TLS:
            with smtplib.SMTP(server, port, timeout=timeout) as smtp:
                smtp.starttls()
                smtp.login(Config.MAIL_USERNAME, Config.MAIL_PASSWORD)
        else:
            with smtplib.SMTP_SSL(server, port, timeout=timeout) as smtp:
                smtp.login(Config.MAIL_USERNAME, Config.MAIL_PASSWORD)
        return True, "login ok"
    except Exception as e:
        return False, f"smtp error: {e}"
