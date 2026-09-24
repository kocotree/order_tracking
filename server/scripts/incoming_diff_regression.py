import argparse
import csv
import hashlib
import json
import runpy
import sys
from collections import defaultdict
from pathlib import Path

from app.adapters.vision import MODEL

PIPELINE = "s1_35flash_v12_boxes"
PROMPT_NAME = "single_v12_boxes.txt"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("experiment_dir", type=Path)
    args = parser.parse_args()
    directory = args.experiment_dir.resolve()
    controlled = (Path(__file__).resolve().parents[1] / "app" / "modules"
                  / "incoming_differences" / "prompts" / PROMPT_NAME)
    original = directory / "prompts" / PROMPT_NAME
    prompt_digest = hashlib.sha256(controlled.read_bytes()).hexdigest()
    if prompt_digest != hashlib.sha256(original.read_bytes()).hexdigest():
        parser.error("实验提示词与正式资源不一致")
    sys.path.insert(0, str(directory))
    score = runpy.run_path(str(directory / "score.py"))
    truth = score["load_truth"](directory / "dataset_holdout.csv", with_line_color=True)
    images = {path.stem for path in (directory / "images_holdout").iterdir()
              if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}}
    if images != set(truth):
        parser.error(
            f"图片与标注不一致：缺标注 {sorted(images - set(truth))}，"
            f"缺图片 {sorted(set(truth) - images)}"
        )
    if any(any(value == "" for value in entry["fields"].values()) or entry["lines"] is None
           for entry in truth.values()):
        parser.error("人工标注有空字段或不完整差异行，停止统计准确率")
    records = [record for record in score["load_runs"](directory / "raw_holdout")
               if record["pipeline"] == PIPELINE]
    expected = {(image, run) for image in images for run in (1, 2, 3)}
    observed = {(Path(record["image"]).stem, record["run"]) for record in records}
    if observed != expected or len(records) != len(expected):
        parser.error("固定样本必须每张图片各有三次结果，且不能有重复记录")
    if any(record["spec"].get("vision") != MODEL
           or record["spec"].get("prompt") != PROMPT_NAME.removesuffix(".txt")
           for record in records):
        parser.error("结果中的模型或提示词与固定配置不一致")

    rows: list[dict[str, str | int]] = []
    canonical: dict[str, set[str]] = defaultdict(set)
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for record in records:
        image = Path(record["image"]).stem
        run = record["run"]
        parsed = record["parsed"]
        canonical[image].add(score["canonical"](parsed, with_line_color=True))
        entry = truth[image]
        for field in ("factoryName", "productCode", "productName"):
            got = (parsed or {}).get(field)
            verdict = score["verdict"](entry["fields"][field], got)
            rows.append({"image": image, "run": run, "field": field,
                         "truth": entry["fields"][field], "got": "" if got is None else str(got),
                         "verdict": verdict})
            counts[field][1] += 1
            counts[field][0] += verdict == "ok"
        verdict, want, got = score["lines_verdict"](
            entry["lines"], parsed, with_line_color=True
        )
        rows.append({"image": image, "run": run, "field": "lines",
                     "truth": json.dumps(sorted(want), ensure_ascii=False),
                     "got": json.dumps(sorted(got), ensure_ascii=False),
                     "verdict": verdict})
        counts["lines"][1] += 1
        counts["lines"][0] += verdict == "ok"

    output = directory / "out_fixed_v12"
    output.mkdir(exist_ok=True)
    headers = ("image", "run", "field", "truth", "got", "verdict")
    for name, selected in (("field_results.csv", rows),
                           ("errors.csv", [row for row in rows if row["verdict"] != "ok"])):
        with (output / name).open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            writer.writerows(selected)
    stable = sum(len(values) == 1 for values in canonical.values())
    lines = [f"固定模型：{MODEL}；提示词 SHA-256：{prompt_digest}",
             f"标注完整性：{len(images)} 张图，空标注 0；每图 3 次，共 {len(records)} 次。",
             "字段准确率（严格对照人工标注）："]
    lines += [f"- {field}: {correct}/{total} ({correct / total:.1%})"
              for field, (correct, total) in counts.items()]
    lines += [f"- 重复运行稳定：{stable}/{len(images)} ({stable / len(images):.1%})",
              f"- 错误：{sum(row['verdict'] != 'ok' for row in rows)} 条，见 errors.csv。",
              "箱贴 boxes 与 diffNoteText 无完整人工真值，未计准确率。"]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
