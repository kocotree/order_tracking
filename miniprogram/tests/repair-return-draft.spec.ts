import { expect, it, vi } from "vitest";
import { RepairDraftSession } from "../modules/repair-return-draft";
import type { RepairDraft } from "../api/repairs";
const entry = { variantId: "sku", selected: true, repaired: "2", scrapped: "" };

it("serializes concurrent edits using acknowledged versions", async () => {
  let complete!: (draft: RepairDraft) => void;
  const saveReturnDraft = vi.fn().mockImplementationOnce(() => new Promise(resolve => { complete = resolve; })).mockResolvedValueOnce({version: 2, entries: [{...entry, repaired: "3"}], submissionKey: "key"});
  const session = new RepairDraftSession({saveReturnDraft}, "repair", {version: 0, entries: [], submissionKey: ""});
  const first = session.save([entry]);
  const second = session.save([{...entry, repaired: "3"}]);
  expect(saveReturnDraft).toHaveBeenCalledTimes(1);
  complete({version: 1, entries: [entry], submissionKey: "key"});
  await Promise.all([first, second]);
  expect(saveReturnDraft.mock.calls[1]).toEqual(["repair", 1, [{...entry, repaired: "3"}]]);
  expect(session.current.version).toBe(2);
});

it("retries failed saves without advancing version and stops on conflict", async () => {
  const saveReturnDraft = vi.fn().mockRejectedValueOnce({statusCode: 500}).mockRejectedValueOnce({statusCode: 409});
  const session = new RepairDraftSession({saveReturnDraft}, "repair", {version: 2, entries: [], submissionKey: "key"});
  await expect(session.save([entry])).rejects.toEqual({statusCode: 500});
  expect(session.current.version).toBe(2);
  await expect(session.save([entry])).rejects.toEqual({statusCode: 409});
  await expect(session.save([entry])).rejects.toEqual({statusCode: 409});
  expect(saveReturnDraft).toHaveBeenCalledTimes(2);
});

it("does not resave restored entries merely because JSON property order changed", async () => {
  const saveReturnDraft = vi.fn();
  const session = new RepairDraftSession({saveReturnDraft}, "repair", {version: 3, entries: [{scrapped: "", repaired: "2", selected: true, variantId: "sku"}], submissionKey: "key"});
  const saved = await session.save([entry]);
  expect(saveReturnDraft).not.toHaveBeenCalled();
  expect(JSON.stringify(saved.entries)).toBe(JSON.stringify([entry]));
});
