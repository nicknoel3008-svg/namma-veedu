"""Send due, user-opted-in email follow-ups; invoke from an OS scheduler."""

from __future__ import annotations

from pathlib import Path
import os
import sys
import argparse

from followup_service import email_config_issues, send_due_followups


ROOT = Path(__file__).resolve().parent
CONFIG_KEYS = (
    "FOLLOWUP_SMTP_HOST", "FOLLOWUP_SMTP_PORT", "FOLLOWUP_SMTP_USERNAME",
    "FOLLOWUP_SMTP_PASSWORD", "FOLLOWUP_SMTP_FROM", "FOLLOWUP_PUBLIC_URL",
)


def load_config() -> dict[str, str]:
    config = {key: os.environ.get(key, "") for key in CONFIG_KEYS}
    secrets_path = ROOT / ".streamlit" / "secrets.toml"
    if secrets_path.exists():
        try:
            import tomllib
            with secrets_path.open("rb") as stream:
                secrets = tomllib.load(stream)
            for key in CONFIG_KEYS:
                config[key] = config[key] or str(secrets.get(key, ""))
        except Exception as error:
            raise RuntimeError(f"Could not read Streamlit follow-up settings: {error}") from error
    return config


def main() -> int:
    parser = argparse.ArgumentParser(description="Process consented email follow-ups.")
    parser.add_argument("--check", action="store_true", help="Validate configuration only; do not connect or send email.")
    args = parser.parse_args()
    config = load_config()
    issues = email_config_issues(config)
    if issues:
        print("Email follow-up setup needs attention:")
        for issue in issues:
            print("- " + issue)
        return 2
    if args.check:
        print("Settings are complete. No email sent; SMTP access, public URL reachability and the scheduler still need verification.")
        return 0
    sent, failed = send_due_followups(config)
    print(f"Follow-up worker finished: {sent} sent, {failed} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
