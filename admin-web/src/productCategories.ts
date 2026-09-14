export const productCategories = [
  "童帽春夏", "童配春夏", "童装春夏", "童帽秋冬", "童配秋冬", "童装秋冬", "儿童手套",
] as const;

export function sortedCategories(values: (string | null | undefined)[]) {
  const categories = new Set(values.map((value) => value?.trim()).filter((value): value is string => Boolean(value)));
  return [...productCategories.filter((value) => categories.delete(value)), ...[...categories].sort()];
}
