# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

import json
from collections import defaultdict
from pathlib import Path

from common import RAW

# 标注里不写尺码、必须去箱唛上找的 5 张，真值还没核对
TARGETS = ["img001", "img003", "img006", "img012", "img013"]


def main() -> None:
    table = defaultdict(lambda: defaultdict(list))
    for path in sorted(RAW.glob("*.jsonl")):
        pipeline = path.stem.partition("__")[0]
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            image = Path(record["image"]).stem
            if image not in TARGETS:
                continue
            parsed = record["parsed"] or {}
            sizes = "+".join(str(l.get("size")) for l in parsed.get("lines", [])) or "空"
            table[image][pipeline].append(sizes)

    for image in TARGETS:
        print(f"\n--- {image} ---")
        for pipeline, sizes in sorted(table[image].items()):
            print(f"  {pipeline:20} {' | '.join(sizes)}")


if __name__ == "__main__":
    main()
