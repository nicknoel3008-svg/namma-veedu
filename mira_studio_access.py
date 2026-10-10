"""Owner-managed, individual access to Mira Studio.

The owner remains authenticated by the Streamlit secret. Peer access codes are
salted and hashed; the plaintext code is shown only when the owner creates it.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets

import storage_backend


LOCAL_FILE = Path(__file__).parent / "data" / "private" / "mira_studio_users.json"
ITERATIONS = 240_000
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _normal_email(value: str) -> str:
    email = str(value or "").strip().casefold()
    if not EMAIL_PATTERN.fullmatch(email):
        raise ValueError("Enter a valid peer email address.")
    return email


def generate_access_code() -> str:
    """Return a strong code that is easy to copy and is never stored raw."""
    return secrets.token_urlsafe(15)


def _digest(code: str, salt_hex: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", str(code).encode("utf-8"), bytes.fromhex(salt_hex), ITERATIONS
    ).hex()


def _local_rows() -> list[dict]:
    if not LOCAL_FILE.exists():
        return []
    try:
        data = json.loads(LOCAL_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [dict(row) for row in data if isinstance(row, dict)]


def _save_local(rows: list[dict]) -> None:
    LOCAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = LOCAL_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(LOCAL_FILE)


def list_managers() -> list[dict]:
    def database(connection):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT email, display_name, role, active, created_at, updated_at "
                "FROM mira_studio_users ORDER BY display_name, email"
            )
            return [
                {
                    "Email": row[0], "Name": row[1], "Role": row[2],
                    "Active": bool(row[3]), "Created": row[4], "Updated": row[5],
                }
                for row in cursor.fetchall()
            ]

    def local():
        return [
            {
                "Email": row["email"], "Name": row["display_name"],
                "Role": row.get("role", "Manager"), "Active": bool(row.get("active", True)),
                "Created": row.get("created_at", ""), "Updated": row.get("updated_at", ""),
            }
            for row in _local_rows()
        ]

    return storage_backend._db_call(database, local)


def save_manager(email: str, display_name: str, access_code: str) -> dict:
    email = _normal_email(email)
    name = str(display_name or "").strip()
    code = str(access_code or "").strip()
    if not name:
        raise ValueError("Enter the peer's name.")
    if len(code) < 12:
        raise ValueError("Use an access code with at least 12 characters.")
    salt = secrets.token_hex(16)
    digest = _digest(code, salt)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def database(connection):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO mira_studio_users
                    (email, display_name, role, access_code_hash, access_code_salt, active, updated_at)
                VALUES (%s, %s, 'Manager', %s, %s, TRUE, NOW())
                ON CONFLICT (email) DO UPDATE SET
                    display_name=EXCLUDED.display_name, role='Manager',
                    access_code_hash=EXCLUDED.access_code_hash,
                    access_code_salt=EXCLUDED.access_code_salt,
                    active=TRUE, updated_at=NOW()
                """,
                (email, name, digest, salt),
            )
        connection.commit()

    def local():
        rows = [row for row in _local_rows() if row.get("email") != email]
        rows.append({
            "email": email, "display_name": name, "role": "Manager",
            "access_code_hash": digest, "access_code_salt": salt,
            "active": True, "created_at": now, "updated_at": now,
        })
        _save_local(rows)

    storage_backend._db_call(database, local)
    return {"email": email, "display_name": name, "role": "Manager"}


def verify_manager(email: str, access_code: str) -> dict | None:
    try:
        email = _normal_email(email)
    except ValueError:
        return None
    code = str(access_code or "")

    def database(connection):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT display_name, role, access_code_hash, access_code_salt, active "
                "FROM mira_studio_users WHERE email=%s",
                (email,),
            )
            row = cursor.fetchone()
        return row

    def local():
        row = next((item for item in _local_rows() if item.get("email") == email), None)
        if not row:
            return None
        return (
            row.get("display_name", ""), row.get("role", "Manager"),
            row.get("access_code_hash", ""), row.get("access_code_salt", ""),
            bool(row.get("active", True)),
        )

    row = storage_backend._db_call(database, local)
    if not row or not row[4]:
        return None
    supplied = _digest(code, row[3])
    if not hmac.compare_digest(supplied, row[2]):
        return None
    return {"email": email, "display_name": row[0], "role": row[1]}


def set_manager_active(email: str, active: bool) -> None:
    email = _normal_email(email)

    def database(connection):
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE mira_studio_users SET active=%s, updated_at=NOW() WHERE email=%s",
                (bool(active), email),
            )
        connection.commit()

    def local():
        rows = _local_rows()
        for row in rows:
            if row.get("email") == email:
                row["active"] = bool(active)
                row["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _save_local(rows)

    storage_backend._db_call(database, local)
