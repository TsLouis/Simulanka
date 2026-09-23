// Graph SSE transport. Validate at the network boundary; consumer failures are
// not parse failures, and native EventSource remains responsible for reconnect.
export interface CommitMessage {
  event_id: string
  graph_version: number
  actor: string
  nodes: string[]
  edges: string[]
  ports: string[]
}

export interface EventSubscription {
  close(): void
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isVersion(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
}

function isRefs(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(id => typeof id === 'string' && id.length > 0)
}

function isCommit(value: unknown): value is CommitMessage {
  return isRecord(value)
    && typeof value.event_id === 'string' && value.event_id.length > 0
    && isVersion(value.graph_version)
    && typeof value.actor === 'string'
    && isRefs(value.nodes) && isRefs(value.edges) && isRefs(value.ports)
}

export function subscribeEvents(opts: {
  onReady?: (graphVersion: number) => void
  onCommit: (msg: CommitMessage) => void
  onError?: (err: Event) => void
}): EventSubscription {
  const es = new EventSource('/events')
  let closed = false

  function decode(e: MessageEvent, kind: 'ready' | 'commit'): unknown {
    try {
      return JSON.parse(e.data)
    } catch {
      protocolError(kind)
      return undefined
    }
  }

  function protocolError(kind: 'ready' | 'commit') {
    opts.onError?.(new ErrorEvent('parse', {
      message: `Invalid graph ${kind} event`,
      error: new Error(`Invalid graph ${kind} event`),
    }))
  }

  function onReady(e: MessageEvent) {
    if (closed) return
    const data = decode(e, 'ready')
    if (data === undefined) return
    if (!isRecord(data) || !isVersion(data.graph_version)) {
      protocolError('ready')
      return
    }
    opts.onReady?.(data.graph_version)
  }

  function onCommit(e: MessageEvent) {
    if (closed) return
    const data = decode(e, 'commit')
    if (data === undefined) return
    if (!isCommit(data)) {
      protocolError('commit')
      return
    }
    opts.onCommit(data)
  }

  es.addEventListener('ready', onReady)
  es.addEventListener('commit', onCommit)
  es.onerror = ev => {
    if (!closed) opts.onError?.(ev)
  }
  return {
    close() {
      if (closed) return
      closed = true
      es.removeEventListener('ready', onReady)
      es.removeEventListener('commit', onCommit)
      es.onerror = null
      es.close()
    },
  }
}
