"""Persistent, consent-based email follow-up queue for Namma Illam."""

from __future__ import annotations

from datetime import datetime, timedelta
from contextlib import contextmanager
from email.message import EmailMessage
from pathlib import Path
import smtplib
import sqlite3
import ssl
from typing import Any
from uuid import uuid4
from urllib.parse import urlparse

from agent_runtime import INDIA_TZ


ROOT = Path(__file__).resolve().parent
FOLLOWUP_DB = ROOT / "data" / "private" / "followups.sqlite3"


@contextmanager
def _connect(db_path: Path = FOLLOWUP_DB):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS email_followups (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            recipient_email TEXT NOT NULL,
            customer_name TEXT NOT NULL DEFAULT '',
            preference_summary TEXT NOT NULL,
            started_at TEXT NOT NULL,
            next_send_at TEXT NOT NULL,
            cadence_days INTEGER NOT NULL,
            max_messages INTEGER NOT NULL,
            sent_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'scheduled',
            opted_in_at TEXT NOT NULL,
            last_error TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        )
    """)
    connection.commit()
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def next_three_day_boundary(started_at: datetime, now: datetime | None = None) -> datetime:
    """Return the next future 3-day boundary anchored to chat start."""
    now = (now or datetime.now(INDIA_TZ)).astimezone(INDIA_TZ)
    started_at = started_at.astimezone(INDIA_TZ)
    elapsed = max((now - started_at).total_seconds(), 0)
    periods_elapsed = int(elapsed // timedelta(days=3).total_seconds())
    return started_at + timedelta(days=(periods_elapsed + 1) * 3)


def schedule_email_followup(
    *, user_id: str, conversation_id: str, recipient_email: str,
    customer_name: str, preference_summary: str, started_at: datetime,
    max_messages: int = 3, db_path: Path = FOLLOWUP_DB,
    initial_status: str = "scheduled",
) -> str:
    """Save a user-opted-in sequence, optionally as a non-delivery draft."""
    if initial_status not in {"scheduled", "saved_pending_activation"}:
        raise ValueError("Unsupported follow-up status")
    now = datetime.now(INDIA_TZ)
    schedule_id = uuid4().hex
    next_send = next_three_day_boundary(started_at, now)
    with _connect(db_path) as connection:
        connection.execute("""
            INSERT INTO email_followups
            (id,user_id,conversation_id,recipient_email,customer_name,preference_summary,
             started_at,next_send_at,cadence_days,max_messages,opted_in_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            schedule_id, user_id, conversation_id, recipient_email.strip().lower(),
            customer_name.strip()[:100], preference_summary.strip()[:500],
            started_at.astimezone(INDIA_TZ).isoformat(timespec="seconds"),
            next_send.isoformat(timespec="seconds"), 3, max_messages,
            now.isoformat(timespec="seconds"), now.isoformat(timespec="seconds"),
        ))
        if initial_status != "scheduled":
            connection.execute(
                "UPDATE email_followups SET status=?, updated_at=? WHERE id=?",
                (initial_status, now.isoformat(timespec="seconds"), schedule_id),
            )
    return schedule_id


def list_email_followups(user_id: str, db_path: Path = FOLLOWUP_DB) -> list[dict[str, Any]]:
    with _connect(db_path) as connection:
        rows = connection.execute(
            "SELECT id, recipient_email, preference_summary, next_send_at, sent_count, max_messages, status FROM email_followups WHERE user_id=? ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def cancel_email_followup(schedule_id: str, user_id: str, db_path: Path = FOLLOWUP_DB) -> bool:
    now = datetime.now(INDIA_TZ).isoformat(timespec="seconds")
    with _connect(db_path) as connection:
        row = connection.execute("SELECT conversation_id FROM email_followups WHERE id=? AND user_id=?", (schedule_id, user_id)).fetchone()
        cursor = connection.execute(
            "UPDATE email_followups SET status='cancelled', updated_at=? WHERE id=? AND user_id=? AND status IN ('scheduled','sending')",
            (now, schedule_id, user_id),
        )
        cancelled = cursor.rowcount > 0
    if cancelled and row:
        from inquiry_log import update_conversation_fields
        update_conversation_fields(str(row["conversation_id"]), {"Follow-up schedule status": "Stopped by user", "Next follow-up time (Asia/Kolkata)": ""})
    return cancelled


def cancel_user_followups(user_id: str, db_path: Path = FOLLOWUP_DB) -> int:
    now = datetime.now(INDIA_TZ).isoformat(timespec="seconds")
    with _connect(db_path) as connection:
        rows = connection.execute("SELECT DISTINCT conversation_id FROM email_followups WHERE user_id=? AND status IN ('scheduled','sending')", (user_id,)).fetchall()
        cursor = connection.execute(
            "UPDATE email_followups SET status='cancelled', updated_at=? WHERE user_id=? AND status IN ('scheduled','sending')",
            (now, user_id),
        )
        cancelled = cursor.rowcount
    if cancelled:
        from inquiry_log import update_conversation_fields
        for row in rows:
            update_conversation_fields(str(row["conversation_id"]), {"Follow-up schedule status": "Stopped after user returned", "Next follow-up time (Asia/Kolkata)": ""})
    return cancelled


def cancel_followup_from_link(token: str, db_path: Path = FOLLOWUP_DB) -> bool:
    """Cancel a schedule using the unguessable id embedded in its stop link."""
    if not token or not all(ch in "0123456789abcdef" for ch in token.lower()) or len(token) != 32:
        return False
    now = datetime.now(INDIA_TZ).isoformat(timespec="seconds")
    with _connect(db_path) as connection:
        row = connection.execute("SELECT conversation_id FROM email_followups WHERE id=?", (token,)).fetchone()
        cursor = connection.execute(
            "UPDATE email_followups SET status='cancelled', updated_at=? WHERE id=? AND status IN ('scheduled','sending')",
            (now, token),
        )
        cancelled = cursor.rowcount > 0
    if cancelled and row:
        from inquiry_log import update_conversation_fields
        update_conversation_fields(str(row["conversation_id"]), {"Follow-up schedule status": "Stopped from email link", "Next follow-up time (Asia/Kolkata)": ""})
    return cancelled


def email_config_ready(config: dict[str, str]) -> bool:
    return not email_config_issues(config)


def email_config_issues(config: dict[str, str]) -> list[str]:
    """Report setup problems without exposing credentials or contact details."""
    issues = []
    for key in ("FOLLOWUP_SMTP_HOST", "FOLLOWUP_SMTP_USERNAME", "FOLLOWUP_SMTP_PASSWORD", "FOLLOWUP_SMTP_FROM", "FOLLOWUP_PUBLIC_URL"):
        if not config.get(key, "").strip():
            issues.append(f"Missing {key}")
    try:
        port = int(config.get("FOLLOWUP_SMTP_PORT") or "587")
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        issues.append("FOLLOWUP_SMTP_PORT must be a valid port number (usually 587 or 465)")
    if config.get("FOLLOWUP_PUBLIC_URL", "").strip():
        parsed = urlparse(config["FOLLOWUP_PUBLIC_URL"])
        if not parsed.hostname or parsed.scheme not in {"http", "https"} or parsed.hostname.casefold() in {"localhost", "127.0.0.1", "::1"}:
            issues.append("FOLLOWUP_PUBLIC_URL must be a reachable shared website URL for the stop-email link; localhost cannot serve recipients")
    return issues


def send_due_followups(config: dict[str, str], db_path: Path = FOLLOWUP_DB) -> tuple[int, int]:
    """Send due opt-in emails. Intended for a once-daily OS/deployment scheduler."""
    if email_config_issues(config):
        raise RuntimeError("Email follow-ups need SMTP settings and FOLLOWUP_PUBLIC_URL.")
    now = datetime.now(INDIA_TZ)
    with _connect(db_path) as connection:
        stale_before = (now - timedelta(hours=1)).isoformat(timespec="seconds")
        connection.execute(
            "UPDATE email_followups SET status='scheduled', updated_at=? WHERE status='sending' AND updated_at<?",
            (now.isoformat(timespec="seconds"), stale_before),
        )
        due = connection.execute(
            "SELECT * FROM email_followups WHERE status='scheduled' AND next_send_at<=? ORDER BY next_send_at",
            (now.isoformat(timespec="seconds"),),
        ).fetchall()
    sent = failed = 0
    for row in due:
        schedule_id = row["id"]
        with _connect(db_path) as connection:
            claimed = connection.execute(
                "UPDATE email_followups SET status='sending', updated_at=? WHERE id=? AND status='scheduled'",
                (now.isoformat(timespec="seconds"), schedule_id),
            )
            if claimed.rowcount != 1:
                continue
        recipient = row["recipient_email"]
        token = schedule_id
        unsubscribe_url = f"{config['FOLLOWUP_PUBLIC_URL'].rstrip('/')}?stop_followup={token}"
        name = row["customer_name"].strip()
        greeting = f"Hi {name}," if name else "Hi," 
        summary = row["preference_summary"].strip()
        summary_text = f"\nYou asked us to follow up about: {summary}\n" if summary else ""
        message = EmailMessage()
        message["Subject"] = "A quick check-in from Namma Illam"
        message["From"] = config["FOLLOWUP_SMTP_FROM"]
        message["To"] = recipient
        message.set_content(
            f"{greeting}\n\nJust checking in from Namma Illam. Would you like to continue exploring your property options?{summary_text}\nThere is no pressure to reply. This is an AI-guided property portal, and this message does not confirm listing availability or loan terms.\n\nTo stop these follow-up emails, use this link: {unsubscribe_url}\n\nNamma Illam"
        )
        try:
            port = int(config.get("FOLLOWUP_SMTP_PORT") or "587")
            if port == 465:
                with smtplib.SMTP_SSL(config["FOLLOWUP_SMTP_HOST"], port, context=ssl.create_default_context(), timeout=30) as smtp:
                    smtp.login(config["FOLLOWUP_SMTP_USERNAME"], config["FOLLOWUP_SMTP_PASSWORD"])
                    smtp.send_message(message)
            else:
                with smtplib.SMTP(config["FOLLOWUP_SMTP_HOST"], port, timeout=30) as smtp:
                    smtp.starttls(context=ssl.create_default_context())
                    smtp.login(config["FOLLOWUP_SMTP_USERNAME"], config["FOLLOWUP_SMTP_PASSWORD"])
                    smtp.send_message(message)
            new_count = int(row["sent_count"]) + 1
            status = "complete" if new_count >= int(row["max_messages"]) else "scheduled"
            # A delayed worker must not send missed messages on consecutive runs.
            next_send = max(
                datetime.fromisoformat(row["next_send_at"]), now,
            ) + timedelta(days=int(row["cadence_days"]))
            with _connect(db_path) as connection:
                connection.execute(
                    "UPDATE email_followups SET sent_count=?, status=?, next_send_at=?, last_error='', updated_at=? WHERE id=? AND status='sending'",
                    (new_count, status, next_send.isoformat(timespec="seconds"), now.isoformat(timespec="seconds"), schedule_id),
                )
            from inquiry_log import update_conversation_fields
            update_conversation_fields(str(row["conversation_id"]), {
                "Follow-up schedule status": "Complete" if status == "complete" else "Scheduled",
                "Next follow-up time (Asia/Kolkata)": "" if status == "complete" else next_send.isoformat(timespec="seconds"),
            })
            sent += 1
        except Exception as error:
            with _connect(db_path) as connection:
                connection.execute(
                    "UPDATE email_followups SET status='scheduled', last_error=?, updated_at=? WHERE id=? AND status='sending'",
                    (str(error)[:500], now.isoformat(timespec="seconds"), schedule_id),
                )
            failed += 1
    return sent, failed
