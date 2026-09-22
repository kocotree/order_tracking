# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=10"]
# ///

import hashlib
import sys
from pathlib import Path

from PIL import Image

from common import images

# dHash：缩到 9x8 灰度，比较左右相邻像素亮度。重新编码、缩放、轻微裁剪后仍然相近，
# 汉明距离 <=6 认为是同一张照片。
THRESHOLD = 6


def dhash(path: Path) -> int:
    with Image.open(path) as im:
        small = im.convert("L").resize((9, 8), Image.LANCZOS)
    bits = 0
    for y in range(8):
        for x in range(8):
            bits = bits << 1 | (small.getpixel((x, y)) > small.getpixel((x + 1, y)))
    return bits


def main() -> None:
    # 已编号的 img0XX 排在前面：真值表引用的是这些名字，重复时保留它们、把新来的那份判为重复
    entries = []
    for path in sorted(images(), key=lambda p: (not p.name.startswith("img"), p.name)):
        entries.append((path, hashlib.md5(path.read_bytes()).hexdigest(), dhash(path)))

    seen: dict[str, Path] = {}
    exact: list[tuple[Path, Path]] = []
    for path, md5, _ in entries:
        if md5 in seen:
            exact.append((path, seen[md5]))
        else:
            seen[md5] = path

    dup_paths = {dup for dup, _ in exact}
    keep = [(p, h) for p, _, h in entries if p not in dup_paths]
    near: list[tuple[Path, Path, int]] = []
    for i, (path_a, hash_a) in enumerate(keep):
        for path_b, hash_b in keep[i + 1 :]:
            distance = bin(hash_a ^ hash_b).count("1")
            if distance <= THRESHOLD:
                near.append((path_a, path_b, distance))

    print(f"共 {len(entries)} 张，字节级重复 {len(exact)} 组，感知级疑似重复 {len(near)} 组\n")
    for dup, original in exact:
        print(f"字节相同  {dup.name}  ==  {original.name}")
    for path_a, path_b, distance in near:
        print(f"疑似同图  {path_a.name}  ~~  {path_b.name}  (距离 {distance})")

    fresh = sorted(p.name for p, h in keep if not p.name.startswith("img"))
    print(f"\n去重后的新图 {len(fresh)} 张：")
    for name in fresh:
        print(f"  {name}")


if __name__ == "__main__":
    sys.exit(main())
