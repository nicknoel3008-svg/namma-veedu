"""One-time migration of the private local records into configured PostgreSQL.

Run locally after setting DATABASE_URL in the environment (or Streamlit
secrets). The command is intentionally explicit and idempotent.
"""

from __future__ import annotations

from inquiry_log import read_inquiries
from mira_learning_library import load_learning_rules, save_learning_rules
import storage_backend


def main() -> None:
    if not storage_backend.is_configured():
        raise SystemExit("DATABASE_URL and psycopg are required before migration.")
    rows = read_inquiries()
    for row in rows:
        storage_backend.append_inquiry(row, lambda _record: None)
    rules = load_learning_rules()
    storage_backend.save_learning_rules(rules, lambda value: value)
    print(f"Migrated {len(rows)} inquiry turns and {len(rules)} learning rules.")


if __name__ == "__main__":
    main()
