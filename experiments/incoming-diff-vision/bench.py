# /// script
# requires-python = ">=3.11"
# dependencies = ["openai>=1.40", "pillow>=10"]
# ///

from __future__ import annotations

import argparse
import json
import time

from openai import OpenAI

from common import BASE_URL, IMAGES_HOLDOUT, RAW, RAW_HOLDOUT, images, load_api_key
from pipelines import PIPELINES, run_pipeline


def done_keys(path) -> set[tuple[str, int]]:
    # 断点续跑：中断后重跑不重复付已经跑过的那些图的钱
    if not path.exists():
        return set()
    keys = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            keys.add((record["image"], record["run"]))
    return keys


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pipeline", required=True, help="方案名，逗号分隔，或 all")
    parser.add_argument("--runs", type=int, default=1, help="每张图跑几遍，测稳定性用 3")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 张，调链路用")
    parser.add_argument("--start", type=int, default=1, help="从第 N 张开始（从 1 计数，可与 --limit 合用）")
    parser.add_argument("--holdout", action="store_true", help="读取 images_holdout，结果写入 raw_holdout")
    args = parser.parse_args()

    names = list(PIPELINES) if args.pipeline == "all" else args.pipeline.split(",")
    unknown = [n for n in names if n not in PIPELINES]
    if unknown:
        raise SystemExit(f"没有这些方案：{unknown}；可选：{list(PIPELINES)}")

    paths = images(IMAGES_HOLDOUT) if args.holdout else images()
    if args.limit:
        paths = paths[: args.limit]
    if not 1 <= args.start <= len(paths):
        parser.error(f"--start 必须在 1 到 {len(paths)} 之间")
    paths = paths[args.start - 1 :]

    client = OpenAI(api_key=load_api_key(), base_url=BASE_URL)
    raw_dir = RAW_HOLDOUT if args.holdout else RAW
    raw_dir.mkdir(exist_ok=True)

    for name in names:
        spec = PIPELINES[name]
        for run in range(1, args.runs + 1):
            out_file = raw_dir / f"{name}__run{run}.jsonl"
            skip = done_keys(out_file)
            print(f"\n=== {name} run{run} ===（已有 {len(skip)} 条，跳过）")
            with out_file.open("a", encoding="utf-8") as handle:
                for index, path in enumerate(paths, 1):
                    if (path.name, run) in skip:
                        continue
                    started = time.perf_counter()
                    parsed, stages, texts, error = run_pipeline(client, spec, path)
                    elapsed = round(time.perf_counter() - started, 1)
                    lines = "; ".join(
                        f"{l.get('color') or ''}{l.get('size') or ''}{l.get('direction')}{l.get('quantity')}"
                        for l in (parsed or {}).get("lines", [])
                    )
                    print(f"[{index}/{len(paths)}] {path.name} {elapsed}s {error or lines}")
                    handle.write(
                        json.dumps(
                            {
                                "image": path.name,
                                "pipeline": name,
                                "spec": spec,
                                "run": run,
                                "elapsed_s": elapsed,
                                "stages": stages,
                                "texts": texts,
                                "parsed": parsed,
                                "error": error,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    handle.flush()

    print(f"\n跑完了，评分用：uv run score.py{' --holdout' if args.holdout else ''}")


if __name__ == "__main__":
    main()
