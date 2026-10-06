import argparse
import json

from sqlalchemy.orm import sessionmaker

from app.adapters.order_source import AppCredentialFeishuOrderSource, FeishuOrderSourceConfig
from app.adapters.shipment_writeback import FeishuShipmentWriter
from app.db.session import create_database_engine
from app.modules.shipment_writeback.service import ShipmentWriteback
from app.settings.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="出货阶段回填配置核验、日志和原任务重试")
    parser.add_argument("action", choices=("inspect", "history", "schedule", "retry", "logs"))
    parser.add_argument("--job-id", type=int)
    args = parser.parse_args()
    settings = Settings()
    config = FeishuOrderSourceConfig(
        app_id=settings.feishu_order_app_id, app_secret=settings.feishu_order_app_secret,
        app_token=settings.feishu_order_app_token, table_id=settings.feishu_order_table_id,
        view_id=settings.feishu_order_view_id, field_ids=settings.feishu_order_field_ids,
    )
    target = FeishuShipmentWriter(
        config, total_field_id=settings.shipment_writeback_total_field_id,
        baseline_formula=settings.shipment_writeback_baseline_formula,
    )
    if args.action == "inspect":
        # 输出只用于受控配置，禁止复制进仓库或共享日志。
        totals = [field for field in target.fields() if field["field_name"] == "出货总数"]
        if len(totals) != 1 or totals[0]["type"] != 20:
            raise ValueError("shipment_writeback_total_field_changed")
        print(json.dumps({
            "total_field_id": totals[0]["field_id"],
            "baseline_formula": totals[0]["property"]["formula_expression"],
        }, ensure_ascii=False))
        return
    if args.action in {"schedule", "retry"} and not settings.shipment_writeback_enabled:
        raise ValueError("shipment_writeback_not_enabled")
    engine = create_database_engine(settings.database_url)
    try:
        service = ShipmentWriteback(
            sessionmaker(engine, expire_on_commit=False),
            source_scope=AppCredentialFeishuOrderSource(config).source_scope, target=target,
        )
        if args.action == "history":
            service.prepare_history()
            print("history_ready")
        elif args.action == "schedule":
            print(json.dumps(service.ensure_due()))
        elif args.action == "retry":
            if args.job_id is None:
                raise ValueError("job-id is required")
            service.retry(args.job_id)
            print("pending")
        else:
            print(json.dumps(service.executions(), ensure_ascii=False))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
