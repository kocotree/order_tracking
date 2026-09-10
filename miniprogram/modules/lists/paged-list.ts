export interface ListPage<T> { items: T[]; total: number }
export interface ListState<T> { items: T[]; total: number; loading: boolean; loadingMore: boolean; error: string; hasMore: boolean }

/** Page-instance state only; a new search invalidates every older response. */
export class PagedList<T> {
  private generation = 0;
  private page = 0;
  private items: T[] = [];
  private total = 0;
  private busy = false;
  private ended = false;
  private request: ((page: number) => Promise<ListPage<T>>) | null = null;
  constructor(private key: (item: T) => string, private update: (state: ListState<T>) => void) {}
  reset(request: (page: number) => Promise<ListPage<T>>): Promise<void> {
    this.generation++;
    this.page = 0;
    this.items = [];
    this.total = 0;
    this.busy = false;
    this.ended = false;
    this.request = request;
    return this.next();
  }
  dispose(): void { this.generation++; this.request = null; }
  async next(): Promise<void> {
    if (this.busy || this.ended || !this.request) return;
    const generation = this.generation, page = this.page + 1;
    this.busy = true;
    this.emit("");
    try {
      const result = await this.request(page);
      if (generation !== this.generation) return;
      const ids = new Set(this.items.map(this.key));
      this.items = [...this.items, ...result.items.filter(item => {
        const id = this.key(item);
        if (ids.has(id)) return false;
        ids.add(id); return true;
      })];
      this.page = page;
      this.total = result.total;
      this.ended = !result.items.length || page * 20 >= result.total;
      this.busy = false;
      this.emit("");
    } catch {
      if (generation !== this.generation) return;
      this.busy = false;
      this.emit("加载失败，点击重试");
    }
  }
  private emit(error: string): void {
    this.update({ items: this.items, total: this.total, loading: this.busy && this.page === 0,
      loadingMore: this.busy && this.page > 0, error, hasMore: !this.ended });
  }
}
