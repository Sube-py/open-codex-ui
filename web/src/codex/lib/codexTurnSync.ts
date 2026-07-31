import {
  cachedTurnIds,
  codexTurnCache,
  mergeTurnDelta,
  mergeTurnPatches,
  refreshTurnIds,
  type CodexTurnCache,
} from './codexTurnCache'
import type {
  CodexConversationState,
  CodexThreadStateDeltaPayload,
  CodexThreadStatePayload,
  CodexTurnState,
  JsonRecord,
} from '../types'

export interface CodexTurnSubscriptionCache {
  cached_turn_ids: string[]
  refresh_turn_ids: string[]
}

export function normalizeThreadDeltaPayload(
  value: unknown,
  fallbackThreadId: string,
): CodexThreadStateDeltaPayload | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null
  }
  const record = value as Partial<CodexThreadStateDeltaPayload>
  const threadId =
    typeof record.thread_id === 'string' && record.thread_id.trim()
      ? record.thread_id.trim()
      : fallbackThreadId
  if (!threadId) {
    return null
  }
  return {
    thread_id: threadId,
    state:
      record.state && typeof record.state === 'object' && !Array.isArray(record.state)
        ? (record.state as CodexConversationState)
        : null,
    turn_ids: Array.isArray(record.turn_ids)
      ? record.turn_ids.filter((turnId): turnId is string => typeof turnId === 'string')
      : [],
    turns: Array.isArray(record.turns)
      ? record.turns.filter(
          (turn): turn is CodexTurnState =>
            Boolean(turn) && typeof turn === 'object' && !Array.isArray(turn),
        )
      : [],
    turn_patches: Array.isArray(record.turn_patches)
      ? record.turn_patches.filter(
          (patch): patch is CodexThreadStateDeltaPayload['turn_patches'][number] =>
            Boolean(patch) && typeof patch === 'object' && !Array.isArray(patch),
        )
      : [],
    stream_role:
      record.stream_role && typeof record.stream_role === 'object'
        ? (record.stream_role as JsonRecord)
        : null,
    queued_followups: Array.isArray(record.queued_followups) ? record.queued_followups : [],
  }
}

export class CodexTurnSync {
  private readonly snapshots = new Map<string, CodexTurnState[]>()

  constructor(private readonly cache: CodexTurnCache = codexTurnCache) {}

  async subscriptionCache(threadId: string): Promise<CodexTurnSubscriptionCache> {
    const turns = await this.load(threadId)
    return {
      cached_turn_ids: cachedTurnIds(turns),
      refresh_turn_ids: refreshTurnIds(turns),
    }
  }

  rememberFull(payload: CodexThreadStatePayload): void {
    const turns = Array.isArray(payload.state?.turns) ? payload.state.turns : []
    const turnIds = cachedTurnIds(turns)
    const previousTurns = this.snapshots.get(payload.thread_id) ?? []
    const previousTurnsById = new Map(previousTurns.map((turn) => [turn.turnId, turn]))
    const lastIndex = turns.length - 1
    const changedTurns = turns.filter((turn, index) => {
      const turnId = turn.turnId
      if (typeof turnId !== 'string' || !turnId) {
        return false
      }
      const previousTurn = previousTurnsById.get(turnId)
      return (
        !previousTurn ||
        previousTurn.status === 'inProgress' ||
        turn.status === 'inProgress' ||
        index === lastIndex
      )
    })
    this.snapshots.set(payload.thread_id, turns)
    void this.cache.update(payload.thread_id, turnIds, changedTurns).catch(() => undefined)
  }

  applyDelta(
    payload: CodexThreadStateDeltaPayload,
    currentTurns: CodexTurnState[] = [],
  ): CodexThreadStatePayload {
    const cachedTurns = this.snapshots.get(payload.thread_id) ?? currentTurns
    const patchedTurns = mergeTurnPatches(cachedTurns, payload.turn_patches)
    const turns = mergeTurnDelta(patchedTurns, payload.turn_ids, payload.turns)
    this.snapshots.set(payload.thread_id, turns)
    void this.cache
      .update(
        payload.thread_id,
        payload.turn_ids,
        [...payload.turns, ...payload.turn_patches.flatMap((patch) => {
          const turn = turns.find((candidate) => candidate.turnId === patch.turn_id)
          return turn ? [turn] : []
        })],
      )
      .catch(() => undefined)
    const state = payload.state ? { ...payload.state, turns } : null
    return {
      thread_id: payload.thread_id,
      host_id: typeof state?.hostId === 'string' ? state.hostId : undefined,
      state,
      stream_role: payload.stream_role,
      queued_followups: payload.queued_followups,
    }
  }

  remove(threadId: string): void {
    this.snapshots.delete(threadId)
    void this.cache.remove(threadId).catch(() => undefined)
  }

  private async load(threadId: string): Promise<CodexTurnState[]> {
    const existing = this.snapshots.get(threadId)
    if (existing) {
      return existing
    }
    try {
      const snapshot = await this.cache.load(threadId)
      this.snapshots.set(threadId, snapshot.turns)
      return snapshot.turns
    } catch {
      this.snapshots.set(threadId, [])
      return []
    }
  }
}
