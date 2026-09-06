import type { DraftBoxWrite } from "../api/shipments";

export function copyToFollowingBoxes(boxes: DraftBoxWrite[], sourceIndex: number, count: number, groupKey: string): DraftBoxWrite[] {
  const source = boxes[sourceIndex];
  if (!Number.isInteger(sourceIndex) || !source || !Number.isSafeInteger(count) || count < 1 || sourceIndex + count >= boxes.length) {
    throw new Error("请填写有效的后续连续箱数");
  }
  if (boxes.some((box, index) => box.boxNo !== index + 1)) throw new Error("箱号重复或不连续，请重新核对");
  if (!source.items.length) throw new Error("请先填写当前箱明细");
  if (source.items.some(item => !Number.isSafeInteger(item.quantity) || item.quantity < 1)) throw new Error("请核对当前箱的规格数量");
  if (boxes.slice(sourceIndex + 1, sourceIndex + count + 1).some(box => box.items.length)) {
    throw new Error("目标箱已有内容，不能覆盖");
  }
  return boxes.map((box, index) => index >= sourceIndex && index <= sourceIndex + count
    ? {...box, groupKey, items: source.items.map(item => ({...item}))}
    : box);
}
