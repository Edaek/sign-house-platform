"""Send Media Pool classify prompts with the user's photo when native quote fails."""
import base64
import io
import logging
import os

from flask import current_app

logger = logging.getLogger(__name__)

MAX_SEND_BYTES = 900_000


def _resolve_pool_image_path(image_path: str) -> str | None:
    if not image_path:
        return None
    uploads_root = os.path.dirname(
        current_app.config.get('WA_UPLOADS_FOLDER', 'uploads/wa-media'),
    )
    local = str(image_path).lstrip('/')
    if local.startswith('uploads/'):
        local = local[len('uploads/') :]
    fpath = os.path.join(uploads_root, local)
    return fpath if os.path.isfile(fpath) else None


def pool_image_data_uri(image_path: str) -> str | None:
    """JPEG data URI for Wakka send-media (same chat as classify nudge)."""
    fpath = _resolve_pool_image_path(image_path)
    if not fpath:
        return None
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:
        logger.warning('[PoolNudge] Pillow not installed; cannot resend pool image')
        return None
    try:
        with Image.open(fpath) as pil:
            img = pil.convert('RGB')
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        logger.warning('[PoolNudge] Invalid pool image %s: %s', fpath, exc)
        return None

    img.thumbnail((1280, 1280))
    quality = 85
    while quality >= 50:
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=quality, optimize=True)
        raw = buf.getvalue()
        if len(raw) <= MAX_SEND_BYTES:
            return f'data:image/jpeg;base64,{base64.b64encode(raw).decode()}'
        quality -= 10
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=50, optimize=True)
    return f'data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()}'


def send_private_classify_nudge(
    phone,
    text,
    *,
    quote_msg_id=None,
    image_path=None,
    quoted_payload=None,
):
    """Prefer quoting the user's media; fall back to resending that image with caption."""
    from app.services.wa_classify_mode import wa_inbound_loomy_dispatch_enabled

    if wa_inbound_loomy_dispatch_enabled():
        logger.debug('[PoolNudge] Skipped — Loomy agent handles classify prompts')
        return None

    from app.services.wa_send_service import send_media, send_message, wakka_private_recipient

    recipient = wakka_private_recipient(phone)

    # Private /send-media currently errors on Wakka; reply must quote the user's message id.
    return send_message(
        recipient,
        text,
        quoted_msg_id=quote_msg_id,
        quoted_payload=quoted_payload,
    )
