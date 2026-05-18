from __future__ import annotations

import json
import logging
import mimetypes
import os
import struct
import tempfile
import uuid
import zlib
from datetime import datetime, timezone
from threading import Thread
from urllib import error as urllib_error
from urllib import request as urllib_request

from .connector_endpoints import (
    CONNECTOR_KEY_TELEGRAM,
    ensure_connector_endpoint_tables,
    get_connector_endpoint_config,
)

logger = logging.getLogger(__name__)

TELEGRAM_SEND_TIMEOUT_SECONDS = 10.0
MASKED_BOT_TOKEN_PLACEHOLDER = "********"


def ensure_telegram_subscription_tables() -> None:
    ensure_connector_endpoint_tables()


def _format_telegram_http_error(exc: urllib_error.HTTPError) -> RuntimeError:
    detail = exc.read().decode("utf-8", errors="replace")
    try:
        payload = json.loads(detail)
    except Exception:
        payload = {}
    description = str(payload.get("description") or "").strip()
    if exc.code == 404 and description.lower() == "not found":
        return RuntimeError(
            "telegram request failed: invalid or revoked bot token. "
            "Paste a fresh Bot Token from BotFather and save subscriptions."
        )
    return RuntimeError(f"telegram request failed: HTTP {exc.code} {detail}")


def _normalize_subscription_row(row) -> dict[str, str]:
    config = get_connector_endpoint_config(row)
    return {
        "subscription_label": str(
            getattr(row, "label", None) or getattr(row, "subscription_label", "") or ""
        ).strip(),
        "bot_token": str(config.get("bot_token", None) or getattr(row, "bot_token", "") or "").strip(),
        "chat_id": str(config.get("chat_id", None) or getattr(row, "chat_id", "") or "").strip(),
        "send_media": bool(config.get("send_media", getattr(row, "send_media", False))),
        "media_source": str(config.get("media_source", getattr(row, "media_source", "none")) or "none").strip().lower(),
    }


def build_trigger_notification_text(
    *,
    trigger_id: str,
    trigger_type: str,
    display_title: str,
    run_identifier: str | None = None,
    source_label: str | None = None,
    camera_id: int | None = None,
    alert_level: str | None = None,
    occurred_at: str | None = None,
    metadata: dict | None = None,
) -> str:
    timestamp = occurred_at
    if not timestamp:
        timestamp = datetime.now(timezone.utc).isoformat()
    lines = [
        f"Hearthlight Trigger: {display_title}",
        f"Trigger ID: {trigger_id}",
        f"Type: {trigger_type}",
    ]
    if alert_level:
        lines.append(f"Level: {alert_level}")
    if run_identifier:
        lines.append(f"Run: {run_identifier}")
    if source_label:
        lines.append(f"Source: {source_label}")
    if camera_id is not None:
        lines.append(f"Camera ID: {camera_id}")
    lines.append(f"Time: {timestamp}")
    if metadata:
        for key, value in metadata.items():
            if value is None:
                continue
            label = str(key).replace("_", " ").title()
            lines.append(f"{label}: {value}")
    return "\n".join(lines)


def send_telegram_message(
    *,
    bot_token: str,
    chat_id: str,
    text: str,
    timeout_seconds: float = TELEGRAM_SEND_TIMEOUT_SECONDS,
) -> None:
    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps(
        {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
    ).encode("utf-8")
    request = urllib_request.Request(
        api_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(request, timeout=timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib_error.HTTPError as exc:
        raise _format_telegram_http_error(exc) from exc
    except urllib_error.URLError as exc:
        raise RuntimeError(f"telegram request failed: {exc.reason}") from exc
    except Exception as exc:
        raise RuntimeError("telegram request failed") from exc

    if not body.get("ok", False):
        description = str(body.get("description") or "telegram rejected the message")
        raise RuntimeError(description)


def _build_multipart_form_data(fields: dict[str, str], file_field: str, file_path: str) -> tuple[bytes, str]:
    boundary = f"----hearthlight-{uuid.uuid4().hex}"
    body = bytearray()
    for key, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode("utf-8")
        )
    mime_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    filename = os.path.basename(file_path) or "media"
    with open(file_path, "rb") as media_file:
        media_bytes = media_file.read()
    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(
        (
            f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode("utf-8")
    )
    body.extend(media_bytes)
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))
    return bytes(body), boundary


def _build_solid_png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    def _chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack("!I", len(data))
            + tag
            + data
            + struct.pack("!I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    r, g, b = rgb
    scanline = b"\x00" + bytes([r, g, b]) * width
    raw = scanline * height
    compressed = zlib.compress(raw, level=9)
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = _chunk(b"IHDR", struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0))
    idat = _chunk(b"IDAT", compressed)
    iend = _chunk(b"IEND", b"")
    return signature + ihdr + idat + iend


def send_telegram_photo_message(
    *,
    bot_token: str,
    chat_id: str,
    caption: str,
    photo_path: str,
    timeout_seconds: float = TELEGRAM_SEND_TIMEOUT_SECONDS,
) -> None:
    if not os.path.isfile(photo_path):
        raise RuntimeError(f"photo not found: {photo_path}")
    api_url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    payload, boundary = _build_multipart_form_data(
        {"chat_id": chat_id, "caption": caption},
        "photo",
        photo_path,
    )
    request = urllib_request.Request(
        api_url,
        data=payload,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(request, timeout=timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib_error.HTTPError as exc:
        raise _format_telegram_http_error(exc) from exc
    except urllib_error.URLError as exc:
        raise RuntimeError(f"telegram request failed: {exc.reason}") from exc
    except Exception as exc:
        raise RuntimeError("telegram request failed") from exc
    if not body.get("ok", False):
        description = str(body.get("description") or "telegram rejected the photo")
        raise RuntimeError(description)


def deliver_telegram_trigger_notifications(
    subscription_rows: list,
    *,
    trigger_text: str,
    media: dict | None = None,
) -> list[str]:
    errors: list[str] = []
    for row in subscription_rows:
        normalized = _normalize_subscription_row(row)
        if not normalized["bot_token"] or not normalized["chat_id"]:
            continue
        try:
            use_media = bool(normalized.get("send_media")) and normalized.get("media_source") == "frame_snapshot"
            media_path = str((media or {}).get("frame_snapshot_path") or "").strip()
            if use_media and media_path:
                try:
                    send_telegram_photo_message(
                        bot_token=normalized["bot_token"],
                        chat_id=normalized["chat_id"],
                        caption=trigger_text,
                        photo_path=media_path,
                    )
                except Exception:
                    logger.warning("Telegram photo delivery failed; falling back to text", exc_info=True)
                    send_telegram_message(
                        bot_token=normalized["bot_token"],
                        chat_id=normalized["chat_id"],
                        text=trigger_text,
                    )
            elif use_media and not media_path:
                logger.warning(
                    "Telegram media requested but frame snapshot was unavailable; sending text fallback"
                )
                send_telegram_message(
                    bot_token=normalized["bot_token"],
                    chat_id=normalized["chat_id"],
                    text=f"{trigger_text}\n\nMedia: unavailable (no frame snapshot found).",
                )
            else:
                send_telegram_message(
                    bot_token=normalized["bot_token"],
                    chat_id=normalized["chat_id"],
                    text=trigger_text,
                )
        except Exception as exc:
            label = normalized["subscription_label"] or normalized["chat_id"]
            message = f"{label}: {exc}"
            logger.warning("Failed to deliver Telegram trigger notification: %s", message)
            errors.append(message)
    return errors


def queue_telegram_trigger_notifications(
    subscription_rows: list,
    *,
    trigger_text: str,
    media: dict | None = None,
) -> None:
    if not subscription_rows:
        return

    def worker() -> None:
        try:
            deliver_telegram_trigger_notifications(
                subscription_rows,
                trigger_text=trigger_text,
                media=media,
            )
        except Exception:
            logger.exception("Failed to dispatch Telegram trigger notifications")

    Thread(
        target=worker,
        daemon=True,
        name="telegram-trigger-notifier",
    ).start()


def send_test_telegram_trigger_message(subscription_row) -> None:
    normalized = _normalize_subscription_row(subscription_row)
    if normalized["bot_token"] == MASKED_BOT_TOKEN_PLACEHOLDER:
        raise RuntimeError(
            "Bot token is masked. Paste the full token, save subscriptions, then retry test."
        )
    text = build_trigger_notification_text(
        trigger_id="TEST-TRIGGER",
        trigger_type="ALERT",
        display_title="Test Trigger",
        source_label="Test Source",
        alert_level="Medium",
        metadata={"purpose": "telegram subscription test"},
    )
    use_media = bool(normalized.get("send_media")) and normalized.get("media_source") == "frame_snapshot"
    if not use_media:
        send_telegram_message(
            bot_token=normalized["bot_token"],
            chat_id=normalized["chat_id"],
            text=text,
        )
        return
    # Generate a valid 640x360 PNG for Telegram media test.
    png_bytes = _build_solid_png(640, 360, (11, 61, 46))
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=".png",
            prefix="hearthlight-telegram-test-",
            delete=False,
        ) as tmp_file:
            tmp_file.write(png_bytes)
            tmp_path = tmp_file.name
        send_telegram_photo_message(
            bot_token=normalized["bot_token"],
            chat_id=normalized["chat_id"],
            caption=text,
            photo_path=tmp_path,
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                logger.debug("Failed to remove temp telegram test image: %s", tmp_path)
