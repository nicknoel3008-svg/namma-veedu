"""Read-only health check for Mira's configured persistent storage."""

from __future__ import annotations

import storage_backend


def main() -> None:
    if not storage_backend.is_configured():
        raise SystemExit("Persistent storage is not configured. Set DATABASE_URL in this CMD session first.")
    inquiries = storage_backend.read_inquiries(lambda: [])
    rules = storage_backend.load_learning_rules(lambda: []) or []
    print("Persistent storage: connected")
    print(f"Inquiry turns stored: {len(inquiries)}")
    print(f"Learning Library rules stored: {len(rules)}")


if __name__ == "__main__":
    main()
