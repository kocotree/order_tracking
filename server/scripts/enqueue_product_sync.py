import argparse
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from app.adapters.product import (
    AppCredentialJstProductSource,
    JstProductSourceConfig,
    ProductSourceError,
)
from app.db.session import create_database_engine, create_session_factory
from app.modules.infrastructure import InfrastructureStore, utc_now
from app.modules.order_import import OrderImportService
from app.modules.product_sync import ProductSyncService
from app.settings.config import Settings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("initial", "incremental", "targeted", "categories"))
    parser.add_argument("--dedupe-key")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--name", help="exact product name; use style ID if ambiguous")
    target.add_argument("--i-id", help="Jushuitan style ID")
    parser.add_argument("--commit", metavar="PREVIEW_DIGEST", help="apply the unchanged preview")
    parser.add_argument("--actor-id")
    parser.add_argument(
        "--resume-request-id",
        help="reuse a failed product-sync request ID and continue its saved checkpoint",
    )
    args = parser.parse_args()
    if args.kind in {"initial", "incremental"}:
        if not args.dedupe_key or args.name or args.i_id or args.commit:
            parser.error("full/incremental sync requires --dedupe-key and no target/commit")
    elif args.kind == "targeted":
        if not (args.name or args.i_id) or args.dedupe_key or args.resume_request_id:
            parser.error("targeted sync requires --name or --i-id; no dedupe/resume")
    elif args.name or args.i_id or args.dedupe_key or args.resume_request_id:
        parser.error("categories accepts only --commit and --actor-id")
    request_id = args.resume_request_id or uuid4().hex
    if len(request_id) > 64:
        parser.error("--resume-request-id must be at most 64 characters")
    settings = Settings()
    engine = create_database_engine(settings.database_url)
    sessions = create_session_factory(engine)
    if args.kind in {"targeted", "categories"}:
        url = make_url(settings.database_url)
        environment = {"appEnv": settings.app_env, "host": url.host, "database": url.database}
        try:
            if args.kind == "categories":
                result = OrderImportService(sessions).rebuild_categories(
                    expected_digest=args.commit, request_id=request_id, actor_id=args.actor_id,
                )
            else:
                if not settings.jst_product_app_key or not settings.jst_product_app_secret:
                    raise ProductSourceError("product_source_not_configured")
                source = AppCredentialJstProductSource(JstProductSourceConfig(
                    app_key=settings.jst_product_app_key,
                    app_secret=settings.jst_product_app_secret,
                    initial_sync_begin=datetime.fromisoformat(
                        settings.jst_product_initial_sync_begin
                    ) if settings.jst_product_initial_sync_begin else datetime.now(),
                    endpoint=settings.jst_product_endpoint,
                    token_cache_path=Path(settings.jst_product_token_cache_path),
                    page_size=settings.jst_product_page_size,
                    request_interval_seconds=settings.jst_product_request_interval_seconds,
                    retry_attempts=settings.jst_product_retry_attempts,
                    retry_base_delay_seconds=settings.jst_product_retry_base_delay_seconds,
                ))
                service = ProductSyncService(sessions, source=source)
                result = (
                    asdict(service.run_targeted(
                        name=args.name, i_id=args.i_id, expected_digest=args.commit,
                        request_id=request_id, worker_id="internal_cli", actor_id=args.actor_id,
                    )) if args.commit else service.preview_targeted(name=args.name, i_id=args.i_id)
                )
            print(json.dumps({"environment": environment, **result}, ensure_ascii=False))
            return 0
        except (ProductSourceError, ValueError) as error:
            code = str(error)
            if not code.startswith(("product_", "category_")):
                code = "product_operation_failed"
            print(json.dumps({"environment": environment, "error": code}, ensure_ascii=False))
            return 1
        except IntegrityError:
            print(json.dumps({"environment": environment, "error": "product_sync_busy"}))
            return 1
        finally:
            engine.dispose()
    store = InfrastructureStore(sessions)
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
