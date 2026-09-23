from collections.abc import Callable
from datetime import date
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field
from sqlalchemy.exc import SQLAlchemyError

from app.api.contracts import ContractFactoryStatusResponse
from app.api.order_import import _candidate_response, _run_response
from app.api.orders import (
    AuditLogListResponse,
    DetailFieldsBatchItem,
    DraftLineWrite,
    _audit_response,
    _draft_lines,
    _order_response,
)
from app.mcp.files import download_descriptor
from app.modules.contracts import ContractService
from app.modules.order_import import OrderImportService
from app.modules.orders import OrderService
from app.modules.orders.dispatch import OrderDispatchService
from app.modules.orders.source_update import OrderSourceUpdateService


def register_order_tools(
    mcp: MCPServer,
    read: Callable[[str, Callable[[str, str], Any]], dict[str, Any]],
    *,
    orders: OrderService,
    imports: OrderImportService | None,
    source_updates: OrderSourceUpdateService,
    dispatch: OrderDispatchService,
    contracts: ContractService,
    origin: str,
) -> None:
    if imports is None:
        raise ValueError("order import service is required for MCP")

    def order_result(name: str, callback: Callable[[str, str], Any]) -> dict[str, Any]:
        return read(name, lambda user_id, rid: _order_response(callback(user_id, rid), rid))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False))
    def start_import_run(
        idempotency_key: str = Field(min_length=1, max_length=191),
    ) -> dict[str, Any]:
        """手动获取飞书新订单。返回后台任务 ID；重复请求使用同一个幂等键。"""
        return read("start_import_run", lambda uid, rid: _run_response(
            imports.create_or_reuse_run(actor_id=uid, request_id=rid,
                                        idempotency_key=idempotency_key), rid
        ))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def get_import_run(run_id: str | None = None) -> dict[str, Any]:
        """查询指定获取任务；省略任务 ID 时查询最近任务。"""
        return read("get_import_run", lambda uid, rid: (
            _run_response(item, rid) if (item := (
                imports.get_run(actor_id=uid, run_id=run_id) if run_id
                else imports.latest_run(actor_id=uid)
            )) else None
        ))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def list_import_candidates(
        status: str = "PENDING", keyword: str = "", category: str | None = None,
        factory_names: list[str] | None = None, trackers: list[str] | None = None,
        validation_state: str | None = None, sort_by: str = "default",
        sort_order: str = "asc", page: int = 1, page_size: int = 20,
    ) -> dict[str, Any]:
        """按网页筛选和分页查询飞书候选。写入须使用返回的稳定 ID。"""
        if page < 1 or not 1 <= page_size <= 100 or len(keyword) > 255:
            raise ValueError("invalid candidate pagination or keyword")

        def query(uid: str, _rid: str) -> dict[str, Any]:
            items, total = imports.list_candidates(
                actor_id=uid, status=status, keyword=keyword, category=category,
                factory_names=factory_names, trackers=trackers,
                validation_state=validation_state, sort_by=sort_by,
                sort_order=sort_order, page=page, page_size=page_size,
            )
            return {"items": [_candidate_response(item).model_dump(mode="json", by_alias=True)
                              for item in items], "total": total,
                    "page": page, "pageSize": page_size}
        return read("list_import_candidates", query)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def get_import_candidate(candidate_id: str) -> dict[str, Any]:
        """查询候选和全部来源明细、校验问题及版本。"""
        return read("get_import_candidate", lambda uid, _rid: _candidate_response(
            imports.get_candidate(actor_id=uid, candidate_id=candidate_id)
        ))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def get_candidate_audit(candidate_id: str) -> dict[str, Any]:
        """查询候选字段修改、导入及排除操作记录。"""
        def query(uid: str, rid: str) -> AuditLogListResponse:
            items = imports.list_candidate_audit(actor_id=uid, candidate_id=candidate_id)
            return AuditLogListResponse(
                items=[_audit_response(item) for item in items],
                total=len(items), request_id=rid,
            )
        return read("get_candidate_audit", query)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False))
    def update_candidate_lines(
        candidate_id: str, version: int,
        lines: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """保存候选明细，仅写明确给出的工厂 ID、合同出货时间和已发数量。"""
        from app.api.order_import import CandidateLinesWrite

        payload = CandidateLinesWrite.model_validate({"version": version, "lines": lines})
        return read("update_candidate_lines", lambda uid, rid: _candidate_response(
            imports.save_candidate_lines(
                actor_id=uid, candidate_id=candidate_id, version=payload.version,
                updates=[(line.candidate_line_id, line.model_dump(
                    exclude={"candidate_line_id"}, exclude_unset=True
                )) for line in payload.lines], request_id=rid,
            )
        ))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False))
    def import_candidates(
        candidates: list[dict[str, Any]], allow_partial: bool = False,
    ) -> dict[str, Any]:
        """按候选 ID 和版本导入。默认先预检全部，任一不合格则零提交；仅明确允许时继续合格项。"""
        if not candidates or len(candidates) > 100:
            raise ValueError("candidate count must be 1..100")
        targets: list[tuple[str, int]] = []
        for item in candidates:
            candidate_id, version = item.get("candidateId"), item.get("version")
            if (not isinstance(candidate_id, str) or not candidate_id
                or isinstance(version, bool) or not isinstance(version, int) or version < 1):
                raise ValueError("each candidate needs candidateId and positive version")
            targets.append((candidate_id, version))
        if len({item[0] for item in targets}) != len(targets):
            raise ValueError("duplicate candidate ID")

        def execute(uid: str, rid: str) -> dict[str, Any]:
            checked: list[tuple[str, int, str | None, str | None]] = []
            for candidate_id, version in targets:
                try:
                    candidate = imports.get_candidate(actor_id=uid, candidate_id=candidate_id)
                except ValueError as failure:
                    checked.append((candidate_id, version, str(failure), None))
                    continue
                error = None
                imported_order_id = candidate.imported_order_id
                if imported_order_id and candidate.status == "IMPORTED":
                    pass
                elif candidate.status != "PENDING" or candidate.version != version:
                    error = "candidate state or version changed"
                elif candidate.validation_state != "READY":
                    error = "candidate is not ready"
                checked.append((candidate_id, version, error, imported_order_id))
            if any(error for _, _, error, _ in checked) and not allow_partial:
                return {"items": [
                    {"candidateId": candidate_id, "version": version,
                     "error": error,
                     "status": "succeeded" if imported_order_id else "notExecuted",
                     **({"orderId": imported_order_id} if imported_order_id else {})}
                    for candidate_id, version, error, imported_order_id in checked
                ]}
            results = []
            stopped = False
            for candidate_id, version, error, imported_order_id in checked:
                result = {"candidateId": candidate_id, "version": version}
                if imported_order_id:
                    results.append({**result, "status": "succeeded",
                                    "orderId": imported_order_id})
                    continue
                if stopped or error:
                    results.append({**result, "error": error, "status": "notExecuted"})
                    continue
                try:
                    order_id = imports.confirm_candidate(
                        actor_id=uid, candidate_id=candidate_id,
                        version=version, request_id=rid,
                    )
                except ValueError as failure:
                    results.append({**result, "status": "failed", "error": str(failure)})
                    stopped = not allow_partial
                except (SQLAlchemyError, TimeoutError):
                    results.append({**result, "status": "needsReconciliation",
                                    "error": "结果待核实，请以原候选 ID 重查后重试"})
                    stopped = True
                else:
                    results.append({**result, "status": "succeeded", "orderId": order_id})
            return {"items": results}
        return read("import_candidates", execute)

    @mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
    def exclude_candidate(candidate_id: str) -> dict[str, Any]:
        """排除完整待处理候选；不会删除飞书来源。需要用户明确授权。"""
        def execute(uid: str, rid: str) -> dict[str, Any]:
            imports.exclude_candidate(actor_id=uid, candidate_id=candidate_id, request_id=rid)
            return {"excluded": True}
        return read("exclude_candidate", execute)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False))
    def create_order_draft(
        order_no: str, order_date: date, tracker: str,
        lines: list[DraftLineWrite],
    ) -> dict[str, Any]:
        """新建手工草稿。工厂使用明确的 factoryId；合同出货时间使用用户提供的日期。"""
        from app.api.orders import DraftCreate

        payload = DraftCreate(order_no=order_no, order_date=order_date,
                              tracker=tracker, lines=lines)
        return order_result("create_order_draft", lambda uid, rid: orders.create_draft(
            actor_id=uid, order_no=payload.order_no, order_date=payload.order_date,
            tracker=payload.tracker, lines=_draft_lines(payload.lines), request_id=rid,
        ))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False))
    def update_order_draft(
        order_id: str, version: int, order_no: str, order_date: date | None,
        tracker: str, lines: list[DraftLineWrite],
    ) -> dict[str, Any]:
        """按版本编辑手工草稿；来源草稿使用明细保存工具。"""
        from app.api.orders import DraftUpdate

        payload = DraftUpdate(order_no=order_no, order_date=order_date,
                              tracker=tracker, lines=lines, version=version)
        return order_result("update_order_draft", lambda uid, rid: orders.save_draft(
            actor_id=uid, order_id=order_id, version=payload.version,
            order_no=payload.order_no, order_date=payload.order_date,
            tracker=payload.tracker, lines=_draft_lines(payload.lines), request_id=rid,
        ))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False))
    def publish_order_draft(order_id: str, version: int, idempotency_key: str) -> dict[str, Any]:
        """发布手工草稿，激活派工和通知。来源草稿使用明细派工工具。"""
        return order_result("publish_order_draft", lambda uid, rid: orders.publish(
            actor_id=uid, order_id=order_id, version=version,
            idempotency_key=idempotency_key, request_id=rid,
        ))

    @mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
    def delete_order(order_id: str, idempotency_key: str) -> dict[str, Any]:
        """删除允许删除的订单。需要用户明确授权。"""
        def execute(uid: str, rid: str) -> dict[str, Any]:
            orders.delete(actor_id=uid, order_id=order_id,
                          idempotency_key=idempotency_key, request_id=rid)
            return {"deleted": True, "orderId": order_id}
        return read("delete_order", execute)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False))
    def update_order_details(
        order_id: str, version: int, lines: list[DetailFieldsBatchItem],
    ) -> dict[str, Any]:
        """按订单及明细版本保存明细字段；已派工明细只可修改已发数量。"""
        return order_result(
            "update_order_details", lambda uid, rid: source_updates.save_fields_batch(
            actor_id=uid, order_id=order_id, version=version,
            updates=[(line.detail_id, line.detail_version,
                      line.model_dump(exclude={"detail_id", "detail_version"},
                                      exclude_unset=True)) for line in lines],
            request_id=rid,
        ))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False))
    def preview_source_refresh(order_id: str, version: int) -> dict[str, Any]:
        """读取一次外部来源并保存预览快照；确认时使用返回的 previewId。"""
        return read("preview_source_refresh", lambda uid, rid: source_updates.preview(
            actor_id=uid, order_id=order_id, version=version, request_id=rid,
        ))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False))
    def confirm_source_refresh(
        order_id: str, version: int, preview_id: str, idempotency_key: str,
    ) -> dict[str, Any]:
        """将已展示差异的来源预览快照应用到未派工明细。"""
        return order_result("confirm_source_refresh", lambda uid, rid: source_updates.confirm(
            actor_id=uid, order_id=order_id, version=version,
            preview_id=preview_id, idempotency_key=idempotency_key, request_id=rid,
        ))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False))
    def preview_dispatch(order_id: str, version: int, detail_ids: list[str]) -> dict[str, Any]:
        """预检明确选中的未派工明细；确认只使用返回的 previewId。"""
        if not 1 <= len(detail_ids) <= 500 or len(set(detail_ids)) != len(detail_ids):
            raise ValueError("detail IDs must be unique and count 1..500")
        return read("preview_dispatch", lambda uid, rid: dispatch.dispatch_preview(
            actor_id=uid, order_id=order_id, version=version,
            detail_ids=detail_ids, request_id=rid,
        ))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False))
    def confirm_dispatch(
        order_id: str, version: int, preview_id: str, idempotency_key: str,
    ) -> dict[str, Any]:
        """确认选中明细派工，会激活工厂任务与既有通知；重复请求复用幂等键。"""
        return order_result("confirm_dispatch", lambda uid, rid: dispatch.dispatch_confirm(
            actor_id=uid, order_id=order_id, version=version,
            preview_id=preview_id, idempotency_key=idempotency_key, request_id=rid,
        ))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def list_withdrawable_factories(order_id: str) -> dict[str, Any]:
        """列出此订单可撤回工厂及已有发货阻塞状态。"""
        return read("list_withdrawable_factories", lambda uid, _rid: {
            "items": orders.withdrawal_factories(actor_id=uid, order_id=order_id)
        })

    @mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
    def withdraw_factory_dispatch(
        order_id: str, factory_id: str, version: int, idempotency_key: str,
    ) -> dict[str, Any]:
        """按稳定工厂 ID 撤回其全部有效派工；需要用户明确授权。"""
        return order_result("withdraw_factory_dispatch", lambda uid, rid: orders.withdraw_factory(
            actor_id=uid, order_id=order_id, factory_id=factory_id,
            version=version, idempotency_key=idempotency_key, request_id=rid,
        ))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False))
    def complete_order(order_id: str, idempotency_key: str) -> dict[str, Any]:
        """逐条交足且无阻塞时完成订单；重复请求复用幂等键。"""
        return order_result("complete_order", lambda uid, rid: orders.complete(
            actor_id=uid, order_id=order_id, idempotency_key=idempotency_key,
            request_id=rid,
        ))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False))
    def reopen_order(order_id: str, reason: str, idempotency_key: str) -> dict[str, Any]:
        """带明确原因撤销完成状态。"""
        return order_result("reopen_order", lambda uid, rid: orders.reopen(
            actor_id=uid, order_id=order_id, reason=reason,
            idempotency_key=idempotency_key, request_id=rid,
        ))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def list_order_contracts(order_id: str) -> dict[str, Any]:
        """查询各工厂合同资格、缺失资料、现有编号与签订日期。"""
        return read("list_order_contracts", lambda uid, _rid: {
            "items": [ContractFactoryStatusResponse.model_validate(item, from_attributes=True)
                      .model_dump(mode="json", by_alias=True)
                      for item in contracts.list_for_order(actor_id=uid, order_id=order_id)]
        })

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False))
    def export_contract(
        order_id: str, factory_id: str, idempotency_key: str,
        signing_date: date | None = None,
    ) -> dict[str, Any]:
        """按现有资格生成或重复导出合同。首次生成须明确签订日期；下载接入文件工具。"""
        def execute(uid: str, rid: str) -> dict[str, Any]:
            result = contracts.create_export(
                actor_id=uid, order_id=order_id, factory_id=factory_id,
                signing_date=signing_date, idempotency_key=idempotency_key,
                request_id=rid,
            )
            return {"exportId": result.export_id, "contractId": result.contract_id,
                    "contractNo": result.contract_no,
                    "signingDate": result.signing_date.isoformat(),
                    "filename": result.filename, "status": result.status}
        return read("export_contract", execute)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def get_contract_download(export_id: str) -> dict[str, Any]:
        """取得本人网页登录后可下载的合同 Excel 链接及文件校验信息。"""
        def query(uid: str, _rid: str) -> dict[str, Any]:
            contract_id, file_id, filename, size_bytes, sha256 = contracts.download_metadata(
                actor_id=uid, export_id=export_id,
            )
            return {
                "exportId": export_id, "contractId": contract_id, "fileId": file_id,
                **download_descriptor(
                    origin=origin,
                    path=f"/api/v1/admin/contract-exports/{export_id}/download",
                    filename=filename, size_bytes=size_bytes, sha256=sha256,
                ),
            }
        return read("get_contract_download", query)
