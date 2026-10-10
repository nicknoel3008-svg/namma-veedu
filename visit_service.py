"""Private property-visit requests with owner confirmation and conflict checks."""
from datetime import datetime
from hashlib import sha256
from uuid import uuid4
import re
from agent_runtime import INDIA_TZ
from followup_service import _connect, FOLLOWUP_DB
from whatsapp_followup import normalize_phone

STATUSES = ("Requested", "Confirmed", "Declined", "Cancelled")


def property_key(record):
    value = record.get("property_id") or "|".join(str(record.get(k) or "") for k in ("title", "source_url", "location"))
    return sha256(str(value).encode()).hexdigest()


def _schema(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS property_visit_requests (
        id TEXT PRIMARY KEY, user_id TEXT NOT NULL, property_key TEXT NOT NULL,
        property_title TEXT NOT NULL, source_url TEXT NOT NULL, visit_at TEXT NOT NULL,
        slot_kind TEXT NOT NULL, customer_name TEXT NOT NULL, contact_method TEXT NOT NULL,
        contact_value TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Requested',
        consent_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS confirmed_property_visit_slot ON property_visit_requests(property_key,visit_at) WHERE status='Confirmed'")
    if getattr(connection,"shared",False):
        connection.execute("ALTER TABLE property_visit_requests ENABLE ROW LEVEL SECURITY")


def confirmed_visit_times(record, date, db_path=FOLLOWUP_DB):
    with _connect(db_path) as connection:
        _schema(connection)
        rows=connection.execute("SELECT visit_at FROM property_visit_requests WHERE property_key=? AND status='Confirmed'",(property_key(record),)).fetchall()
    return {datetime.fromisoformat(row["visit_at"]).strftime("%H:%M") for row in rows if datetime.fromisoformat(row["visit_at"]).date()==date}


def request_visit(*, record, user_id, visit_at, slot_kind, customer_name, contact_method, contact_value, consent, db_path=FOLLOWUP_DB):
    if not consent:
        raise ValueError("Please consent to share your contact for this visit request.")
    if not customer_name.strip():
        raise ValueError("Please enter your name.")
    if visit_at.tzinfo is None or visit_at <= datetime.now(INDIA_TZ):
        raise ValueError("Choose a future visit date and time (IST).")
    if slot_kind not in {"Predefined slot", "Custom time"}:
        raise ValueError("Choose a supported slot type.")
    if contact_method == "WhatsApp":
        contact_value=normalize_phone(contact_value)
    elif contact_method != "Email" or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",contact_value.strip()):
        raise ValueError("Please enter a valid contact address or WhatsApp number.")
    key=property_key(record)
    when=visit_at.astimezone(INDIA_TZ).replace(second=0,microsecond=0).isoformat(timespec="minutes")
    now=datetime.now(INDIA_TZ).isoformat(timespec="seconds")
    with _connect(db_path) as connection:
        _schema(connection)
        taken=connection.execute("SELECT id FROM property_visit_requests WHERE property_key=? AND visit_at=? AND status='Confirmed'",(key,when)).fetchone()
        if taken:
            raise ValueError("This property visit time is already confirmed. Please choose another time.")
        existing=connection.execute("SELECT id FROM property_visit_requests WHERE user_id=? AND property_key=? AND visit_at=? AND status='Requested'",(user_id,key,when)).fetchone()
        if existing:
            return existing["id"]
        visit_id=uuid4().hex
        connection.execute("""INSERT INTO property_visit_requests
            (id,user_id,property_key,property_title,source_url,visit_at,slot_kind,customer_name,contact_method,contact_value,status,consent_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",(visit_id,user_id,key,str(record.get("title") or "Saved property")[:200],str(record.get("source_url") or "")[:1000],when,slot_kind,customer_name.strip()[:100],contact_method,contact_value.strip(),"Requested",now,now))
    return visit_id


def list_visit_requests(user_id=None, db_path=FOLLOWUP_DB):
    with _connect(db_path) as connection:
        _schema(connection)
        rows=connection.execute("SELECT * FROM property_visit_requests"+(" WHERE user_id=?" if user_id is not None else "")+" ORDER BY updated_at DESC",(user_id,) if user_id is not None else ()).fetchall()
    return [dict(row) for row in rows]


def update_visit_status(visit_id, status, *, user_id=None, db_path=FOLLOWUP_DB):
    if status not in STATUSES or (user_id is not None and status != "Cancelled"):
        raise ValueError("Unsupported visit status change.")
    with _connect(db_path) as connection:
        _schema(connection)
        row=connection.execute("SELECT * FROM property_visit_requests WHERE id=?"+(" AND user_id=?" if user_id is not None else ""),(visit_id,user_id) if user_id is not None else (visit_id,)).fetchone()
        if not row:
            return False
        if status == "Confirmed":
            if datetime.fromisoformat(row["visit_at"]) <= datetime.now(INDIA_TZ):
                raise ValueError("This visit time has passed. Ask the customer to choose another time.")
            conflict=connection.execute("SELECT id FROM property_visit_requests WHERE property_key=? AND visit_at=? AND status='Confirmed' AND id<>?",(row["property_key"],row["visit_at"],visit_id)).fetchone()
            if conflict:
                raise ValueError("Another visit is already confirmed for this property and time.")
        connection.execute("UPDATE property_visit_requests SET status=?,updated_at=? WHERE id=?",(status,datetime.now(INDIA_TZ).isoformat(timespec="seconds"),visit_id))
    return True
