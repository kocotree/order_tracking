# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

import json
from collections import defaultdict

from common import RAW

# 人工核对过的标注原文（8 张），其余为 None
VERIFIED = {
    "img001.jpg": "多10",
    "img004.jpg": "120少1，130多1",
    "img005.jpg": "100少7，110多7，130少7，120多7",
    "img007.jpg": "m少一个.s多一个",
    "img010.jpg": "150少1，140多1",
    "img011.jpg": "m少一个.XL多一个",
    "img012.jpg": "少2",
    "img013.jpg": "少3",
}


def digits(text) -> str:
    # 只比数字和多/少，绕开标点、全角逗号、「一个」这类写法差异
    return "".join(c for c in str(text) if c.isdigit() or c in "多少")


def main() -> None:
    notes = defaultdict(dict)
    for path in sorted(RAW.glob("*.jsonl")):
        pipeline, _, run = path.stem.partition("__")
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            note = record["texts"].get("note")
            parsed = record["parsed"] or {}
            notes[record["image"]][f"{pipeline}/{run}"] = (note, parsed.get("diffNoteText"))

    for image in sorted(notes):
        want = VERIFIED.get(image)
        print(f"\n--- {image}  真值={want!r} ---")
        for key, (note, field) in sorted(notes[image].items()):
            mark = ""
            if want:
                mark = "  ✓" if digits(field) == digits(want) else "  ✗"
            head = f"note={note!r}  " if note is not None else ""
            print(f"  {key:28} {head}diffNoteText={field!r}{mark}")


if __name__ == "__main__":
    main()
