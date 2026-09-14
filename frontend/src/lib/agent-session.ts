import { writable } from 'svelte/store'
import * as api from './api'
import { DEFAULT_PROVIDER_ID } from './api'
import type {
  ContextRefDTO, ContextPreviewDTO, ProviderCapabilitiesDTO,
  SessionDTO, SessionEventDTO,
} from './api'

// Session persistence and provider history stay server-owned. This controller
// only coordinates frontend scope/tree/branch state and explicit attachments;
// it never projects sessions onto the graph or reads/writes canvas positions.
type SessionClient = Pick<typeof api,
  | 'fetchSessions' | 'fetchSessionHistory' | 'fetchProviderDescriptors'
  | 'forkSession' | 'archiveSession' | 'stopSession'
  | 'previewSessionContext' | 'streamSessionMessage'
>
type SelectionStorage = Pick<Storage, 'getItem' | 'setItem'>

export function createAgentSessionController(
  client: SessionClient = api,
  storage?: SelectionStorage,
) {
  const {
    fetchSessions, fetchSessionHistory, fetchProviderDescriptors,
    forkSession, archiveSession, stopSession,
    previewSessionContext, streamSessionMessage,
  } = client
  let currentRootId: string | null = null
  let scopeKey = 'top'
  type PendingContextRef = ContextRefDTO & {
    label: string
    pinned: boolean
  }
  type TurnTarget = {
    scopeKey: string
    scopeRootId: string | null
    targetKey: string
    sessionId: string | null
  }
  const ACTIVE_BRANCH_KEY = 'simulanka.active_session_by_tree'
  const SELECTED_TREE_KEY = 'simulanka.selected_tree_by_scope'
  let sessionsById: Record<string, SessionDTO> = {}
  let sessionIdsByScope: Record<string, string[]> = {}
  let activeSessionByTree: Record<string, string> = {}
  let selectedTreeByScope: Record<string, string> = {}
  let selectedTreeId: string | null = null
  let eventsBySession: Record<string, SessionEventDTO[]> = {}
  let draftEventsByScope: Record<string, SessionEventDTO[]> = {}
  let pendingRefsByTarget: Record<string, PendingContextRef[]> = {}
  let previewByTarget: Record<string, ContextPreviewDTO | null> = {}
  let previewErrorByTarget: Record<string, string | null> = {}
  let previewRequestByTarget: Record<string, number> = {}
  let previewBusyTargets = new Set<string>()
  let busyTargets = new Set<string>()
  let historyRequestBySession: Record<string, number> = {}
  let sessionListRequest = 0
  let sessionListBusy = false
  let sessionActionBusy = false
  let sessionListError: string | null = null
  let providerCapabilitiesById: Record<string, ProviderCapabilitiesDTO> = {}
  let stoppingSessionIds = new Set<string>()
  let recoverySessions: SessionDTO[] = []
  let recoverySessionId: string | null = null
  let recoveryEvents: SessionEventDTO[] = []
  let recoveryBusy = false
  let recoveryError: string | null = null

  function isReadOnly(session: SessionDTO | null): boolean {
    return (
      session?.status === 'archived' ||
      (session?.status === 'orphaned' && session.native_session_id === null) ||
      session?.status === 'native_missing' ||
      session?.status === 'stateless'
    )
  }

  function readStoredMap(key: string): Record<string, string> {
    try {
      const value = JSON.parse((storage ?? window.localStorage).getItem(key) ?? '{}')
      if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
      return Object.fromEntries(
        Object.entries(value).filter(
          (entry): entry is [string, string] => typeof entry[1] === 'string',
        ),
      )
    } catch {
      return {}
    }
  }

  function persistSessionSelection() {
    const selectionStorage = storage ?? window.localStorage
    selectionStorage.setItem(
      ACTIVE_BRANCH_KEY,
      JSON.stringify(activeSessionByTree),
    )
    selectionStorage.setItem(
      SELECTED_TREE_KEY,
      JSON.stringify(selectedTreeByScope),
    )
  }

  function invalidateSessionListSnapshot() {
    // A list response represents an older server snapshot. Once a local
    // mutation starts, that response must never overwrite the new tree,
    // branch, or lifecycle state when it eventually resolves.
    sessionListRequest += 1
    sessionListBusy = false
  }

  function sessionsForTree(treeId: string): SessionDTO[] {
    return getVisibleSessions().filter(session => session.tree_id === treeId)
  }

  function chooseActiveSessionId(
    branches: SessionDTO[],
    remembered: string | undefined,
    treeId: string,
  ): string | null {
    return (
      branches.find(session => session.session_id === remembered)?.session_id ??
      branches.find(session => session.status !== 'archived')?.session_id ??
      branches.find(session => session.session_id === treeId)?.session_id ??
      branches[0]?.session_id ??
      null
    )
  }

  function activeSessionIdForTree(treeId: string): string | null {
    return chooseActiveSessionId(
      sessionsForTree(treeId),
      activeSessionByTree[treeId],
      treeId,
    )
  }

  function selectTree(treeId: string) {
    selectedTreeId = treeId
    selectedTreeByScope = { ...selectedTreeByScope, [scopeKey]: treeId }
    const sessionId = activeSessionIdForTree(treeId)
    if (sessionId) {
      activeSessionByTree = { ...activeSessionByTree, [treeId]: sessionId }
      if (!eventsBySession[sessionId]) void loadSessionHistory(sessionId)
    }
    persistSessionSelection()
    publish()
  }

  async function loadSessionHistory(sessionId: string) {
    const request = (historyRequestBySession[sessionId] ?? 0) + 1
    historyRequestBySession = {
      ...historyRequestBySession,
      [sessionId]: request,
    }
    try {
      const history = await fetchSessionHistory(sessionId)
      if (historyRequestBySession[sessionId] !== request) return
      sessionsById = {
        ...sessionsById,
        [history.session.session_id]: history.session,
      }
      eventsBySession = {
        ...eventsBySession,
        [history.session.session_id]: history.events,
      }
    } catch (err) {
      if (historyRequestBySession[sessionId] === request) {
        sessionListError = (err as Error).message
      }
    } finally {
      publish()
    }
  }

  async function openSession(
    sessionId: string,
    sessionScopeKey: string = scopeKey,
  ) {
    const session = sessionsById[sessionId]
    if (!session) return
    // Context delivery state belongs to the native branch, not merely the
    // visible tree. A preview compiled for the previous branch is stale.
    invalidatePreview(session.tree_id)
    selectedTreeByScope = {
      ...selectedTreeByScope,
      [sessionScopeKey]: session.tree_id,
    }
    activeSessionByTree = {
      ...activeSessionByTree,
      [session.tree_id]: sessionId,
    }
    if (scopeKey === sessionScopeKey) {
      selectedTreeId = session.tree_id
    }
    persistSessionSelection()
    publish()
    await loadSessionHistory(sessionId)
  }

  async function restoreSessions(scopeRootId: string | null = currentRootId) {
    const request = ++sessionListRequest
    const requestedScopeKey = scopeRootId ?? 'top'
    sessionListBusy = true
    sessionListError = null
    publish()
    try {
      const scopedSessions = await fetchSessions(scopeRootId)
      if (request !== sessionListRequest) return
      const nextSessions = { ...sessionsById }
      for (const session of scopedSessions) {
        nextSessions[session.session_id] = session
      }
      sessionsById = nextSessions
      sessionIdsByScope = {
        ...sessionIdsByScope,
        [requestedScopeKey]: scopedSessions.map(session => session.session_id),
      }
      const treeIds = [...new Set(scopedSessions.map(session => session.tree_id))]
      for (const treeId of treeIds) {
        const branches = scopedSessions.filter(session => session.tree_id === treeId)
        const remembered = activeSessionByTree[treeId]
        const active =
          branches.find(session => session.session_id === remembered) ??
          branches.find(session => session.status !== 'archived') ??
          branches.find(session => session.session_id === treeId) ??
          branches[0]
        if (active) {
          activeSessionByTree = {
            ...activeSessionByTree,
            [treeId]: active.session_id,
          }
        }
      }
      if (request === sessionListRequest && scopeKey === requestedScopeKey) {
        const rememberedTree = selectedTreeByScope[requestedScopeKey]
        const candidate =
          treeIds.find(treeId => treeId === rememberedTree) ?? treeIds[0] ?? null
        selectedTreeId = candidate
        const activeId = candidate ? activeSessionIdForTree(candidate) : null
        if (activeId && !eventsBySession[activeId]) void loadSessionHistory(activeId)
      }
      persistSessionSelection()
    } catch (err) {
      if (request === sessionListRequest) {
        sessionListError = (err as Error).message
      }
    } finally {
      if (request === sessionListRequest) sessionListBusy = false
      publish()
    }
  }

  async function openRecovery() {
    recoveryBusy = true
    recoveryError = null
    publish()
    try {
      recoverySessions = await fetchSessions('unassigned')
      const candidate =
        recoverySessions.find(
          session => session.session_id === recoverySessionId,
        ) ?? recoverySessions[0]
      if (candidate) await openRecoverySession(candidate.session_id)
      else {
        recoverySessionId = null
        recoveryEvents = []
      }
    } catch (err) {
      recoveryError = (err as Error).message
    } finally {
      recoveryBusy = false
      publish()
    }
  }

  async function openRecoverySession(sessionId: string) {
    recoverySessionId = sessionId
    recoveryBusy = true
    recoveryError = null
    publish()
    try {
      const history = await fetchSessionHistory(sessionId)
      if (recoverySessionId === sessionId) recoveryEvents = history.events
    } catch (err) {
      if (recoverySessionId === sessionId) {
        recoveryError = (err as Error).message
      }
    } finally {
      if (recoverySessionId === sessionId) recoveryBusy = false
      publish()
    }
  }

  function startNewSession() {
    selectedTreeId = null
    draftEventsByScope = { ...draftEventsByScope, [scopeKey]: [] }
    pendingRefsByTarget = { ...pendingRefsByTarget, [draftTargetKey()]: [] }
    invalidatePreview(draftTargetKey())
    publish()
  }

  async function forkActiveSession(treeId: string) {
    const sessionId = activeSessionIdForTree(treeId)
    if (!sessionId || sessionActionBusy) return
    const sessionScopeKey = scopeKey
    invalidateSessionListSnapshot()
    sessionActionBusy = true
    sessionListError = null
    publish()
    try {
      const child = await forkSession(sessionId)
      sessionsById = { ...sessionsById, [child.session_id]: child }
      sessionIdsByScope = {
        ...sessionIdsByScope,
        [sessionScopeKey]: [
          child.session_id,
          ...(sessionIdsByScope[sessionScopeKey] ?? []).filter(
            candidate => candidate !== child.session_id,
          ),
        ],
      }
      activeSessionByTree = {
        ...activeSessionByTree,
        [treeId]: child.session_id,
      }
      await openSession(child.session_id, sessionScopeKey)
    } catch (err) {
      sessionListError = (err as Error).message
    } finally {
      sessionActionBusy = false
      publish()
    }
  }

  async function archiveActiveSession(treeId: string) {
    const sessionId = activeSessionIdForTree(treeId)
    if (!sessionId || sessionActionBusy) return
    invalidateSessionListSnapshot()
    sessionActionBusy = true
    sessionListError = null
    publish()
    try {
      const archived = await archiveSession(sessionId)
      sessionsById = { ...sessionsById, [archived.session_id]: archived }
    } catch (err) {
      sessionListError = (err as Error).message
    } finally {
      sessionActionBusy = false
      publish()
    }
  }

  async function stopActiveSession(treeId: string) {
    const sessionId = activeSessionIdForTree(treeId)
    if (!sessionId || stoppingSessionIds.has(sessionId)) return
    stoppingSessionIds = new Set([...stoppingSessionIds, sessionId])
    sessionListError = null
    publish()
    try {
      await stopSession(sessionId)
    } catch (err) {
      const nextStopping = new Set(stoppingSessionIds)
      nextStopping.delete(sessionId)
      stoppingSessionIds = nextStopping
      sessionListError = (err as Error).message
    } finally {
      publish()
    }
  }

  function addPendingRef(ref: ContextRefDTO, label: string) {
    const targetKey = selectedTargetKey()
    const refs = pendingRefsByTarget[targetKey] ?? []
    const exists = refs.some(
      item => item.kind === ref.kind && item.ref_id === ref.ref_id,
    )
    if (!exists) {
      pendingRefsByTarget = {
        ...pendingRefsByTarget,
        [targetKey]: [...refs, { ...ref, label, pinned: false }],
      }
    }
    invalidatePreview(targetKey)
    publish()
  }

  function removePendingRef(ref: ContextRefDTO) {
    const targetKey = selectedTargetKey()
    pendingRefsByTarget = {
      ...pendingRefsByTarget,
      [targetKey]: (pendingRefsByTarget[targetKey] ?? []).filter(
        item => item.kind !== ref.kind || item.ref_id !== ref.ref_id,
      ),
    }
    invalidatePreview(targetKey)
    publish()
  }

  function togglePendingPin(ref: ContextRefDTO) {
    const targetKey = selectedTargetKey()
    pendingRefsByTarget = {
      ...pendingRefsByTarget,
      [targetKey]: (pendingRefsByTarget[targetKey] ?? []).map(item =>
        item.kind === ref.kind && item.ref_id === ref.ref_id
          ? { ...item, pinned: !item.pinned }
          : item,
      ),
    }
    publish()
  }

  function invalidatePreview(targetKey: string) {
    previewRequestByTarget = {
      ...previewRequestByTarget,
      [targetKey]: (previewRequestByTarget[targetKey] ?? 0) + 1,
    }
    const nextBusy = new Set(previewBusyTargets)
    nextBusy.delete(targetKey)
    previewBusyTargets = nextBusy
    previewByTarget = { ...previewByTarget, [targetKey]: null }
    previewErrorByTarget = { ...previewErrorByTarget, [targetKey]: null }
  }

  async function previewPendingRefs() {
    const targetKey = selectedTargetKey()
    const request = (previewRequestByTarget[targetKey] ?? 0) + 1
    previewRequestByTarget = { ...previewRequestByTarget, [targetKey]: request }
    previewBusyTargets = new Set([...previewBusyTargets, targetKey])
    previewErrorByTarget = { ...previewErrorByTarget, [targetKey]: null }
    publish()
    const refs = (pendingRefsByTarget[targetKey] ?? []).map(
      ({ kind, ref_id }) => ({ kind, ref_id }),
    )
    const sessionId =
      selectedTreeId === null ? null : activeSessionIdForTree(selectedTreeId)
    try {
      const result = await previewSessionContext(refs, sessionId)
      if (request === previewRequestByTarget[targetKey]) {
        previewByTarget = { ...previewByTarget, [targetKey]: result }
      }
    } catch (err) {
      if (request !== previewRequestByTarget[targetKey]) return
      previewByTarget = { ...previewByTarget, [targetKey]: null }
      previewErrorByTarget = {
        ...previewErrorByTarget,
        [targetKey]: (err as Error).message,
      }
    } finally {
      if (request === previewRequestByTarget[targetKey]) {
        const nextBusy = new Set(previewBusyTargets)
        nextBusy.delete(targetKey)
        previewBusyTargets = nextBusy
      }
      publish()
    }
  }

  function sessionEvent(event: SessionEventDTO, target: TurnTarget) {
    if (event.type === 'status' && event.status === 'created') {
      const details = event.details
      const sessionId = details?.session_id
      const providerId = details?.provider_id
      const workspace = details?.workspace
      if (
        typeof sessionId === 'string' &&
        typeof providerId === 'string' &&
        typeof workspace === 'string'
      ) {
        const previousTargetKey = target.targetKey
        target.sessionId = sessionId
        target.targetKey = sessionId
        const session: SessionDTO = {
          session_id: sessionId,
          tree_id: sessionId,
          scope_root_id: target.scopeRootId,
          scope_status: 'bound',
          provider_id: providerId,
          model: typeof details?.model === 'string' ? details.model : null,
          native_session_id: null,
          workspace,
          parent_session_id:
            typeof details?.parent_session_id === 'string'
              ? details.parent_session_id
              : null,
          forked_from_event_id:
            typeof details?.forked_from_event_id === 'string'
              ? details.forked_from_event_id
              : null,
          status: 'idle',
          legacy: false,
        }
        sessionsById = { ...sessionsById, [sessionId]: session }
        sessionIdsByScope = {
          ...sessionIdsByScope,
          [target.scopeKey]: [
            sessionId,
            ...(sessionIdsByScope[target.scopeKey] ?? []).filter(
              candidate => candidate !== sessionId,
            ),
          ],
        }
        activeSessionByTree = { ...activeSessionByTree, [sessionId]: sessionId }
        const draftRefs = pendingRefsByTarget[previousTargetKey] ?? []
        const nextPendingRefs = { ...pendingRefsByTarget }
        delete nextPendingRefs[previousTargetKey]
        nextPendingRefs[sessionId] = draftRefs
        pendingRefsByTarget = nextPendingRefs
        const nextPreview = { ...previewByTarget }
        delete nextPreview[previousTargetKey]
        nextPreview[sessionId] = null
        previewByTarget = nextPreview
        const nextPreviewError = { ...previewErrorByTarget }
        delete nextPreviewError[previousTargetKey]
        nextPreviewError[sessionId] = null
        previewErrorByTarget = nextPreviewError
        if (scopeKey === target.scopeKey && selectedTreeId === null) {
          selectedTreeId = sessionId
          selectedTreeByScope = {
            ...selectedTreeByScope,
            [target.scopeKey]: sessionId,
          }
        }
        const nextBusy = new Set(busyTargets)
        nextBusy.delete(previousTargetKey)
        nextBusy.add(sessionId)
        busyTargets = nextBusy
        persistSessionSelection()
      }
    }
    if (target.sessionId) {
      eventsBySession = {
        ...eventsBySession,
        [target.sessionId]: [
          ...(eventsBySession[target.sessionId] ?? []),
          event,
        ],
      }
      const lifecycle = event.status
      const lifecycleStatuses: SessionDTO['status'][] = [
        'idle',
        'running',
        'done',
        'failed',
        'interrupted',
        'orphaned',
        'native_missing',
        'stateless',
        'archived',
      ]
      const session = sessionsById[target.sessionId]
      if (session) {
        sessionsById = {
          ...sessionsById,
          [target.sessionId]: {
            ...session,
            native_session_id:
              event.provider_session_id ?? session.native_session_id,
            status:
              lifecycle &&
              lifecycleStatuses.includes(lifecycle as SessionDTO['status'])
                ? (lifecycle as SessionDTO['status'])
                : session.status,
          },
        }
      }
      if (
        lifecycle &&
        ['done', 'failed', 'interrupted', 'orphaned', 'native_missing', 'stateless'].includes(
          lifecycle,
        )
      ) {
        const nextStopping = new Set(stoppingSessionIds)
        nextStopping.delete(target.sessionId)
        stoppingSessionIds = nextStopping
      }
    }
    publish()
  }

  async function sendMessage(text: string) {
    const view = snapshot()
    if (!text.trim() || view.busy || view.readOnly) return
    const originTargetKey = selectedTargetKey()
    const originTreeId = selectedTreeId
    const target: TurnTarget = {
      scopeKey,
      scopeRootId: currentRootId,
      targetKey: originTargetKey,
      sessionId:
        originTreeId === null ? null : activeSessionIdForTree(originTreeId),
    }
    invalidateSessionListSnapshot()
    if (target.sessionId) {
      historyRequestBySession = {
        ...historyRequestBySession,
        [target.sessionId]:
          (historyRequestBySession[target.sessionId] ?? 0) + 1,
      }
    }
    busyTargets = new Set([...busyTargets, originTargetKey])
    invalidatePreview(originTargetKey)
    publish()
    let turnDone = false
    const sentRefs = (pendingRefsByTarget[originTargetKey] ?? []).map(ref => ({
      ...ref,
    }))
    try {
      const resolvedSessionId = await streamSessionMessage(
        {
          sessionId: target.sessionId,
          scopeRootId: target.scopeRootId,
          text,
          providerId: DEFAULT_PROVIDER_ID,
          refs: sentRefs.map(({ kind, ref_id }) => ({ kind, ref_id })),
        },
        event => {
          if (event.type === 'status' && event.status === 'done') {
            turnDone = true
          }
          sessionEvent(event, target)
        },
      )
      target.sessionId = resolvedSessionId
      if (turnDone) {
        const sentKeys = new Set(
          sentRefs.map(ref => `${ref.kind}:${ref.ref_id}`),
        )
        pendingRefsByTarget = {
          ...pendingRefsByTarget,
          [target.targetKey]: (pendingRefsByTarget[target.targetKey] ?? []).filter(
            ref => ref.pinned || !sentKeys.has(`${ref.kind}:${ref.ref_id}`),
          ),
        }
        invalidatePreview(target.targetKey)
      }
    } catch (err) {
      const failure: SessionEventDTO = {
        type: 'error',
        status: 'failed',
        text: `⚠ 会话失败: ${(err as Error).message}`,
      }
      if (target.sessionId) {
        eventsBySession = {
          ...eventsBySession,
          [target.sessionId]: [
            ...(eventsBySession[target.sessionId] ?? []),
            failure,
          ],
        }
      } else {
        draftEventsByScope = {
          ...draftEventsByScope,
          [target.scopeKey]: [
            ...(draftEventsByScope[target.scopeKey] ?? []),
            failure,
          ],
        }
      }
    } finally {
      const nextBusy = new Set(busyTargets)
      nextBusy.delete(originTargetKey)
      nextBusy.delete(target.targetKey)
      busyTargets = nextBusy
      if (target.sessionId) {
        const nextStopping = new Set(stoppingSessionIds)
        nextStopping.delete(target.sessionId)
        stoppingSessionIds = nextStopping
      }
      publish()
    }
  }

  function draftTargetKey(): string {
    return `draft:${scopeKey}`
  }

  function selectedTargetKey(): string {
    return selectedTreeId ?? draftTargetKey()
  }

  function getVisibleSessions(): SessionDTO[] {
    return (sessionIdsByScope[scopeKey] ?? [])
      .map(id => sessionsById[id])
      .filter((session): session is SessionDTO => session !== undefined)
  }

  function getVisibleTreeIds(): string[] {
    return [...new Set(getVisibleSessions().map(session => session.tree_id))]
  }

  function snapshot() {
    const sessionId = selectedTreeId ? activeSessionIdForTree(selectedTreeId) : null
    const session = sessionId ? sessionsById[sessionId] ?? null : null
    const targetKey = selectedTargetKey()
    const refs = pendingRefsByTarget[targetKey] ?? []
    const capabilities = session ? providerCapabilitiesById[session.provider_id] : null
    return {
      scopeKey,
      selectedTreeId,
      selectedTargetKey: targetKey,
      trees: getVisibleTreeIds().map(treeId => ({
        treeId,
        sessions: sessionsForTree(treeId),
        activeSessionId: activeSessionIdForTree(treeId),
        busy: busyTargets.has(treeId),
      })),
      activeSession: session,
      events: sessionId
        ? eventsBySession[sessionId] ?? []
        : draftEventsByScope[scopeKey] ?? [],
      busy: busyTargets.has(targetKey),
      readOnly: isReadOnly(session),
      listBusy: sessionListBusy,
      actionBusy: sessionActionBusy,
      error: sessionListError,
      pendingRefs: refs,
      contextLabel: `${selectedTreeId ? '当前会话树' : '新树'} · ${refs.length ? `已附加 ${refs.length} 项` : '未附加上下文'}`,
      preview: previewByTarget[targetKey] ?? null,
      previewError: previewErrorByTarget[targetKey] ?? null,
      previewBusy: previewBusyTargets.has(targetKey),
      providerId: session?.provider_id ?? DEFAULT_PROVIDER_ID,
      capabilities: capabilities ?? null,
      interruptReady: Boolean(session && (
        capabilities?.native_resume === false || session.native_session_id !== null
      )),
      stopping: sessionId ? stoppingSessionIds.has(sessionId) : false,
      recovery: {
        sessions: recoverySessions,
        sessionId: recoverySessionId,
        events: recoveryEvents,
        busy: recoveryBusy,
        error: recoveryError,
      },
    }
  }

  const state = writable(snapshot())
  function publish() {
    state.set(snapshot())
  }

  async function initialize() {
    activeSessionByTree = readStoredMap(ACTIVE_BRANCH_KEY)
    selectedTreeByScope = readStoredMap(SELECTED_TREE_KEY)
    const providers = fetchProviderDescriptors()
      .then(descriptors => {
        providerCapabilitiesById = Object.fromEntries(
          descriptors.map(descriptor => [descriptor.provider_id, descriptor.capabilities]),
        )
        publish()
      })
      .catch(() => undefined)
    await Promise.all([providers, restoreSessions(currentRootId)])
  }

  function setScope(rootId: string | null) {
    currentRootId = rootId
    scopeKey = rootId ?? 'top'
    selectedTreeId = null
    publish()
    return restoreSessions(rootId)
  }

  return {
    subscribe: state.subscribe,
    initialize, setScope, restoreSessions,
    selectTree, openSession, startNewSession,
    forkActiveSession, archiveActiveSession, stopActiveSession,
    openRecovery, openRecoverySession,
    addPendingRef, removePendingRef, togglePendingPin,
    previewPendingRefs, sendMessage,
  }
}

export type AgentSessionController = ReturnType<typeof createAgentSessionController>
