export class CreateReloadGate {
  private inFlightCreates = 0
  private deferredReload = false

  /** Start one Add Node request whose creation commit may arrive over SSE. */
  begin(): void {
    this.inFlightCreates += 1
  }

  /**
   * Called when an otherwise-relevant SSE commit wants to reload the active view.
   * Returns true when the caller should defer that reload until create handoff settles.
   */
  deferIfBusy(): boolean {
    if (this.inFlightCreates === 0) return false
    this.deferredReload = true
    return true
  }

  /**
   * Finish one Add Node request after its position handoff attempt is complete.
   * Returns true exactly when one coalesced deferred reload should now be scheduled.
   */
  finish(): boolean {
    if (this.inFlightCreates === 0) return false
    this.inFlightCreates -= 1
    if (this.inFlightCreates > 0 || !this.deferredReload) return false
    this.deferredReload = false
    return true
  }

  get busy(): boolean {
    return this.inFlightCreates > 0
  }

  get pendingCount(): number {
    return this.inFlightCreates
  }
}
