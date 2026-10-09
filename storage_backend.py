"""Shared persistent storage; local files are used only when unconfigured.

The hosted app can use PostgreSQL (for example a Supabase database) when a
``DATABASE_URL`` secret is configured.  Development and unconfigured hosted
instances continue to use the existing private workbook/JSON files.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)
_imported_local_databases: set[str] = set()
_AADHAAR_PATTERN = re.compile(r"(?<![\w-])(?:\d[\s-]?){11}\d(?![\w-])")
_PAN_PATTERN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b", re.IGNORECASE)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _PAN_PATTERN.sub("[PAN redacted]", _AADHAAR_PATTERN.sub("[Aadhaar redacted]", value))
    return value


def _database_url() -> str:
    value = os.getenv("DATABASE_URL", "").strip()
    if value:
        return value
    try:
        import streamlit as st

        value = str(st.secrets.get("DATABASE_URL", "") or "").strip()
    except Exception:
        value = ""
    return value


def is_configured() -> bool:
    """Return whether a database URL and the optional driver are available."""
    if not _database_url():
        return False
    try:
        import psycopg  # noqa: F401
    except ImportError:
        log.warning("DATABASE_URL is set but psycopg is not installed; using local storage")
        return False
    return True


def mode() -> str:
    return "postgresql" if is_configured() else "local files"


def _connect():
    import psycopg

    connection = psycopg.connect(_database_url(), connect_timeout=8)
    connection.autocommit = False
    _ensure_schema(connection)
    return connection


def _ensure_schema(connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS mira_inquiry_turns (
                inquiry_id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                payload JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS mira_inquiry_conversation_idx "
            "ON mira_inquiry_turns (conversation_id, occurred_at)"
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS mira_learning_rules (
                rule_id TEXT PRIMARY KEY,
                payload JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    connection.commit()


def _db_call(action, fallback):
    if not _database_url():
        return fallback()
    if not is_configured():
        raise RuntimeError("Shared storage is configured but its database driver is unavailable.")
    try:
        with _connect() as connection:
            return action(connection)
    except Exception:
        log.error("Shared storage request failed; local fallback is disabled to keep records consistent")
        raise RuntimeError("Shared storage is unavailable. Please try again; no local-only save was made.") from None


def read_inquiries(local_reader) -> list[dict[str, Any]]:
    def action(connection):
        # Preserve older hosted/local files when this instance first switches
        # to shared storage. Existing cloud records and owner edits win.
        database_key = _database_url()
        if database_key not in _imported_local_databases:
            legacy_rows = local_reader()
            with connection.cursor() as cursor:
                cursor.execute("SELECT inquiry_id FROM mira_inquiry_turns")
                existing_ids = {row[0] for row in cursor.fetchall()}
                for legacy in legacy_rows:
                    record = _redact(legacy)
                    inquiry_id = str(record.get("Inquiry ID") or "").strip()
                    if not inquiry_id or inquiry_id in existing_ids:
                        continue
                    cursor.execute(
                        "INSERT INTO mira_inquiry_turns (inquiry_id, conversation_id, occurred_at, payload) "
                        "VALUES (%s, %s, COALESCE(%s::timestamptz, NOW()), %s::jsonb) "
                        "ON CONFLICT (inquiry_id) DO NOTHING",
                        (inquiry_id, str(record.get("Conversation ID") or inquiry_id),
                         record.get("Timestamp (Asia/Kolkata)") or None,
                         json.dumps(record, ensure_ascii=False, default=str)),
                    )
            connection.commit()
            _imported_local_databases.add(database_key)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT payload FROM mira_inquiry_turns "
                "ORDER BY occurred_at ASC, inquiry_id ASC"
            )
            return [dict(row[0]) for row in cursor.fetchall() if isinstance(row[0], dict)]

    return _db_call(action, local_reader)


def append_inquiry(record: dict[str, Any], local_writer) -> None:
    record = _redact(record)
    def action(connection):
        inquiry_id = str(record.get("Inquiry ID") or "").strip()
        conversation_id = str(record.get("Conversation ID") or inquiry_id).strip()
        if not inquiry_id:
            raise ValueError("Inquiry ID is required for persistent storage")
        timestamp = record.get("Timestamp (Asia/Kolkata)")
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO mira_inquiry_turns
                    (inquiry_id, conversation_id, occurred_at, payload, updated_at)
                VALUES (%s, %s, COALESCE(%s::timestamptz, NOW()), %s::jsonb, NOW())
                ON CONFLICT (inquiry_id) DO UPDATE SET
                    conversation_id = EXCLUDED.conversation_id,
                    payload = EXCLUDED.payload,
                    updated_at = NOW()
                """,
                (inquiry_id, conversation_id, str(timestamp) if timestamp else None,
                 json.dumps(record, ensure_ascii=False, default=str)),
            )
        connection.commit()

    _db_call(action, lambda: local_writer(record))


def _update_rows(predicate_sql: str, predicate_value: str, fields: dict[str, Any], local_updater):
    def action(connection):
        changed = 0
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT inquiry_id, payload FROM mira_inquiry_turns WHERE {predicate_sql} FOR UPDATE",
                (predicate_value,),
            )
            for inquiry_id, payload in cursor.fetchall():
                merged = dict(payload or {})
                merged.update(fields)
                cursor.execute(
                    "UPDATE mira_inquiry_turns SET payload=%s::jsonb, updated_at=NOW() WHERE inquiry_id=%s",
                    (json.dumps(merged, ensure_ascii=False, default=str), inquiry_id),
                )
                changed += 1
        connection.commit()
        return changed

    return _db_call(action, lambda: local_updater(predicate_value, fields))


def update_inquiry_fields(inquiry_id: str, fields: dict[str, Any], local_updater) -> bool:
    return bool(_update_rows("inquiry_id = %s", str(inquiry_id), fields,
                             lambda value, updates: local_updater(value, updates)))


def update_conversation_fields(conversation_id: str, fields: dict[str, Any], local_updater) -> int:
    return int(_update_rows("conversation_id = %s", str(conversation_id), fields,
                            lambda value, updates: local_updater(value, updates)))


def load_learning_rules(local_loader) -> list[dict[str, Any]] | None:
    def action(connection):
        with connection.cursor() as cursor:
            cursor.execute("SELECT payload FROM mira_learning_rules ORDER BY rule_id")
            rules = [dict(row[0]) for row in cursor.fetchall() if isinstance(row[0], dict)]
        if rules:
            return rules
        # Seed a newly configured database from the owner's existing private
        # library. This makes the first hosted run preserve approved guidance.
        seeded = local_loader()
        with connection.cursor() as cursor:
            for rule in seeded:
                cursor.execute(
                    "INSERT INTO mira_learning_rules (rule_id, payload, updated_at) VALUES (%s, %s::jsonb, NOW()) ON CONFLICT DO NOTHING",
                    (str(rule.get("Rule ID") or ""), json.dumps(rule, ensure_ascii=False, default=str)),
                )
        connection.commit()
        return seeded

    return _db_call(action, local_loader)


def save_learning_rules(rules: list[dict[str, Any]], local_saver) -> list[dict[str, Any]]:
    def action(connection):
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM mira_learning_rules")
            for rule in rules:
                cursor.execute(
                    "INSERT INTO mira_learning_rules (rule_id, payload, updated_at) VALUES (%s, %s::jsonb, NOW())",
                    (str(rule.get("Rule ID") or ""), json.dumps(rule, ensure_ascii=False, default=str)),
                )
        connection.commit()
        return rules

    return _db_call(action, lambda: local_saver(rules))


def revision(local_revision: int = 0) -> int:
    """Return a changing cache key for dashboard reads.

    Include row count and microsecond precision so multiple chat turns written
    in one second still invalidate Streamlit's cached dashboard read.
    """
    def action(connection):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT "
                "(COALESCE(EXTRACT(EPOCH FROM MAX(updated_at)), 0) * 1000000)::bigint "
                "+ COUNT(*) "
                "FROM mira_inquiry_turns"
            )
            return int(cursor.fetchone()[0] or 0)

    return int(_db_call(action, lambda: local_revision))
