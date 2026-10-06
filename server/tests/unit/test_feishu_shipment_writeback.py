import json
from copy import deepcopy

import httpx
import pytest

from app.adapters.order_source import FeishuOrderSourceConfig
from app.adapters.shipment_writeback import FeishuShipmentWriter
from app.modules.shipment_writeback.periods import month_stages

BASELINE = "ROUND(SUM(IFBLANK(bitable::$table[table].$field[old],0)),0)"


class RemoteBase:
    def __init__(self):
        self.fields = [
            {"field_id": "old", "field_name": "26.10.26-10.31出货", "type": 2},
            {"field_id": "total", "field_name": "出货总数", "type": 20,
             "property": {"formula_expression": BASELINE, "formatter": "0"},
             "description": {"text": "保留描述"}, "ui_type": "Formula"},
        ]
        self.records = {"record-a": {"订单编号": [{"text": "S07-ORDER-A"}],
                                     "下单明细ID": "detail-a"}}
        self.fail_record = False
        self.fail_create = False
        self.fail_formula_before = False
        self.create_tokens = {}

    def request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("tenant_access_token/internal"):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "test-token"})
        body = json.loads(request.content) if request.content else {}
        if path.endswith("/fields"):
            if request.method == "GET":
                return httpx.Response(200, json={"code": 0, "data": {
                    "items": deepcopy(self.fields), "has_more": False,
                }})
            token = request.url.params.get("client_token")
            if self.fail_create:
                self.fail_create = False
                self.create_tokens[token] = body
                raise httpx.ReadTimeout("creation response lost before read visibility")
            if self.create_tokens:
                assert token is not None and token in self.create_tokens
            created = {**body, "field_id": f"new{len(self.fields)}"}
            self.fields.append(created)
            return httpx.Response(200, json={"code": 0, "data": {"field": created}})
        if path.endswith("/fields/total") and request.method == "PUT":
            if self.fail_formula_before:
                self.fail_formula_before = False
                raise httpx.ReadTimeout("formula request interrupted")
            self.fields[1] = {**body, "field_id": "total"}
            return httpx.Response(200, json={"code": 0, "data": {"field": self.fields[1]}})
        if "/records/" in path:
            record_id = path.rsplit("/", 1)[1]
            if request.method == "PUT":
                self.records[record_id].update(body["fields"])
                if self.fail_record:
                    self.fail_record = False
                    raise httpx.ReadTimeout("simulated lost response")
            return httpx.Response(200, json={"code": 0, "data": {"record": {
                "record_id": record_id, "fields": deepcopy(self.records[record_id]),
            }}})
        raise AssertionError(f"unexpected request: {request.method} {path}")

    def writer(self):
        return FeishuShipmentWriter(
            FeishuOrderSourceConfig(app_id="app", app_secret="secret", app_token="base",
                                   table_id="table", view_id="view",
                                   field_ids={"订单编号": "order", "下单明细ID": "detail"}),
            total_field_id="total", baseline_formula=BASELINE,
            transport=httpx.MockTransport(self.request),
        )


def test_month_preparation_is_idempotent_and_preserves_formula_properties():
    remote = RemoteBase()
    writer = remote.writer()
    state = {}
    stages = month_stages(2026, 11)
    writer.prepare_month(stages, state, lambda value: state.update(deepcopy(value)))
    writer.prepare_month(stages, state, lambda value: state.update(deepcopy(value)))
    assert [field["field_name"] for field in remote.fields[2:]] == [stage.name for stage in stages]
    formula = remote.fields[1]["property"]["formula_expression"]
    assert formula == (
        "ROUND(SUM(IFBLANK(bitable::$table[table].$field[old],0),"
        "IFBLANK(bitable::$table[table].$field[new2],0),"
        "IFBLANK(bitable::$table[table].$field[new3],0),"
        "IFBLANK(bitable::$table[table].$field[new4],0),"
        "IFBLANK(bitable::$table[table].$field[new5],0)),0)"
    )
    assert remote.fields[1]["property"]["formatter"] == "0"
    assert remote.fields[1]["description"] == {"text": "保留描述"}


def test_unknown_write_result_recovers_by_reading_absolute_quantity():
    remote = RemoteBase()
    remote.fields.extend([
        {"field_id": "order", "field_name": "订单编号", "type": 1},
        {"field_id": "detail", "field_name": "下单明细ID", "type": 1005},
    ])
    writer = remote.writer()
    stage = month_stages(2026, 10)[-1]
    identity = {"order_no": "S07-ORDER-A", "detail_id": "detail-a"}
    previous = []
    remote.fail_record = True
    with pytest.raises(httpx.ReadTimeout):
        writer.write_row(stage, "old", "record-a", identity, 12, previous.append)
    writer.write_row(stage, "old", "record-a", identity, 12, previous.append)
    assert remote.records["record-a"][stage.name] == 12
    assert remote.records["record-a"]["下单明细ID"] == "detail-a"
    assert previous[0] is None


def test_uncertain_creation_reuses_persisted_idempotency_token():
    remote = RemoteBase()
    remote.fail_create = True
    state = {}
    stages = month_stages(2026, 11)
    with pytest.raises(httpx.ReadTimeout):
        remote.writer().prepare_month(stages, state, lambda v: state.update(deepcopy(v)))
    # 只继续首个创建请求，验证重启后的幂等令牌与未完成请求相同。
    remote.writer().prepare_month(stages[:1], state, lambda v: state.update(deepcopy(v)))
    assert len([f for f in remote.fields if f["field_name"] == stages[0].name]) == 1


@pytest.mark.parametrize("fault", ["formula", "duplicate", "type", "overlap", "record"])
def test_drift_fails_without_overwriting_unknown_data(fault):
    remote = RemoteBase()
    stages = month_stages(2026, 11)
    if fault == "formula":
        remote.fields[1]["property"]["formula_expression"] = "SUM(1,2)"
    elif fault == "duplicate":
        remote.fields.extend([
            {"field_id": "a", "field_name": stages[0].name, "type": 2},
            {"field_id": "b", "field_name": "26.11.1-11.8出货", "type": 2},
        ])
    elif fault == "type":
        remote.fields.append({"field_id": "a", "field_name": stages[0].name, "type": 1})
    elif fault == "overlap":
        remote.fields.append({"field_id": "a", "field_name": "26.11.1-11.7出货", "type": 2})
    else:
        remote.fields.extend([
            {"field_id": "order", "field_name": "订单编号", "type": 1},
            {"field_id": "detail", "field_name": "下单明细ID", "type": 1005},
        ])
        remote.records["record-a"]["下单明细ID"] = "another-detail"
    before = deepcopy(remote.fields)
    with pytest.raises(ValueError, match="shipment_writeback"):
        if fault == "record":
            remote.writer().write_row(month_stages(2026, 10)[-1], "old", "record-a",
                                      {"order_no": "S07-ORDER-A", "detail_id": "detail-a"},
                                      12, lambda value: None)
        else:
            remote.writer().prepare_month(stages, {}, lambda value: None)
    assert remote.fields == before


def test_next_month_recovers_previous_formula_intent_before_extending():
    remote = RemoteBase()
    state = {}

    def save(value):
        state.clear()
        state.update(deepcopy(value))

    remote.fail_formula_before = True
    with pytest.raises(httpx.ReadTimeout):
        remote.writer().prepare_month(month_stages(2026, 11), state, save)
    remote.writer().prepare_month(month_stages(2026, 12), state, save)
    assert "pending_formula" not in state
    assert len(remote.fields) == 11
    assert remote.fields[1]["property"]["formula_expression"].count("IFBLANK(") == 10
