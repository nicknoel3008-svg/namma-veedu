"""Send one isolated visit-reminder email and optionally verify Gmail receipt."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import email
import imaplib
from pathlib import Path
from tempfile import TemporaryDirectory
import time

from agent_runtime import INDIA_TZ
from followup_service import _connect, email_config_issues
from run_followup_worker import load_config
from visit_journey import run_visit_worker, schema
from visit_service import request_visit, update_visit_status


def gmail_inbox_uid(config: dict[str, str]) -> int:
    username = config["FOLLOWUP_SMTP_USERNAME"]
    password = config["FOLLOWUP_SMTP_PASSWORD"]
    with imaplib.IMAP4_SSL("imap.gmail.com", 993) as mailbox:
        mailbox.login(username, password)
        mailbox.select("INBOX")
        status, data = mailbox.uid("search", None, "ALL")
        if status != "OK" or not data or not data[0]:
            return 0
        return int(data[0].split()[-1])


def received_after(config: dict[str, str], after_uid: int, property_title: str) -> bool:
    username = config["FOLLOWUP_SMTP_USERNAME"]
    password = config["FOLLOWUP_SMTP_PASSWORD"]
    with imaplib.IMAP4_SSL("imap.gmail.com", 993) as mailbox:
        mailbox.login(username, password)
        mailbox.select("INBOX")
        status, data = mailbox.uid("search", None, f"UID {after_uid + 1}:*")
        if status != "OK" or not data:
            return False
        for uid in reversed(data[0].split()):
            status, message_data = mailbox.uid("fetch", uid, "(RFC822)")
            if status != "OK" or not message_data or not isinstance(message_data[0], tuple):
                continue
            message = email.message_from_bytes(message_data[0][1])
            body = ""
            if message.is_multipart():
                for part in message.walk():
                    if part.get_content_type() == "text/plain":
                        body += part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
            else:
                body = message.get_payload(decode=True).decode(message.get_content_charset() or "utf-8", errors="replace")
            if message.get("Subject") == "Please confirm your property visit" and property_title in body:
                return True
    return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Send one real isolated visit reminder email.")
    parser.add_argument("--recipient", default="", help="Recipient email; defaults to the configured sender.")
    parser.add_argument("--send", action="store_true", help="Required acknowledgment that one real email will be sent.")
    args = parser.parse_args(argv)
    if not args.send:
        print("No email sent. Pass --send to run the isolated receipt test.")
        return 2
    config = load_config()
    config["VISIT_EMAIL_ENABLED"] = "true"
    issues = email_config_issues(config)
    if issues:
        print("Email setup needs attention: " + "; ".join(issues))
        return 2
    recipient = (args.recipient or config["FOLLOWUP_SMTP_FROM"]).strip().lower()
    marker = datetime.now(INDIA_TZ).strftime("%Y%m%d-%H%M%S")
    property_title = f"Namma Veedu email receipt test {marker}"
    baseline_uid = 0
    can_check_receipt = recipient == config["FOLLOWUP_SMTP_USERNAME"].strip().lower() and recipient.endswith("@gmail.com")
    if can_check_receipt:
        try:
            baseline_uid = gmail_inbox_uid(config)
        except Exception:
            can_check_receipt = False
    with TemporaryDirectory() as folder:
        database = Path(folder) / "visit-email-test.sqlite3"
        now = datetime.now(INDIA_TZ)
        visit_id = request_visit(
            record={"property_id": marker, "title": property_title},
            user_id="real-email-qa",
            conversation_id="real-email-qa",
            visit_at=now + timedelta(minutes=30),
            slot_kind="Custom time",
            customer_name="Namma Veedu QA",
            contact_method="Email",
            contact_value=recipient,
            consent=True,
            email_reminders=True,
            preferences={"purpose": "isolated email receipt test"},
            db_path=database,
        )
        update_visit_status(visit_id, "Confirmed", db_path=database)
        submitted, failed = run_visit_worker(config, database, now=now)
        with _connect(database) as connection:
            schema(connection)
            state = connection.execute(
                "SELECT status FROM visit_email_outbox WHERE visit_id=? AND kind='reminder'", (visit_id,)
            ).fetchone()
        if submitted != 1 or failed or not state or state["status"] != "sent":
            print(f"Email test failed: submitted={submitted}, failed={failed}, queue={state['status'] if state else 'missing'}")
            return 1
    receipt = False
    if can_check_receipt:
        for _ in range(6):
            time.sleep(5)
            if received_after(config, baseline_uid, property_title):
                receipt = True
                break
    print(f"SMTP accepted one visit reminder for {recipient}.")
    print("Inbox receipt confirmed through Gmail IMAP." if receipt else "Inbox receipt could not be independently confirmed; check the recipient inbox.")
    return 0 if receipt or not can_check_receipt else 1


if __name__ == "__main__":
    raise SystemExit(main())

