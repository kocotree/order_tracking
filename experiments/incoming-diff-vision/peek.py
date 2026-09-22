# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

import argparse
import json

from common import RAW


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--texts", action="store_true", help="连各阶段原文一起打印")
    args = parser.parse_args()

    for path in sorted(RAW.glob("*.jsonl")):
        print(f"\n=== {path.stem} ===")
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            parsed = record["parsed"] or {}
            lines = "; ".join(
                f"{l.get('size')}{l.get('direction')}{l.get('quantity')}" for l in parsed.get("lines", [])
            )
            tokens = "+".join(f"{s['in']}/{s['out']}" for s in record["stages"])
            print(
                f"{record['image']} r{record['run']} {record['elapsed_s']}s [{tokens}] "
                f"{record['error'] or ''} 标注={parsed.get('diffNoteText')!r} 明细={lines} "
                f"工厂={parsed.get('factoryName')} 颜色={parsed.get('color')}"
            )
            if args.texts:
                for stage, text in record["texts"].items():
                    print(f"    --- {stage} ---\n    {text[:600]}")


if __name__ == "__main__":
    main()
