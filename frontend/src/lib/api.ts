import type { GraphPayload } from './types'

export async function fetchGraph(
  root: string | null,
  depth: number,
): Promise<GraphPayload> {
  const params = new URLSearchParams()
  if (root !== null) params.set('root', root)
  params.set('depth', String(depth))
  const resp = await fetch(`/graph?${params}`)
  if (!resp.ok) {
    throw new Error(`GET /graph failed: ${resp.status} ${await resp.text()}`)
  }
  return (await resp.json()) as GraphPayload
}

// Per-view-root maps of node id → [x, y]. "top" is the top-level view key.
export type Positions = Record<string, Record<string, [number, number]>>

export async function fetchPositions(): Promise<Positions> {
  const resp = await fetch('/ui/positions')
  if (!resp.ok) throw new Error(`GET /ui/positions failed: ${resp.status}`)
  return (await resp.json()) as Positions
}

export async function savePositions(
  rootKey: string,
  positions: Record<string, [number, number]>,
): Promise<void> {
  const resp = await fetch(`/ui/positions/${encodeURIComponent(rootKey)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(positions),
  })
  if (!resp.ok) {
    throw new Error(`POST /ui/positions failed: ${resp.status} ${await resp.text()}`)
  }
}
