"""Read-only prospective net shipment projection; never modifies source facts."""

from datetime import datetime
from typing import Any

from app.modules.shipment_writeback.periods import SHANGHAI, Stage, month_stages


def project_returns(
    *, facts: list[dict[str, Any]], returns: list[dict[str, Any]],
    first_submitted: dict[str, datetime], activation: datetime, cutoff: datetime,
    source_scope: str, baseline: dict[str, Any], after: datetime | None = None,
) -> list[dict[str, Any]]:
    if any(t.tzinfo is None for t in (activation, cutoff, *( [after] if after else []))):
        raise ValueError("timezone required")
    if cutoff < activation or (after and not activation <= after <= cutoff):
        raise ValueError("invalid projection interval")
    start = datetime.fromisoformat(baseline["stage"]).date()
    stages: list[Stage] = []
    year, month = start.year, start.month
    while (year, month) <= (cutoff.astimezone(SHANGHAI).year, cutoff.astimezone(SHANGHAI).month):
        stages.extend(s for s in month_stages(year, month, midnight_from=start)
                      if s.first >= start and s.since <= cutoff)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    eligible = {root for root, at in first_submitted.items() if activation <= at < cutoff}
    visible = sorted((f for f in facts if f["root_id"] in eligible
                      and activation <= f["occurred_at"] < cutoff),
                     key=lambda f: (f["occurred_at"], f.get("id", 0)))
    rows: dict[str, dict[str, dict[str, Any]]] = {s.key: {} for s in stages}
    changed: set[str] = set()
    allocation: dict[str, tuple[str, dict[int, dict[str, Any]]]] = {}

    def add(stage: str, line: dict[str, Any], quantity: int) -> None:
        if line.get("source_scope", source_scope) is None:
            raise ValueError("source identity missing")
        if line.get("source_scope", source_scope) != source_scope:
            return
        if not all(line.get(k) for k in ("record_id", "order_no", "detail_id")):
            raise ValueError("source identity missing")
        record = line["record_id"]
        identity = {k: line[k] for k in ("record_id", "order_no", "detail_id")}
        prior = rows[stage].setdefault(record, {**identity, "quantity": 0})
        if any(prior[k] != identity[k] for k in identity):
            raise ValueError("source identity changed")
        prior["quantity"] += quantity

    for line in baseline["rows"]:
        add(baseline["stage"], line, line["quantity"])
    for stage in stages:
        latest = {}
        for f in visible:
            if stage.since <= f["occurred_at"] < min(stage.until, cutoff):
                latest[f["root_id"]] = f
                if after is None or f["occurred_at"] >= after:
                    changed.add(stage.key)
        for root, f in latest.items():
            if root in allocation:
                continue
            lines = {line["assignment_id"]: dict(line) for line in f["lines"]}
            if len(lines) != len(f["lines"]):
                raise ValueError("duplicate assignment")
            for line in lines.values():
                if type(line["quantity"]) is not int or line["quantity"] < 0:
                    raise ValueError("invalid shipment quantity")
                add(stage.key, line, line["quantity"] if f["status"] == "SHIPPED" else 0)
            if f["status"] == "SHIPPED":
                allocation[root] = (stage.key, lines)
    deducted: dict[tuple[str, int], int] = {}
    for event in returns:
        root, assignment = event["root_id"], event["assignment_id"]
        if root not in eligible or event["occurred_at"] >= cutoff:
            continue
        if root not in allocation or assignment not in allocation[root][1]:
            raise ValueError("return source missing")
        stage_key, lines = allocation[root]
        line = lines[assignment]
        key = (root, assignment)
        quantity = event["quantity"]
        deducted[key] = deducted.get(key, 0) + quantity
        if type(quantity) is not int or quantity <= 0 or deducted[key] > line["quantity"]:
            raise ValueError("return exceeds reported quantity")
        add(stage_key, line, -quantity)
        if after is None or event["occurred_at"] >= after:
            changed.add(stage_key)
    # Always reconcile the closing period as well as the current period, even if
    # no event happened since the cursor (e.g. withdrawal just before midnight).
    changed.update(s.key for s in stages[-2:])
    return [dict(stage=s.key, field=s.name, cutoff=cutoff.astimezone(SHANGHAI).isoformat(),
                 rows=sorted(rows[s.key].values(), key=lambda r: r["record_id"]))
            for s in stages if after is None or s.key in changed]
