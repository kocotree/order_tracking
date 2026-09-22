# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

from common import (
    DATASET, DATASET_HOLDOUT, IMAGES_HOLDOUT, OUT, OUT_HOLDOUT,
    PRICES, RAW, RAW_HOLDOUT, images,
)

# 只判定这几个文本字段；packQuantity 数值本身不判定，箱贴表格的列对齐通过 lines 里的尺码体现
FIELDS = ["factoryName", "productCode", "productName", "color"]

# dataset.csv 的约定：
#   空格   = 还没标注，评分跳过
#   "-"    = 图上没有 / 人也认不出，模型必须返回 null，返回值算「编造」
#   lines 真值 = 该图所有「尺码/方向/数量」三格都填了值的行；
#                三格都填 "-" 表示该图确实没有差异，lines 应为空数组
#   holdout 中单条差异的 size 填 "-" 表示商品本身无尺码；续行 color 是该条差异的颜色
SKIP, ABSENT = "", "-"


def norm_text(value) -> str:
    return re.sub(r"\s+", "", str(value)).upper()


def norm_size(value) -> str:
    if value is None or value == ABSENT:
        return ""
    return re.sub(r"(CM|#)+$", "", re.sub(r"\s+", "", str(value)).upper())


def norm_color(value) -> str:
    return "" if value in (None, "", ABSENT) else norm_text(value)


def norm_qty(value) -> str:
    if value is None or value == "":
        return ""
    return str(int(float(value)))


def load_truth(dataset: Path = DATASET, with_line_color: bool = False) -> dict:
    truth: dict[str, dict] = {}
    broken: dict[str, list] = {}
    for row in csv.DictReader(dataset.open(encoding="utf-8-sig")):
        image = row["image"].strip().removesuffix(".jpg").removesuffix(".jpeg").removesuffix(".png")
        if not image:
            continue
        entry = truth.setdefault(image, {"tags": [], "fields": {f: SKIP for f in FIELDS}, "lines": None})
        if row.get("tags", "").strip():
            entry["tags"] = [t for t in re.split(r"[;,；，]", row["tags"]) if t.strip()]
        for field in FIELDS:
            value = row.get(field, "").strip()
            if value and entry["fields"][field] == SKIP:
                entry["fields"][field] = value
        cells = tuple(row.get(k, "").strip() for k in ("size", "direction", "quantity"))
        if all(c == ABSENT for c in cells):
            entry["lines"] = []
        elif all(cells):
            if entry["lines"] is None:
                entry["lines"] = []
            line = (norm_size(cells[0]), cells[1], norm_qty(cells[2]))
            if with_line_color:
                color = row.get("color", "").strip() or entry["fields"]["color"]
                line = (norm_color(color), *line)
            entry["lines"].append(line)
        elif any(cells):
            broken.setdefault(image, []).append(cells)
    # 只填了一半的行不能当真值：整张图的 lines 退回「未标注」，并明确报出来等人补齐，
    # 不静默丢行、也不替人猜缺的那一格
    for image, cells in broken.items():
        truth[image]["lines"] = None
        print(f"⚠️ {dataset.name}：{image} 有 {len(cells)} 行只填了一半 {cells}，"
              f"该图差异明细按未标注跳过，三格填齐后重跑")
    return truth


def load_runs(raw_dir: Path = RAW) -> list[dict]:
    records = []
    for path in sorted(raw_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    return records


def verdict(truth_value: str, got) -> str:
    if truth_value == SKIP:
        return "skip"
    if truth_value == ABSENT:
        return "ok" if got in (None, "", []) else "invent"
    if got in (None, "", []):
        return "miss"
    return "ok" if norm_text(truth_value) == norm_text(got) else "wrong"


def scored_fields(spec: dict) -> list[str]:
    # 真值表没有「同图所有箱贴颜色」这一列；逐条颜色在 holdout 的 lines 中评分。
    return [f for f in FIELDS if f != "color"] if spec.get("box_color_list") else FIELDS


def valid_box_colors(parsed: dict) -> bool:
    colors = parsed.get("color")
    return isinstance(colors, list) and all(isinstance(color, str) and color.strip() for color in colors)


def lines_verdict(truth_lines, parsed, with_line_color: bool = False) -> tuple[str, set, set]:
    if truth_lines is None:
        return "skip", set(), set()
    if parsed is None:
        return "fail", set(truth_lines), set()
    got = set()
    for line in parsed.get("lines", []):
        detail = (norm_size(line.get("size")), str(line.get("direction") or ""), norm_qty(line.get("quantity")))
        got.add((norm_color(line.get("color")), *detail) if with_line_color else detail)
    want = set(truth_lines)
    if not want and not got:
        return "ok", want, got
    if not want:
        return "invent", want, got
    if not got:
        return "miss", want, got
    return ("ok" if want == got else "wrong"), want, got


def load_prices() -> dict:
    return {k: v for k, v in json.loads(PRICES.read_text(encoding="utf-8")).items() if not k.startswith("_")}


def cost_yuan(stages: list[dict], prices: dict) -> float | None:
    total = 0.0
    for stage in stages:
        price = prices.get(stage["model"])
        if not price or price.get("in") is None or price.get("out") is None:
            return None
        total += stage["in"] / 1e6 * price["in"] + stage["out"] / 1e6 * price["out"]
    return total


def canonical(parsed, with_line_color: bool = False) -> str:
    # 只比会落库的字段。confidence 和 unresolvedFields 每次都在抖，算进去所有方案都「不稳定」
    if parsed is None:
        return "FAIL"
    payload = {f: parsed.get(f) for f in FIELDS}
    if isinstance(payload["color"], list):
        payload["color"] = sorted(norm_color(color) for color in payload["color"])
    payload["diffNoteText"] = parsed.get("diffNoteText")
    payload["lines"] = sorted(
        ((norm_color(l.get("color")),) if with_line_color else ())
        + (norm_size(l.get("size")), str(l.get("direction") or ""), norm_qty(l.get("quantity")))
        for l in parsed.get("lines", [])
    )
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--pipeline", help="只统计这些方案，逗号分隔")
    parser.add_argument("--start", type=int, default=1, help="从第 N 张开始评分（从 1 计数）")
    parser.add_argument("--limit", type=int, default=0, help="只评分前 N 张，可与 --start 合用")
    parser.add_argument("--holdout", action="store_true", help="读取新样本真值和 raw_holdout，逐条比较颜色")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        return

    dataset = DATASET_HOLDOUT if args.holdout else DATASET
    raw_dir = RAW_HOLDOUT if args.holdout else RAW
    out_dir = OUT_HOLDOUT if args.holdout else OUT
    truth = load_truth(dataset, with_line_color=args.holdout)
    records = load_runs(raw_dir)
    if args.pipeline:
        selected_names = set(args.pipeline.split(","))
        unknown = selected_names - {record["pipeline"] for record in records}
        if unknown:
            parser.error(f"没有这些方案的结果：{sorted(unknown)}")
        records = [record for record in records if record["pipeline"] in selected_names]
    if args.start != 1 or args.limit:
        paths = images(IMAGES_HOLDOUT) if args.holdout else images()
        if args.limit:
            paths = paths[: args.limit]
        if not 1 <= args.start <= len(paths):
            parser.error(f"--start 必须在 1 到 {len(paths)} 之间")
        selected = {path.stem for path in paths[args.start - 1 :]}
        truth = {name: entry for name, entry in truth.items() if name in selected}
        records = [record for record in records if Path(record["image"]).stem in selected]
    if not records:
        raise SystemExit(f"{raw_dir} 里没有结果，先跑 bench.py")
    prices = load_prices()

    unlabeled = sum(1 for t in truth.values() for v in t["fields"].values() if v == SKIP)
    unlabeled += sum(1 for t in truth.values() if t["lines"] is None)

    errors: list[dict] = []
    summary: dict[str, dict] = {}
    by_tag: dict[tuple[str, str], list[bool]] = defaultdict(list)
    parsed_by_image: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))

    for record in records:
        name, image, run = record["pipeline"], Path(record["image"]).stem, record["run"]
        entry = truth.get(image)
        if entry is None:
            continue
        stat = summary.setdefault(
            name,
            {"pass": 0, "graded": 0, "need_human": 0, "invent": 0, "field_ok": 0, "field_graded": 0,
             "tokens_in": 0, "tokens_out": 0, "seconds": 0.0, "cost": 0.0, "cost_known": True, "n": 0},
        )
        stat["n"] += 1
        stat["seconds"] += record["elapsed_s"]
        stat["tokens_in"] += sum(s["in"] for s in record["stages"])
        stat["tokens_out"] += sum(s["out"] for s in record["stages"])
        yuan = cost_yuan(record["stages"], prices)
        if yuan is None:
            stat["cost_known"] = False
        else:
            stat["cost"] += yuan

        parsed = record["parsed"]
        parsed_by_image[name][image].add(canonical(parsed, with_line_color=args.holdout))

        dirty = False
        if record["spec"].get("box_color_list") and parsed is not None and not valid_box_colors(parsed):
            dirty = True
            errors.append(
                {"image": image, "pipeline": name, "run": run, "field": "color_schema",
                 "truth": "颜色字符串数组", "got": parsed.get("color"), "verdict": "wrong"}
            )
        for field in scored_fields(record["spec"]):
            result = verdict(entry["fields"][field], (parsed or {}).get(field))
            if result == "skip":
                continue
            stat["field_graded"] += 1
            if result == "ok":
                stat["field_ok"] += 1
            else:
                dirty = True
                if result == "invent":
                    stat["invent"] += 1
                errors.append(
                    {"image": image, "pipeline": name, "run": run, "field": field,
                     "truth": entry["fields"][field], "got": (parsed or {}).get(field), "verdict": result}
                )

        result, want, got = lines_verdict(entry["lines"], parsed, with_line_color=args.holdout)
        if result != "skip":
            stat["graded"] += 1
            if result == "ok":
                stat["pass"] += 1
            else:
                dirty = True
                if result == "invent":
                    stat["invent"] += 1
                errors.append(
                    {"image": image, "pipeline": name, "run": run, "field": "lines",
                     "truth": " / ".join(sorted("".join(t) for t in want)) or "（空）",
                     "got": " / ".join(sorted("".join(g) for g in got)) or "（空）", "verdict": result}
                )
            for tag in entry["tags"]:
                by_tag[(tag, name)].append(result == "ok")
        if dirty:
            stat["need_human"] += 1

    out_dir.mkdir(exist_ok=True)
    write_report(summary, by_tag, parsed_by_image, truth, records, unlabeled, out_dir)
    with (out_dir / "errors.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["image", "pipeline", "run", "field", "truth", "got", "verdict"])
        writer.writeheader()
        writer.writerows(errors)
    print(f"报告写入 {out_dir/'report.md'}，错误清单 {len(errors)} 条写入 {out_dir/'errors.csv'}")


def write_report(summary, by_tag, parsed_by_image, truth, records, unlabeled, out_dir: Path) -> None:
    rows = []
    for name, stat in summary.items():
        stable = [len(v) == 1 for v in parsed_by_image[name].values()]
        rows.append(
            {
                "方案": name,
                "样张通过": f"{stat['pass']}/{stat['graded']}",
                "通过率": f"{stat['pass'] / stat['graded']:.0%}" if stat["graded"] else "—",
                "文本字段": f"{stat['field_ok'] / stat['field_graded']:.0%}" if stat["field_graded"] else "—",
                "需人工": stat["need_human"],
                "编造": stat["invent"],
                "稳定率": f"{sum(stable) / len(stable):.0%}" if stable else "—",
                "token进/出": f"{stat['tokens_in']}/{stat['tokens_out']}",
                "元每千张": f"{stat['cost'] / stat['n'] * 1000:.2f}" if stat["cost_known"] and stat["n"] else "待填单价",
                "秒每张": f"{stat['seconds'] / stat['n']:.1f}" if stat["n"] else "—",
            }
        )
    scores = {name: (stat["pass"] / stat["graded"] if stat["graded"] else -1, stat["graded"])
              for name, stat in summary.items()}
    rows.sort(key=lambda row: scores[row["方案"]], reverse=True)

    lines = [
        f"# 来货出入识别测评报告",
        "",
        f"生成日期：{date.today()}　样张：{len(truth)} 张　结果记录：{len(records)} 条　**未标注格：{unlabeled}**",
        "",
        "## 总表",
        "",
    ]
    header = list(rows[0]) if rows else []
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "---|" * len(header))
    for row in rows:
        lines.append("| " + " | ".join(str(row[h]) for h in header) + " |")

    if any(record["spec"].get("box_color_list") for record in records):
        lines += ["", "注：v3 顶层 color 为箱贴颜色数组，现有真值表未标注该数组，不计入文本字段；holdout 仍逐条评分 lines.color。"]

    tags = sorted({t for t, _ in by_tag})
    names = [r["方案"] for r in rows]
    if tags:
        lines += ["", "## 按难度切片（差异明细通过率）", "", "| tag | " + " | ".join(names) + " |", "|" + "---|" * (len(names) + 1)]
        for tag in tags:
            cells = []
            for name in names:
                got = by_tag.get((tag, name), [])
                cells.append(f"{sum(got)}/{len(got)}" if got else "—")
            lines.append(f"| {tag} | " + " | ".join(cells) + " |")

    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with (out_dir / "report.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)
    print("\n".join(lines))


def selftest() -> None:
    assert norm_size("120CM") == "120" and norm_size("120#") == "120" and norm_size("m") == "M"
    assert norm_size(None) == "" and norm_size("-") == ""
    assert norm_color(None) == "" and norm_color(" 暮山紫 ") == "暮山紫"
    assert norm_qty(None) == "" and norm_qty("3") == "3"
    assert verdict("", None) == "skip"
    assert verdict("-", None) == "ok" and verdict("-", "2023-5-1") == "invent"
    assert verdict("豆豆", None) == "miss" and verdict("豆豆", "豆豆 ") == "ok" and verdict("豆豆", "雄浩") == "wrong"
    assert scored_fields({}) == FIELDS
    assert scored_fields({"box_color_list": True}) == ["factoryName", "productCode", "productName"]
    assert valid_box_colors({"color": []}) and valid_box_colors({"color": ["碧潭灰", "暮山紫"]})
    assert not valid_box_colors({"color": "碧潭灰"}) and not valid_box_colors({"color": [None]})
    assert canonical({"color": ["碧潭灰", "暮山紫"], "lines": []}) == canonical({
        "color": ["暮山紫", "碧潭灰"], "lines": []
    })
    assert lines_verdict(None, {})[0] == "skip"
    assert lines_verdict([], {"lines": []})[0] == "ok"
    assert lines_verdict([], {"lines": [{"size": "M", "direction": "少", "quantity": 1}]})[0] == "invent"
    assert lines_verdict([("M", "少", "1")], {"lines": []})[0] == "miss"
    assert lines_verdict([("M", "少", "1")], {"lines": [{"size": "m", "direction": "少", "quantity": 1}]})[0] == "ok"
    assert lines_verdict([("M", "少", "1")], {"lines": [{"size": "M", "direction": "多", "quantity": 1}]})[0] == "wrong"
    assert lines_verdict([("M", "少", "1")], None)[0] == "fail"
    color_truth = [("暮山紫", "160", "少", "2"), ("云落黑", "160", "少", "9")]
    color_result = {"lines": [
        {"color": "暮山紫", "size": "160", "direction": "少", "quantity": 2},
        {"color": "云落黑", "size": "160", "direction": "少", "quantity": 9},
    ]}
    assert lines_verdict(color_truth, color_result, with_line_color=True)[0] == "ok"
    color_result["lines"][1]["color"] = "暮山紫"
    assert lines_verdict(color_truth, color_result, with_line_color=True)[0] == "wrong"
    assert lines_verdict([("兔兔奶糖", "", "多", "5")], {
        "lines": [{"color": "兔兔奶糖", "size": None, "direction": "多", "quantity": 5}]
    }, with_line_color=True)[0] == "ok"
    assert cost_yuan([{"model": "x", "in": 1_000_000, "out": 0}], {"x": {"in": 2.0, "out": 8.0}}) == 2.0
    assert cost_yuan([{"model": "x", "in": 1, "out": 1}], {"x": {"in": None, "out": None}}) is None
    print("selftest ok")


if __name__ == "__main__":
    main()
