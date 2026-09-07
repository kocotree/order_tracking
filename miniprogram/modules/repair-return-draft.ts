import type { RepairDraft, RepairDraftEntry } from "../api/repairs";

type Gateway = { saveReturnDraft(id: string, version: number, entries: RepairDraftEntry[]): Promise<RepairDraft> };

function normalize(entries: RepairDraftEntry[]): RepairDraftEntry[] {
  return entries.map(({ variantId, selected, repaired, scrapped }) => ({ variantId, selected, repaired, scrapped }));
}

/** A page serializes saves against the last server-acknowledged version. */
export class RepairDraftSession {
  private latest: RepairDraftEntry[];
  private savedKey: string;
  private pending: Promise<RepairDraft> | null = null;
  private conflict = false;

  constructor(private gateway: Gateway, private repairId: string, public current: RepairDraft) {
    this.current = { ...current, entries: normalize(current.entries) };
    this.latest = this.current.entries;
    this.savedKey = JSON.stringify(this.current.entries);
  }

  save(entries: RepairDraftEntry[]): Promise<RepairDraft> {
    if (this.conflict) return Promise.reject({ statusCode: 409 });
    this.latest = normalize(entries);
    if (!this.pending) this.pending = this.drain().catch(error => {
      if (error.statusCode === 409) this.conflict = true;
      throw error;
    }).finally(() => { this.pending = null; });
    return this.pending;
  }

  private async drain(): Promise<RepairDraft> {
    while (JSON.stringify(this.latest) !== this.savedKey) {
      const value = this.latest;
      const saved = await this.gateway.saveReturnDraft(this.repairId, this.current.version, value);
      this.current = { ...saved, entries: normalize(saved.entries) };
      this.savedKey = JSON.stringify(value);
    }
    return this.current;
  }
}
