import type { AffordanceDTO, EdgeDTO, PortDTO } from './types'

export interface CreatePortRequest {
  name: string
  direction: 'in' | 'out'
  port_type?: string
  attrs?: Record<string, unknown>
}

export interface UpdatePortRequest {
  name?: string
  direction?: 'in' | 'out'
  port_type?: string
  attrs?: Record<string, unknown>
}

export interface PortMutationResult {
  port_id: string
  graph_version: number
}

export interface DeletePortResult {
  deleted: string[]
  graph_version: number
}

async function responseError(resp: Response, label: string): Promise<Error> {
  return new Error(`${label} failed: ${resp.status} ${await resp.text()}`)
}

export async function createPort(
  nodeId: string,
  request: CreatePortRequest,
): Promise<PortMutationResult> {
  const resp = await fetch(`/node/${encodeURIComponent(nodeId)}/ports`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  if (!resp.ok) throw await responseError(resp, 'create port')
  return (await resp.json()) as PortMutationResult
}

export async function updatePort(
  portId: string,
  request: UpdatePortRequest,
): Promise<PortMutationResult> {
  const resp = await fetch(`/port/${encodeURIComponent(portId)}/update`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  if (!resp.ok) throw await responseError(resp, 'update port')
  return (await resp.json()) as PortMutationResult
}

export async function deletePort(portId: string): Promise<DeletePortResult> {
  const resp = await fetch(`/port/${encodeURIComponent(portId)}`, {
    method: 'DELETE',
  })
  if (!resp.ok) throw await responseError(resp, 'delete port')
  return (await resp.json()) as DeletePortResult
}

export async function disconnectEdge(edgeId: string): Promise<void> {
  const resp = await fetch(`/edge/${encodeURIComponent(edgeId)}`, {
    method: 'DELETE',
  })
  if (!resp.ok) throw await responseError(resp, 'disconnect edge')
}

export function objectAction(
  affordances: AffordanceDTO[],
  id: string,
): AffordanceDTO | null {
  return affordances.find(action => action.id === id) ?? null
}

export function portAction(port: PortDTO, id: string): AffordanceDTO | null {
  return objectAction(port.affordances, id)
}

export function edgeAction(edge: EdgeDTO, id: string): AffordanceDTO | null {
  return objectAction(edge.affordances, id)
}
