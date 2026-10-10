"""Consent-based WhatsApp template queue; shares the email queue's persistence."""
from datetime import datetime
import re
from uuid import uuid4
import requests
from agent_runtime import INDIA_TZ
from followup_service import FOLLOWUP_DB, _connect, next_three_day_boundary

CONFIG_KEYS = ("FOLLOWUP_WHATSAPP_ENABLED", "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID",
               "WHATSAPP_API_VERSION", "WHATSAPP_TEMPLATE_NAME", "WHATSAPP_TEMPLATE_LANGUAGE", "FOLLOWUP_PUBLIC_URL")


def normalize_phone(value):
    phone = re.sub(r"[\s().-]", "", str(value))
    if not re.fullmatch(r"\+[1-9]\d{7,14}", phone):
        raise ValueError("Enter a WhatsApp number with + and country code, for example +91 followed by your number.")
    return phone


def whatsapp_config_issues(config):
    from followup_service import email_config_issues
    issues = []
    if str(config.get("FOLLOWUP_WHATSAPP_ENABLED", "")).lower() != "true":
        issues.append("WhatsApp delivery is disabled (FOLLOWUP_WHATSAPP_ENABLED)")
    for key in CONFIG_KEYS[1:]:
        if not str(config.get(key, "")).strip():
            issues.append(f"Missing {key}")
    if config.get("WHATSAPP_API_VERSION") and not re.fullmatch(r"v\d+\.\d+", config["WHATSAPP_API_VERSION"]):
        issues.append("WHATSAPP_API_VERSION must look like vXX.0")
    if config.get("WHATSAPP_PHONE_NUMBER_ID") and not config["WHATSAPP_PHONE_NUMBER_ID"].isdigit():
        issues.append("WHATSAPP_PHONE_NUMBER_ID must contain digits only")
    issues.extend(issue for issue in email_config_issues(config) if issue.startswith("FOLLOWUP_PUBLIC_URL"))
    return issues


def schedule_whatsapp_followup(*, user_id, conversation_id, recipient_phone, customer_name,
                               preference_summary, started_at, recommendations="", max_messages=1,
                               consent=False, initial_status="saved_pending_activation", db_path=FOLLOWUP_DB):
    if not consent:
        raise ValueError("WhatsApp opt-in is required")
    if initial_status not in {"scheduled", "saved_pending_activation"} or max_messages != 1:
        raise ValueError("Unsupported schedule")
    phone = normalize_phone(recipient_phone)
    now = datetime.now(INDIA_TZ).isoformat(timespec="seconds")
    schedule_id = uuid4().hex
    with _connect(db_path) as connection:
        existing = connection.execute("SELECT id FROM email_followups WHERE channel='whatsapp' AND user_id=? AND conversation_id=? AND recipient_phone=? AND recommendations=? AND preference_summary=? AND max_messages=? AND status IN ('scheduled','sending','saved_pending_activation')",
            (user_id, conversation_id, phone, recommendations[:1000], preference_summary[:500], max_messages)).fetchone()
        if existing:
            return existing["id"]
        connection.execute("""INSERT INTO email_followups
            (id,user_id,conversation_id,recipient_email,customer_name,preference_summary,started_at,next_send_at,
             cadence_days,max_messages,status,opted_in_at,updated_at,channel,recipient_phone,recommendations)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (schedule_id,user_id,conversation_id,"",customer_name[:100],preference_summary[:500],
             started_at.astimezone(INDIA_TZ).isoformat(timespec="seconds"),next_three_day_boundary(started_at).isoformat(timespec="seconds"),
             3,max_messages,initial_status,now,now,"whatsapp",phone,recommendations[:1000]))
    return schedule_id


def send_due_whatsapp_followups(config, db_path=FOLLOWUP_DB, *, recipient_allowlist=None):
    if whatsapp_config_issues(config):
        raise RuntimeError("WhatsApp setup is incomplete; no message sent.")
    now = datetime.now(INDIA_TZ)
    with _connect(db_path) as connection:
        due = connection.execute("SELECT * FROM email_followups WHERE channel='whatsapp' AND status='scheduled' AND next_send_at<=? ORDER BY next_send_at", (now.isoformat(timespec="seconds"),)).fetchall()
    accepted = failed = 0
    for row in due:
        if recipient_allowlist is not None and row["recipient_phone"] not in recipient_allowlist:
            continue
        with _connect(db_path) as connection:
            claimed = connection.execute("UPDATE email_followups SET status='sending', updated_at=? WHERE id=? AND status='scheduled'", (now.isoformat(timespec="seconds"),row["id"]))
            if claimed.rowcount != 1:
                continue
        try:
            payload = {"messaging_product":"whatsapp", "to":row["recipient_phone"].lstrip("+"), "type":"template",
                "template":{"name":config["WHATSAPP_TEMPLATE_NAME"], "language":{"code":config["WHATSAPP_TEMPLATE_LANGUAGE"]},
                    "components":[{"type":"body","parameters":[{"type":"text","text":row["recommendations"] or "No saved matching recommendations. Please resume your search on Namma Veedu."}]},
                                  {"type":"button","sub_type":"url","index":"0","parameters":[{"type":"text","text":row["id"]}]}]}}
            response = requests.post(f"https://graph.facebook.com/{config['WHATSAPP_API_VERSION']}/{config['WHATSAPP_PHONE_NUMBER_ID']}/messages",
                headers={"Authorization":"Bearer "+config["WHATSAPP_ACCESS_TOKEN"]}, json=payload,timeout=30)
            response.raise_for_status()
            message_id = response.json()["messages"][0]["id"]
            # Accepted by Meta is distinct from handset delivery. No blind
            # retry on timeouts: acceptance can be ambiguous and duplicate texts hurt users.
            with _connect(db_path) as connection:
                connection.execute("UPDATE email_followups SET status='accepted', sent_count=sent_count+1, provider_message_id=?, last_error='', updated_at=? WHERE id=? AND status='sending'", (message_id,now.isoformat(timespec="seconds"),row["id"]))
            accepted += 1
        except Exception as error:
            with _connect(db_path) as connection:
                connection.execute("UPDATE email_followups SET status='needs_review', last_error=?, updated_at=? WHERE id=? AND status='sending'", ("WhatsApp request failed or acceptance is uncertain: "+type(error).__name__,now.isoformat(timespec="seconds"),row["id"]))
            failed += 1
        # A reporting failure must not turn an accepted message into a retry.
        from inquiry_log import update_conversation_fields
        try:
            with _connect(db_path) as connection:
                current = connection.execute("SELECT status FROM email_followups WHERE id=?", (row["id"],)).fetchone()
            update_conversation_fields(row["conversation_id"], {"Follow-up schedule status":"Accepted by WhatsApp; delivery unconfirmed" if current["status"] == "accepted" else "Needs review", "Next follow-up time (Asia/Kolkata)":""})
        except Exception:
            pass
    return accepted, failed
