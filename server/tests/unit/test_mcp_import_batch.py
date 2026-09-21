from types import SimpleNamespace

from app.mcp.order_tools import register_order_tools


class Tools:
    def __init__(self) -> None:
        self.functions = {}

    def tool(self, **_kwargs):
        def collect(function):
            self.functions[function.__name__] = function
            return function
        return collect


class Imports:
    def __init__(self) -> None:
        self.confirmed = []

    def get_candidate(self, *, candidate_id, **_kwargs):
        return SimpleNamespace(
            status="PENDING", version=1,
            validation_state="INVALID" if candidate_id == "bad" else "READY",
            imported_order_id=None,
        )

    def confirm_candidate(self, *, candidate_id, **_kwargs):
        self.confirmed.append(candidate_id)
        if candidate_id == "conflict":
            raise ValueError("candidate version changed")
        return f"order-{candidate_id}"


def test_import_batch_prechecks_all_and_reports_committed_items() -> None:
    tools = Tools()
    imports = Imports()
    register_order_tools(
        tools, lambda _name, callback: callback("admin", "request"),
        orders=object(), imports=imports, source_updates=object(),
        dispatch=object(), contracts=object(), origin="http://testserver",
    )
    run = tools.functions["import_candidates"]
    targets = [{"candidateId": "good", "version": 1},
               {"candidateId": "bad", "version": 1}]
    blocked = run(targets)
    assert [item["status"] for item in blocked["items"]] == ["notExecuted", "notExecuted"]
    assert imports.confirmed == []

    partial = run(targets, allow_partial=True)
    assert [item["status"] for item in partial["items"]] == ["succeeded", "notExecuted"]
    assert imports.confirmed == ["good"]

    interrupted = run([{"candidateId": "good", "version": 1},
                       {"candidateId": "conflict", "version": 1},
                       {"candidateId": "last", "version": 1}])
    assert [item["status"] for item in interrupted["items"]] == [
        "succeeded", "failed", "notExecuted",
    ]
    assert imports.confirmed == ["good", "good", "conflict"]
