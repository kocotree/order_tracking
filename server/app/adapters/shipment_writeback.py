import re
from collections.abc import Callable
from copy import deepcopy
from datetime import date
from time import monotonic
from typing import Any, Literal
from urllib.parse import quote
from uuid import uuid4

import httpx

from app.adapters.order_source import AppCredentialFeishuOrderSource, FeishuOrderSourceConfig
from app.modules.shipment_writeback.periods import Stage


class FeishuShipmentWriter:
    def __init__(
        self, config: FeishuOrderSourceConfig, *, total_field_id: str,
        baseline_formula: str, transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.config = config
        self.total_field_id = total_field_id
        self.baseline_formula = baseline_formula
        self.transport = transport
        self._token = ""
        self._expires = 0.0
        self._prefix = (f"/open-apis/bitable/v1/apps/{quote(config.app_token, safe='')}"
                        f"/tables/{quote(config.table_id, safe='')}")

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        with httpx.Client(base_url=self.config.base_url, timeout=30, transport=self.transport) as c:
            if monotonic() >= self._expires:
                auth = c.post("/open-apis/auth/v3/tenant_access_token/internal", json={
                    "app_id": self.config.app_id, "app_secret": self.config.app_secret,
                })
                if auth.status_code != 200 or auth.json().get("code") != 0:
                    raise ValueError("shipment_writeback_auth_failed")
                self._token = auth.json()["tenant_access_token"]
                self._expires = monotonic() + 60
            response = c.request(method, self._prefix + path,
                                 headers={"Authorization": f"Bearer {self._token}"}, **kwargs)
            if response.status_code != 200:
                raise ValueError(f"shipment_writeback_http_{response.status_code}")
            payload = response.json()
            if payload.get("code") != 0:
                raise ValueError(f"shipment_writeback_api_{payload.get('code')}")
            data: dict[str, Any] = payload["data"]
            return data

    def fields(self) -> list[dict[str, Any]]:
        result = []
        params: dict[str, str | int] = {"page_size": 100}
        tokens = set()
        while True:
            data = self._request("GET", "/fields", params=params)
            result.extend(data["items"])
            if not data["has_more"]:
                break
            token = data.get("page_token")
            if not isinstance(token, str) or not token or token in tokens:
                raise ValueError("shipment_writeback_invalid_pagination")
            tokens.add(token)
            params["page_token"] = token
        return result

    def _stage_fields(
        self, stages: list[Stage], fields: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        expected = {(stage.first, stage.last): stage.key for stage in stages}
        result = {}
        for field in fields:
            match = re.fullmatch(r"(\d{2})\.(\d{1,2})\.(\d{1,2})-(\d{1,2})\.(\d{1,2})出货",
                                 field["field_name"])
            if not match:
                continue
            year, month, day, end_month, end_day = map(int, match.groups())
            first, last = date(2000 + year, month, day), date(2000 + year, end_month, end_day)
            if first > last:
                raise ValueError("shipment_writeback_invalid_field_range")
            if last < stages[0].first or first > stages[-1].last:
                continue
            key = expected.get((first, last))
            if key is None or key in result or field["type"] != 2:
                raise ValueError("shipment_writeback_field_conflict")
            result[key] = field
        return result

    def prepare_month(
        self, stages: list[Stage], state: dict[str, Any],
        save: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        if (not self.total_field_id or not self.baseline_formula.startswith("ROUND(SUM(")
                or not self.baseline_formula.endswith("),0)")):
            raise ValueError("shipment_writeback_formula_baseline_required")
        state = deepcopy(state)
        if state.get("total_field_id", self.total_field_id) != self.total_field_id:
            raise ValueError("shipment_writeback_total_field_changed")
        state["total_field_id"] = self.total_field_id
        fields = self.fields()
        total = next((f for f in fields if f["field_id"] == self.total_field_id), None)
        if total is None or total["type"] != 20 or total["field_name"] != "出货总数":
            raise ValueError("shipment_writeback_total_field_changed")
        current = total["property"]["formula_expression"]
        expected = state.get("formula", self.baseline_formula)
        pending = state.get("pending_formula")
        if current != expected and current != pending:
            raise ValueError("shipment_writeback_formula_drift")
        if pending is not None:
            self._write_formula(total, current, pending)
            state["formula"] = pending
            state.pop("pending_formula")
            save(state)
            current = pending
            total = next(f for f in self.fields() if f["field_id"] == self.total_field_id)
        resolved = self._stage_fields(stages, fields)
        known = state.setdefault("fields", {})
        for stage in stages:
            field = resolved.get(stage.key)
            if stage.key in known and (field is None or field["field_id"] != known[stage.key]):
                raise ValueError("shipment_writeback_field_identity_changed")
            if field is None:
                token = state.setdefault("create_tokens", {}).setdefault(stage.key, str(uuid4()))
                save(state)
                self._request("POST", "/fields", params={"client_token": token}, json={
                    "field_name": stage.name, "type": 2, "property": {"formatter": "0"},
                })
                resolved = self._stage_fields(stages, self.fields())
                field = resolved.get(stage.key)
                if field is None:
                    raise ValueError("shipment_writeback_field_not_created")
            known[stage.key] = field["field_id"]
            save(state)
        additions = []
        for stage in stages:
            reference = f"bitable::$table[{self.config.table_id}].$field[{known[stage.key]}]"
            if current.count(reference) > 1:
                raise ValueError("shipment_writeback_duplicate_formula_reference")
            if reference not in current:
                additions.append(f"IFBLANK({reference},0)")
        if additions:
            target = current[:-4] + "," + ",".join(additions) + "),0)"
            state["pending_formula"] = target
            state["formula"] = current
            save(state)
            self._write_formula(total, current, target)
            state["formula"] = target
            state.pop("pending_formula")
            save(state)
        return state

    def _write_formula(self, total: dict[str, Any], before: str, after: str) -> None:
        fresh = next(f for f in self.fields() if f["field_id"] == self.total_field_id)
        value = fresh["property"]["formula_expression"]
        if value == after:
            return
        if value != before or fresh != total:
            raise ValueError("shipment_writeback_formula_drift")
        body = {key: deepcopy(fresh[key]) for key in
                ("field_name", "type", "property", "description", "ui_type") if key in fresh}
        body["property"]["formula_expression"] = after
        self._request("PUT", f"/fields/{quote(self.total_field_id, safe='')}", json=body)
        readback = next(f for f in self.fields() if f["field_id"] == self.total_field_id)
        if readback["property"]["formula_expression"] != after:
            raise ValueError("shipment_writeback_formula_readback_mismatch")

    def write_row(
        self, stage: Stage, field_id: str, record_id: str, identity: dict[str, Any],
        quantity: int, save_before: Callable[[Any], None],
    ) -> Literal["WRITTEN", "SKIPPED_EXISTING"]:
        if type(quantity) is not int or quantity < 0:
            raise ValueError("shipment_writeback_invalid_quantity")
        fields = self.fields()
        field = self._stage_fields([stage], fields).get(stage.key)
        if field is None or field["field_id"] != field_id:
            raise ValueError("shipment_writeback_field_identity_changed")
        by_id = {f["field_id"]: f["field_name"] for f in fields}
        identity_names = {key: by_id[self.config.field_ids[name]] for key, name in
                          (("order_no", "订单编号"), ("detail_id", "下单明细ID"))}
        path = f"/records/{quote(record_id, safe='')}"

        def read() -> dict[str, Any]:
            record = self._request("GET", path, params={"automatic_fields": "true"})["record"]
            if record["record_id"] != record_id:
                raise ValueError("shipment_writeback_record_identity_changed")
            values: dict[str, Any] = record["fields"]
            for key, name in identity_names.items():
                if AppCredentialFeishuOrderSource._text(values.get(name)) != identity[key]:
                    raise ValueError("shipment_writeback_record_identity_changed")
            return values

        current = read().get(field["field_name"])
        save_before(current)
        if current is not None:
            return "SKIPPED_EXISTING"
        # shortcut: 复查后仍有并发窗口，飞书提供条件更新接口时改用原子写入。
        current = read().get(field["field_name"])
        if current is not None:
            save_before(current)
            return "SKIPPED_EXISTING"
        self._request("PUT", path, json={"fields": {field["field_name"]: quantity}})
        readback = read().get(field["field_name"])
        if readback != quantity or isinstance(readback, bool):
            raise ValueError("shipment_writeback_record_readback_mismatch")
        return "WRITTEN"
