import smtplib
from email.message import EmailMessage
from email.utils import formataddr

from .settings import settings


def send_registration_code(email: str, code: str) -> None:
    if not settings.smtp_host or not settings.smtp_username or not settings.smtp_password:
        raise RuntimeError("SMTP is not configured")

    message = EmailMessage()
    message["From"] = formataddr((settings.smtp_from_name, settings.smtp_username))
    message["To"] = email
    message["Subject"] = "【Nerva】登录验证码"
    message.set_content(f"您的 Nerva 登录验证码是：{code}。验证码 5 分钟内有效，请勿泄露给他人。")
    message.add_alternative(
        f"""<html><body style="font-family:Arial,sans-serif;color:#17231e">
        <h2>登录 Nerva</h2><p>您的登录验证码是：</p>
        <p style="font-size:28px;font-weight:700;letter-spacing:6px;color:#1e684c">{code}</p>
        <p>验证码 5 分钟内有效，请勿泄露给他人。</p></body></html>""",
        subtype="html",
    )

    if settings.smtp_use_ssl:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15) as client:
            client.login(settings.smtp_username, settings.smtp_password)
            client.send_message(message)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as client:
            client.starttls()
            client.login(settings.smtp_username, settings.smtp_password)
            client.send_message(message)
