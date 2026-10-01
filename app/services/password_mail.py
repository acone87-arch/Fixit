"""Minimal reset-email delivery. Raw reset URLs are never logged."""
from email.message import EmailMessage
import smtplib

from fastapi.concurrency import run_in_threadpool

from app.config import settings


def configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_from)


def _send(recipient: str, reset_url: str) -> None:
    message = EmailMessage()
    message["Subject"] = "Восстановление доступа к Fixit Pulse"
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message.set_content(
        "Для смены пароля откройте одноразовую ссылку:\n\n"
        f"{reset_url}\n\n"
        f"Ссылка действует {settings.password_reset_expire_minutes} минут. "
        "Если вы не запрашивали восстановление, ничего не делайте."
    )
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as client:
        if settings.smtp_starttls:
            client.starttls()
        if settings.smtp_username:
            client.login(settings.smtp_username, settings.smtp_password or "")
        client.send_message(message)


async def send_password_reset(recipient: str, reset_url: str) -> bool:
    if not configured():
        return False
    await run_in_threadpool(_send, recipient, reset_url)
    return True
