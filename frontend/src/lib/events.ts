// SSE subscription for graph commits. The server emits one `commit` event per
// apply_patch with {event_id, graph_version, affected_nodes, affected_edges,
// affected_ports}. MVP: the App just reloads the current view on any commit.

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

export function subscribeEvents(opts: {
  onReady?: (graphVersion: number) => void
  onCommit: (msg: CommitMessage) => void
  onError?: (err: Event) => void
}): EventSubscription {
  const es = new EventSource('/events')
  es.addEventListener('ready', (e: MessageEvent) => {
    if (!opts.onReady) return
    try {
      const data = JSON.parse(e.data) as { graph_version: number }
      opts.onReady(data.graph_version)
    } catch {
      // Malformed ready frame is non-fatal — server still streaming commits.
    }
  })
  es.addEventListener('commit', (e: MessageEvent) => {
    try {
      const data = JSON.parse(e.data) as CommitMessage
      opts.onCommit(data)
    } catch (err) {
      opts.onError?.(new ErrorEvent('parse', { error: err }))
    }
  })
  es.onerror = ev => {
    opts.onError?.(ev)
  }
  return {
    close() {
      es.close()
    },
  }
}
