// Successful writes invalidate existing page instances without caching business data.
const revisions = { orders: 0, repairs: 0, shipments: 0 };
export type FactoryList = keyof typeof revisions;
export function factoryRevision(list: FactoryList): number { return revisions[list]; }
export function invalidateFactoryLists(...lists: FactoryList[]): void {
  lists.forEach(list => { revisions[list]++; });
}
