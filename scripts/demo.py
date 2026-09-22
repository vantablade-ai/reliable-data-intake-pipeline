from __future__ import annotations

import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import connect_database, initialize_database
from app.repositories.records import IntakeRepository
from app.services.ingestion import IdempotencyConflictError, IntakeService


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="intake-demo-") as directory:
        connection = connect_database(Path(directory) / "demo.db")
        initialize_database(connection)
        service = IntakeService(IntakeRepository(connection))
        alpha = {"record_id": "alpha-1", "email": "RILEY@example.test", "first_name": "Riley", "last_name": "Chen", "company": "Northstar Labs"}
        accepted = service.ingest("provider_alpha", alpha)
        beta = service.ingest("provider_beta", {"contactId": "beta-1", "contactEmail": "riley@EXAMPLE.test", "fullName": "Riley Chen", "organization": {"name": "Northstar Labs"}})
        gamma = service.ingest("provider_gamma", {"ref": "gamma-1", "mail": "", "name": "Morgan Lee", "org": "Orbit Works"})
        bad = service.ingest("provider_alpha", {"record_id": "alpha-bad", "email": "invalid", "first_name": "Casey", "last_name": "Jones"})
        replay_payload = {"record_id": "replay-1", "email": "replay@example.test", "first_name": "Replay", "last_name": "Person"}
        service.ingest("provider_alpha", replay_payload, "demo-key")
        replay = service.ingest("provider_alpha", replay_payload, "demo-key")
        conflict = False
        try:
            service.ingest("provider_alpha", {**replay_payload, "email": "changed@example.test"}, "demo-key")
        except IdempotencyConflictError:
            conflict = True

        checks = [
            (accepted.items[0].decision.value == "ACCEPTED", "[ACCEPTED] Alpha record"),
            (beta.items[0].decision.value == "DUPLICATE", "[DUPLICATE] Beta matched normalized email"),
            (gamma.items[0].decision.value == "REVIEW_REQUIRED" and "missing_email" in gamma.items[0].reasons, "[REVIEW_REQUIRED] Gamma missing_email"),
            (bad.items[0].decision.value == "REJECTED", "[REJECTED] Alpha invalid_email"),
            (replay.idempotent_replay, "[REPLAY] same request reused safely"),
            (conflict, "[409] changed request rejected for reused idempotency key"),
        ]
        print("Reliable Data Intake Pipeline — demo\n")
        for ok, message in checks:
            print(message if ok else f"[FAILED] {message}")
        record_count = connection.execute("SELECT COUNT(*) FROM canonical_records").fetchone()[0]
        review_count = connection.execute("SELECT COUNT(*) FROM canonical_records WHERE status='REVIEW_REQUIRED'").fetchone()[0]
        print(f"\nCanonical records: {record_count}\nReview queue: {review_count}")
        connection.close()
        if not all(ok for ok, _ in checks):
            raise SystemExit(1)
        print("\nAll demo invariants passed.")


if __name__ == "__main__":
    main()
