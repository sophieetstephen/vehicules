from email.message import EmailMessage
import subprocess

def send_mail_msmtp(subject: str, body: str, to_addrs, sender: str = "gestionvehiculestomer@gmail.com", profile: str = "gmail"):
    """
    Envoie un email en passant par msmtp (profil donné).
    - subject : sujet
    - body    : texte (plain text)
    - to_addrs: str ou liste de destinataires
    - sender  : expéditeur (doit correspondre au compte msmtp)
    """
    if isinstance(to_addrs, str):
        to_list = [to_addrs]
    else:
        to_list = list(to_addrs)

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"]   = ", ".join(to_list)
    msg["Subject"] = subject
    msg.set_content(body)

    # Appelle msmtp en mode "sendmail-like"
    # -a <profile> : utilise le compte "gmail" défini dans /etc/msmtprc
    try:
        proc = subprocess.run(
            ["/usr/bin/msmtp", "-a", profile, *to_list],
            input=msg.as_bytes(),
            check=True
        )
        return True, "sent"
    except subprocess.CalledProcessError as e:
        return False, f"msmtp error: {e}"
