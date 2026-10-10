"""Daily test-number worker: approval gate and explicit recipient restriction."""
from datetime import datetime
from pathlib import Path
import argparse
import json
import os
import requests
from run_followup_worker import load_config
from whatsapp_followup import normalize_phone, send_due_whatsapp_followups


def run(config, recipient, *, check_only=False):
    recipient = normalize_phone(recipient)
    required = ("WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_API_VERSION", "WHATSAPP_TEMPLATE_NAME", "WHATSAPP_TEMPLATE_LANGUAGE")
    if any(not config.get(key) for key in required):
        return {"status": "setup_incomplete", "sent": 0}
    if config["WHATSAPP_PHONE_NUMBER_ID"] != "1330438393493229":
        return {"status": "test_sender_mismatch", "sent": 0}
    response = requests.get(
        f"https://graph.facebook.com/{config['WHATSAPP_API_VERSION']}/1801049450922619/message_templates",
        params={"name": config["WHATSAPP_TEMPLATE_NAME"], "fields": "name,status,language,components"},
        headers={"Authorization": "Bearer " + config["WHATSAPP_ACCESS_TOKEN"]}, timeout=20)
    if not response.ok:
        return {"status": "meta_access_failed", "http": response.status_code, "sent": 0}
    templates = response.json().get("data", [])
    template = next((item for item in templates if item.get("name") == config["WHATSAPP_TEMPLATE_NAME"] and item.get("language") == config["WHATSAPP_TEMPLATE_LANGUAGE"]), None)
    if not template or template.get("status") != "APPROVED":
        return {"status": "template_" + (template.get("status", "missing").lower() if template else "missing"), "sent": 0}
    if check_only:
        return {"status": "ready", "sent": 0}
    if config.get("DATABASE_URL"):
        os.environ["DATABASE_URL"] = config["DATABASE_URL"]
    # Public delivery stays disabled. Only existing scheduled, opted-in rows
    # for this verified test recipient can be processed by this worker.
    enabled = {**config, "FOLLOWUP_WHATSAPP_ENABLED": "true"}
    accepted, failed = send_due_whatsapp_followups(enabled, recipient_allowlist={recipient})
    return {"status": "processed", "accepted": accepted, "failed": failed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipient", required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        result = run(load_config(), args.recipient, check_only=args.check)
    except Exception as error:
        result = {"status": "worker_error", "error_type": type(error).__name__, "sent": 0}
    result["at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    log = Path(__file__).resolve().parent / "data/private/whatsapp_test_worker.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as output:
        output.write(json.dumps(result) + "\n")
    print(json.dumps(result))
    return 1 if result["status"] in {"worker_error", "meta_access_failed", "setup_incomplete", "test_sender_mismatch"} or result.get("failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
