from __future__ import annotations

import logging
import platform
import subprocess
from threading import Thread

from ..database.database import get_engine
from ..models import SQLModels
from .telegram_notifications import build_trigger_notification_text

logger = logging.getLogger(__name__)

APPLE_MESSAGES_SEND_TIMEOUT_SECONDS = 20.0
APPLE_MESSAGES_SUPPORTED_SERVICES = {"iMessage", "SMS"}


def ensure_apple_message_subscription_tables() -> None:
    engine = get_engine()
    SQLModels.Base.metadata.create_all(
        bind=engine,
        tables=[SQLModels.AppleMessageTriggerSubscription.__table__],
        checkfirst=True,
    )


def _normalize_subscription_row(row) -> dict[str, str]:
    service = str(getattr(row, "service", "iMessage") or "iMessage").strip() or "iMessage"
    if service not in APPLE_MESSAGES_SUPPORTED_SERVICES:
        service = "iMessage"
    return {
        "subscription_label": str(getattr(row, "subscription_label", "") or "").strip(),
        "recipient_handle": str(getattr(row, "recipient_handle", "") or "").strip(),
        "service": service,
    }


def send_apple_message(
    *,
    recipient_handle: str,
    text: str,
    service: str = "iMessage",
    timeout_seconds: float = APPLE_MESSAGES_SEND_TIMEOUT_SECONDS,
) -> None:
    if platform.system() != "Darwin":
        raise RuntimeError("Apple Messages delivery is only supported on macOS hosts")
    if service not in APPLE_MESSAGES_SUPPORTED_SERVICES:
        raise RuntimeError("Apple Messages service must be iMessage or SMS")

    script = """
on run argv
    set recipientHandle to item 1 of argv
    set messageText to item 2 of argv
    set serviceName to item 3 of argv
    tell application "Messages"
        if serviceName is "SMS" then
            set targetService to first service whose service type = SMS
        else
            set targetService to first service whose service type = iMessage
        end if
        set targetBuddy to buddy recipientHandle of targetService
        send messageText to targetBuddy
    end tell
end run
""".strip()
    try:
        subprocess.run(
            ["osascript", "-e", script, recipient_handle, text, service],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("osascript is unavailable on this host") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Apple Messages request timed out") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(detail or "Apple Messages rejected the message") from exc
    except Exception as exc:
        raise RuntimeError("Apple Messages request failed") from exc


def deliver_apple_message_trigger_notifications(
    subscription_rows: list,
    *,
    trigger_text: str,
) -> list[str]:
    errors: list[str] = []
    for row in subscription_rows:
        normalized = _normalize_subscription_row(row)
        if not normalized["recipient_handle"]:
            continue
        try:
            send_apple_message(
                recipient_handle=normalized["recipient_handle"],
                text=trigger_text,
                service=normalized["service"],
            )
        except Exception as exc:
            label = normalized["subscription_label"] or normalized["recipient_handle"]
            message = f"{label}: {exc}"
            logger.warning("Failed to deliver Apple Messages trigger notification: %s", message)
            errors.append(message)
    return errors


def queue_apple_message_trigger_notifications(
    subscription_rows: list,
    *,
    trigger_text: str,
) -> None:
    if not subscription_rows:
        return

    def worker() -> None:
        try:
            deliver_apple_message_trigger_notifications(
                subscription_rows,
                trigger_text=trigger_text,
            )
        except Exception:
            logger.exception("Failed to dispatch Apple Messages trigger notifications")

    Thread(
        target=worker,
        daemon=True,
        name="apple-message-trigger-notifier",
    ).start()


def send_test_apple_message_trigger_message(subscription_row) -> None:
    normalized = _normalize_subscription_row(subscription_row)
    send_apple_message(
        recipient_handle=normalized["recipient_handle"],
        service=normalized["service"],
        text=build_trigger_notification_text(
            trigger_id="TEST-TRIGGER",
            trigger_type="ALERT",
            display_title="Test Trigger",
            source_label="Test Source",
            alert_level="Medium",
            metadata={"purpose": "apple messages subscription test"},
        ),
    )
