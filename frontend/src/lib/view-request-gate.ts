// A response may commit UI state only while it owns the current view request.
// This does not cancel network traffic or change graph write ordering.
export class ViewRequestGate {
  private generation = 0
  private closed = false

  get disposed(): boolean { return this.closed }

  begin(root: string | null): { generation: number; root: string | null } {
    return { generation: ++this.generation, root }
  }

  accepts(request: { generation: number; root: string | null }, root: string | null): boolean {
    return !this.closed && request.generation === this.generation && request.root === root
  }

  dispose(): void {
    this.closed = true
    this.generation += 1
  }
}
