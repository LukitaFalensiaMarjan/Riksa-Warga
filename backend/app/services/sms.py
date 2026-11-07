"""Pengiriman SMS lewat adaptor penyedia (PRD §7.3, D-03).

Mode (SMS_MODE):
- mock   : tidak mengirim, hanya dicatat (status "mock") — default aman untuk demo.
- twilio : Twilio Programmable Messaging (REST). Perlu TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, dan
           TWILIO_FROM (nomor pengirim) atau TWILIO_MESSAGING_SERVICE_SID.

SMS berbayar dan hanya untuk peristiwa berat: pemanggil menentukan lewat Alert.sms. Pembatas per nomor per
jam ada di notifier. Nomor tidak pernah ditulis ke log selain bentuk yang disamarkan.
"""
import logging
import re

import httpx

from app.config import settings
from app.models import DeliveryStatus

log = logging.getLogger("riksa.sms")
TWILIO_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
SMS_MAX_CHARS = 300  # ~2 segmen; pesan lebih panjang dipotong agar biaya tidak membengkak


def normalize_phone(raw: str | None) -> str | None:
    """08xxxxxxxxxx / 628xx / +628xx -> +628xx. Nomor yang tidak masuk akal -> None."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("0"):
        digits = "62" + digits[1:]
    elif digits.startswith("8"):
        digits = "62" + digits
    if not digits.startswith("62") or not 10 <= len(digits) <= 15:
        return None
    return "+" + digits


def mask_phone(e164: str) -> str:
    return f"{e164[:5]}****{e164[-3:]}" if len(e164) > 8 else "****"


def short_text(message: str) -> str:
    """Ringkas pesan alert untuk SMS: judul + baris penting, tanpa data pribadi."""
    lines = [ln.strip() for ln in message.splitlines() if ln.strip()]
    keep = [lines[0]] if lines else []
    for ln in lines[1:]:
        if ln.startswith(("Status:", "Tindakan:", "Alasan:", "Wilayah:")):
            keep.append(ln)
    text = " | ".join(keep) or message
    return text if len(text) <= SMS_MAX_CHARS else text[: SMS_MAX_CHARS - 1] + "…"


def send_sms(phone_e164: str, text: str) -> tuple[DeliveryStatus, str | None]:
    if settings.sms_mode == "mock":
        return DeliveryStatus.MOCK, None
    if settings.sms_mode == "twilio":
        if not (settings.twilio_account_sid and settings.twilio_auth_token
                and (settings.twilio_from or settings.twilio_messaging_service_sid)):
            return DeliveryStatus.GAGAL, "Kredensial Twilio belum lengkap di .env"
        data = {"To": phone_e164, "Body": text}
        if settings.twilio_messaging_service_sid:
            data["MessagingServiceSid"] = settings.twilio_messaging_service_sid
        else:
            data["From"] = settings.twilio_from
        try:
            r = httpx.post(TWILIO_URL.format(sid=settings.twilio_account_sid), data=data, timeout=15,
                           auth=(settings.twilio_account_sid, settings.twilio_auth_token))
            if r.status_code in (200, 201):
                return DeliveryStatus.TERKIRIM, None
            try:
                body = r.json()
                reason = f"{body.get('code', '')} {body.get('message', '')}".strip()
            except ValueError:
                reason = ""
            return DeliveryStatus.GAGAL, f"HTTP {r.status_code} {reason}"[:255]
        except httpx.HTTPError as e:
            # jangan simpan str(e): bisa memuat kredensial/URL
            return DeliveryStatus.GAGAL, type(e).__name__
    return DeliveryStatus.GAGAL, f"SMS_MODE tidak dikenal: {settings.sms_mode}"
