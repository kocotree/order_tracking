import argparse
import json
from uuid import uuid4

from app.db.session import create_database_engine, create_session_factory
from app.modules.infrastructure import InfrastructureStore, utc_now
from app.settings.config import Settings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("initial", "incremental"))
    parser.add_argument("--dedupe-key", required=True)
    parser.add_argument("--actor-id")
    args = parser.parse_args()
    settings = Settings()
    engine = create_database_engine(settings.database_url)
    store = InfrastructureStore(create_session_factory(engine))
    request_id = uuid4().hex
    job_id = store.enqueue_job(
        job_type=f"product-sync-{args.kind}",
        dedupe_key=args.dedupe_key,
        payload={"request_id": request_id, "actor_id": args.actor_id},
        available_at=utc_now(),
    )
    store.append_audit_log(
        request_id=request_id,
        action="product_sync.scheduled",
        target_type="background_job",
        target_id=str(job_id),
        changes={"runType": args.kind},
        actor_id=args.actor_id,
        source_terminal="internal_cli",
    )
    engine.dispose()
    print(json.dumps({"jobId": job_id, "requestId": request_id}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
