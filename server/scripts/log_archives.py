import argparse
import json
from datetime import datetime, timedelta

import oss2
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import case, func, select

from app.adapters.private_files import AliyunOssPrivateFileStore
from app.db.models import LogArchiveEntry
from app.db.session import create_database_engine, create_session_factory
from app.modules.infrastructure import utc_now
from app.modules.log_retention import TABLES, LogRetention, eligibility
from app.modules.notifications_audit.service import NotificationsAuditService


class ArchiveSettings(BaseSettings):
    database_url: str
    oss_endpoint: str
    oss_region: str
    oss_bucket: str
    oss_access_key_id: str
    oss_access_key_secret: str
    model_config = SettingsConfigDict(env_prefix="LOG_ARCHIVE_", extra="ignore")


def main() -> None:
    parser = argparse.ArgumentParser(description="私有日志归档、盘点与脱敏检索")
    parser.add_argument("operation", choices=("inventory", "run", "search"))
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--table", choices=tuple(TABLES))
    parser.add_argument("--from-utc", type=datetime.fromisoformat)
    parser.add_argument("--to-utc", type=datetime.fromisoformat)
    parser.add_argument("--id")
    parser.add_argument("--confirm", choices=("archive-and-expire",))
    args = parser.parse_args()
    if not 1 <= args.limit <= 10000:
        parser.error("limit must be 1..10000")
    if args.operation == "run" and args.confirm != "archive-and-expire":
        parser.error("run requires --confirm archive-and-expire")
    if args.operation == "search" and (not args.table or not args.from_utc or not args.to_utc):
        parser.error("search requires --table --from-utc --to-utc (naive UTC)")
    if args.operation == "search" and (
        args.from_utc.tzinfo or args.to_utc.tzinfo or args.from_utc >= args.to_utc
    ):
        parser.error("search requires ordered naive UTC boundaries")
    settings = ArchiveSettings()
    engine = create_database_engine(settings.database_url)
    engine.hide_parameters = True
    sessions = create_session_factory(engine)
    if args.operation == "inventory":
        with sessions() as session:
            now = utc_now()
            for name, table in TABLES.items():
                age = case((table.c.created_at >= now - timedelta(days=30), "0-30d"),
                           (table.c.created_at > now - timedelta(days=180), "30-180d"),
                           else_="180d+")
                protection = case((eligibility(name), "eligible"), else_="protected")
                state = table.c.action if name == "audit_logs" else table.c.status
                detail = table.c[{
                    "audit_logs": "changes", "order_import_runs": "sync_result",
                    "product_sync_runs": "source_checkpoint", "background_jobs": "payload",
                    "outbox_messages": "payload",
                }[name]]
                classified = select(
                    age.label("age"), protection.label("protection"), state.label("state"),
                    table.c.created_at, func.length(detail).label("detail_bytes"),
                ).subquery()
                for row in session.execute(select(
                    classified.c.age, classified.c.protection, classified.c.state, func.count(),
                    func.min(classified.c.created_at), func.max(classified.c.created_at),
                    func.sum(classified.c.detail_bytes),
                ).group_by(classified.c.age, classified.c.protection, classified.c.state)):
                    print(json.dumps({"table": name, "age": row[0], "protection": row[1],
                                      "state": row[2], "count": row[3], "oldest": str(row[4]),
                                      "newest": str(row[5]), "detailBytes": int(row[6] or 0)}))
        engine.dispose()
        return
    client = oss2.Bucket(oss2.AuthV4(settings.oss_access_key_id, settings.oss_access_key_secret),
                        settings.oss_endpoint, settings.oss_bucket, region=settings.oss_region)
    if client.get_bucket_acl().acl != oss2.BUCKET_ACL_PRIVATE:
        raise ValueError("archive_bucket_must_be_private")
    store = AliyunOssPrivateFileStore(
        endpoint=settings.oss_endpoint, region=settings.oss_region,
        access_key_id=settings.oss_access_key_id, access_key_secret=settings.oss_access_key_secret,
        bucket=settings.oss_bucket, bucket_client=client,
    )
    service = LogRetention(sessions, store)
    if args.operation == "run":
        print(json.dumps(service.run(limit=args.limit)))
    else:
        with sessions() as session:
            query = select(LogArchiveEntry).where(
                LogArchiveEntry.source_table == args.table,
                LogArchiveEntry.source_created_at >= args.from_utc,
                LogArchiveEntry.source_created_at < args.to_utc,
                LogArchiveEntry.status == "completed", LogArchiveEntry.expires_at > utc_now(),
            )
            if args.id:
                query = query.where(LogArchiveEntry.source_id == args.id)
            for entry in session.scalars(query.order_by(
                LogArchiveEntry.source_created_at, LogArchiveEntry.source_id,
            ).limit(args.limit)):
                print(json.dumps(NotificationsAuditService._redact_changes(service.read(entry)),
                                 ensure_ascii=False))
    engine.dispose()


if __name__ == "__main__":
    main()
