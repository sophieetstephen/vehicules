from email.message import EmailMessage
import smtplib
from config import Config

def send_mail_msmtp(subject: str, body: str, to_addrs, sender: str = "gestionvehiculestomer@gmail.com", profile: str = "gmail"):
    """Send an email using Gmail's SMTP service.

    The signature mirrors the previous msmtp-based helper to avoid breaking
    existing calls or tests. The ``profile`` argument is kept for backward
    compatibility but ignored.
    """

    if isinstance(to_addrs, str):
        to_list = [to_addrs]
    else:
        to_list = list(to_addrs)

    msg = EmailMessage()
    msg["From"] = sender
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
