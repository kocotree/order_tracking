from collections.abc import Callable
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.api.repairs import (
    RepairSummaryListResponse,
    RepairSummaryResponse,
    _archive_response,
    _preview_response,
    _repair_response,
)
from app.db.models import RepairPreview, StoredFile
from app.mcp.files import AgentFile, FileTransferError, download_descriptor, fetch_file
from app.modules.repairs.confirmation import (
    RepairConfirmationConflict,
    RepairConfirmationNotFound,
    RepairConfirmationService,
)
from app.modules.repairs.periods import RepairPeriodService
from app.modules.repairs.preview import (
    RepairPreviewExpired,
    RepairPreviewNotFound,
    RepairPreviewService,
)
from app.modules.repairs.returns import RepairReturnService
from app.modules.repairs.workbook import InspectionWorkbookValidationError
from app.modules.repairs.workflow import (
    XLSX_MIME,
    RepairWorkflowService,
    RepairWorkflowValidationError,
)

Read = Callable[[str, Callable[[str, str], Any]], dict[str, Any]]


def register_repair_tools(
    mcp: MCPServer,
    *,
    read: Read,
    workflow: RepairWorkflowService,
    previews: RepairPreviewService,
    confirmations: RepairConfirmationService,
    returns: RepairReturnService,
    sessions: sessionmaker[Session],
    origin: str,
    file_hosts: frozenset[str],
) -> None:
    periods = RepairPeriodService(sessions)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def list_repair_periods(
        keyword: str = "",
        status: str = "all",
        period: str = "",
        factories: list[str] | None = None,
        sort_by: str = "",
        sort_order: str = "asc",
        page: int = 1,
        page_size: int = 10,
    ) -> dict[str, Any]:
        """按网页相同筛选和分页查询工厂返修周期。"""
        if page < 1 or not 1 <= page_size <= 100 or sort_order not in {"asc", "desc"}:
            raise ValueError("无效的分页或排序参数")
        def query(_user_id: str, _request_id: str) -> RepairSummaryListResponse:
            rows, total = periods.page(
                keyword=keyword, status=status, period=period, factories=factories,
                sort_by=sort_by, sort_order=sort_order, page=page, page_size=page_size,
            )
            return RepairSummaryListResponse(
                items=[RepairSummaryResponse(**row) for row in rows],
                total=total, page=page, page_size=page_size,
            )
        return read("list_repair_periods", query)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def get_repair(repair_id: str) -> dict[str, Any]:
        """查询返修周期汇总、质检附件和工厂发回记录。"""
        return read("get_repair", lambda _user_id, _request_id: _repair_response(
            periods.get(repair_id)
        ))

    @mcp.tool(
        meta={"openai/fileParams": ["files"]},
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, openWorldHint=True
        ),
    )
    def upload_repair_workbook(files: list[AgentFile]) -> dict[str, Any]:
        """上传最多 20 份标准 .xlsx 质检单并生成预览；此操作不创建工厂任务。"""
        if not 1 <= len(files) <= 20:
            raise ValueError("每批须上传 1 至 20 份质检 Excel")

        def upload(user_id: str, _request_id: str) -> dict[str, Any]:
            items: list[dict[str, Any]] = []
            for file in files:
                item: dict[str, Any] = {
                    "fileId": file.file_id,
                    "filename": file.file_name,
                }
                try:
                    content = fetch_file(file, file_hosts)
                    preview = workflow.create_preview(
                        content=content,
                        filename=file.file_name or "",
                        mime_type=XLSX_MIME,
                        uploaded_by=user_id,
                    )
                    item.update(
                        previewId=preview.preview_id,
                        status=preview.status,
                        validationErrors=list(preview.validation_errors),
                        factoryId=preview.factory_id,
                        sizeBytes=len(content),
                    )
                except (
                    FileTransferError,
                    InspectionWorkbookValidationError,
                    RepairWorkflowValidationError,
                ) as error:
                    item.update(status="ERROR", error=str(error))
                    if isinstance(error, InspectionWorkbookValidationError):
                        item["validationErrors"] = list(error.issues)
                items.append(item)
            return {"items": items, "canConfirmAll": all(
                item["status"] == "READY" for item in items
            )}
        return read("upload_repair_workbook", upload)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def get_repair_preview(preview_id: str) -> dict[str, Any]:
        """回读质检预览、匹配结果和阻塞原因。"""
        return read("get_repair_preview", lambda _user_id, _request_id: _preview_response(
            previews.get(preview_id)
        ))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    def confirm_repair_previews(
        items: list[dict[str, str]], allow_partial: bool = False
    ) -> dict[str, Any]:
        """逐份确认预览；默认预检失败即停止。每项须提供 previewId 和 idempotencyKey。"""
        if not 1 <= len(items) <= 20:
            raise ValueError("每批须确认 1 至 20 份质检 Excel")
        if any(set(item) != {"previewId", "idempotencyKey"} for item in items):
            raise ValueError("每项需要 previewId 和 idempotencyKey")
        if len({item["previewId"] for item in items}) != len(items):
            raise ValueError("同一预览不能在批次内重复")

        def confirm(user_id: str, _request_id: str) -> dict[str, Any]:
            results: list[dict[str, Any]] = []
            for item in items:
                result: dict[str, Any] = {"previewId": item["previewId"]}
                try:
                    with sessions() as session:
                        stored_preview = session.get(RepairPreview, item["previewId"])
                    if not (stored_preview and stored_preview.status == "CONFIRMED"):
                        preview = previews.get(item["previewId"])
                        if preview.status != "READY" or preview.validation_errors:
                            raise RepairConfirmationConflict("当前预览不可确认")
                    result["status"] = "READY"
                except (
                    RepairPreviewNotFound, RepairPreviewExpired, RepairConfirmationConflict
                ) as error:
                    result.update(status="INVALID", error=str(error))
                results.append(result)
            if not allow_partial and any(result["status"] != "READY" for result in results):
                for result in results:
                    if result["status"] == "READY":
                        result["status"] = "NOT_ATTEMPTED"
                return {"items": results}
            interrupted = False
            for item, result in zip(items, results, strict=True):
                if result["status"] != "READY":
                    continue
                if interrupted:
                    result["status"] = "NOT_ATTEMPTED"
                    continue
                try:
                    repair = confirmations.confirm(
                        preview_id=item["previewId"], confirmed_by=user_id,
                        idempotency_key=item["idempotencyKey"],
                    )
                    result.update(status="CREATED", repairId=repair.repair_id,
                                  repairNo=repair.repair_no)
                except (RepairConfirmationConflict, RepairConfirmationNotFound) as error:
                    result.update(status="FAILED", error=str(error))
                    interrupted = not allow_partial
                except (SQLAlchemyError, TimeoutError):
                    result.update(status="NEEDS_RECONCILIATION",
                                  error="结果待核实，请使用原幂等键重试")
                    interrupted = True
            return {"items": results}
        return read("confirm_repair_previews", confirm)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def archive_repair_period(repair_id: str, idempotency_key: str) -> dict[str, Any]:
        """已完成的整周期归档；保留质检单及发回历史。"""
        return read("archive_repair_period", lambda user_id, _request_id: _archive_response(
            returns.archive(
                repair_id=repair_id, archived_by=user_id, idempotency_key=idempotency_key
            )
        ))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def get_repair_download(repair_id: str, file_id: int) -> dict[str, Any]:
        """取得本人网页登录后可直接下载的原始质检 Excel 链接。"""
        def query(_user_id: str, _request_id: str) -> dict[str, Any]:
            period = periods.get(repair_id)
            attachment = next(
                (entry for entry in period.attachments if entry.file_id == file_id), None
            )
            if attachment is None:
                raise ValueError("返修附件不存在")
            with sessions() as session:
                stored = session.get(StoredFile, file_id)
                if stored is None:
                    raise ValueError("返修附件不存在")
                return {
                    "fileId": file_id,
                    "repairId": period.repair_id,
                    **download_descriptor(
                        origin=origin,
                        path=f"/api/v1/agent-files/{file_id}/download",
                        filename=attachment.filename,
                        size_bytes=stored.size_bytes,
                        sha256=stored.content_sha256,
                    ),
                }
        return read("get_repair_download", query)
