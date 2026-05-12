from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from threading import Thread
from urllib import error as urllib_error
from urllib import request as urllib_request

from ..database.database import get_engine
from ..models import SQLModels

logger = logging.getLogger(__name__)

TELEGRAM_SEND_TIMEOUT_SECONDS = 10.0


def ensure_telegram_subscription_tables() -> None:
    engine = get_engine()
    SQLModels.Base.metadata.create_all(
        bind=engine,
        tables=[SQLModels.TelegramTriggerSubscription.__table__],
        checkfirst=True,
    )


def _normalize_subscription_row(row) -> dict[str, str]:
    return {
        "subscription_label": str(getattr(row, "subscription_label", "") or "").strip(),
        "bot_token": str(getattr(row, "bot_token", "") or "").strip(),
        "chat_id": str(getattr(row, "chat_id", "") or "").strip(),
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
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"telegram request failed: HTTP {exc.code} {detail}") from exc
    except urllib_error.URLError as exc:
        raise RuntimeError(f"telegram request failed: {exc.reason}") from exc
    except Exception as exc:
        raise RuntimeError("telegram request failed") from exc

    if not body.get("ok", False):
        description = str(body.get("description") or "telegram rejected the message")
        raise RuntimeError(description)


def deliver_telegram_trigger_notifications(
    subscription_rows: list,
    *,
    trigger_text: str,
) -> list[str]:
    errors: list[str] = []
    for row in subscription_rows:
        normalized = _normalize_subscription_row(row)
        if not normalized["bot_token"] or not normalized["chat_id"]:
            continue
        try:
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
) -> None:
    if not subscription_rows:
        return

    def worker() -> None:
        try:
            deliver_telegram_trigger_notifications(
                subscription_rows,
                trigger_text=trigger_text,
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
    send_telegram_message(
        bot_token=normalized["bot_token"],
        chat_id=normalized["chat_id"],
        text=build_trigger_notification_text(
            trigger_id="TEST-TRIGGER",
            trigger_type="ALERT",
            display_title="Test Trigger",
            source_label="Test Source",
            alert_level="Medium",
            metadata={"purpose": "telegram subscription test"},
        ),
    )
