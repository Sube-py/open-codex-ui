import type { CodexTurnState } from '../types'

const DATABASE_NAME = 'yier-codex-turn-cache'
const DATABASE_VERSION = 1
const TURN_STORE = 'turns'
const ORDER_STORE = 'thread-orders'
const THREAD_INDEX = 'thread-id'

interface CachedTurnRecord {
  threadId: string
  turnId: string
  turn: CodexTurnState
}

interface CachedTurnOrder {
  threadId: string
  turnIds: string[]
  updatedAt: number
}

export interface CodexTurnCacheSnapshot {
  turns: CodexTurnState[]
}

export interface CodexTurnCache {
  load: (threadId: string) => Promise<CodexTurnCacheSnapshot>
  update: (threadId: string, turnIds: string[], changedTurns: CodexTurnState[]) => Promise<void>
  remove: (threadId: string) => Promise<void>
}

export function codexTurnId(turn: CodexTurnState): string {
  return typeof turn.turnId === 'string' ? turn.turnId.trim() : ''
}

export function cachedTurnIds(turns: CodexTurnState[]): string[] {
  return turns.map(codexTurnId).filter(Boolean)
}

export function refreshTurnIds(turns: CodexTurnState[]): string[] {
  return cachedTurnIds(turns.filter((turn) => turn.status === 'inProgress'))
}

export function mergeTurnDelta(
  cachedTurns: CodexTurnState[],
  turnIds: string[],
  changedTurns: CodexTurnState[],
): CodexTurnState[] {
  const turnsById = new Map<string, CodexTurnState>()
  for (const turn of cachedTurns) {
    const turnId = codexTurnId(turn)
    if (turnId) {
      turnsById.set(turnId, turn)
    }
  }
  for (const turn of changedTurns) {
    const turnId = codexTurnId(turn)
    if (turnId) {
      turnsById.set(turnId, turn)
    }
  }

  const orderedTurns = turnIds
    .map((turnId) => turnsById.get(turnId))
    .filter((turn): turn is CodexTurnState => Boolean(turn))
  const idlessTurns = changedTurns.filter((turn) => !codexTurnId(turn))
  return [...orderedTurns, ...idlessTurns]
}

function requestResult<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error ?? new Error('IndexedDB request failed.'))
  })
}

function transactionDone(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve()
    transaction.onerror = () =>
      reject(transaction.error ?? new Error('IndexedDB transaction failed.'))
    transaction.onabort = () =>
      reject(transaction.error ?? new Error('IndexedDB transaction aborted.'))
  })
}

export class IndexedDbCodexTurnCache implements CodexTurnCache {
  private databasePromise: Promise<IDBDatabase | null> | null = null

  async load(threadId: string): Promise<CodexTurnCacheSnapshot> {
    const database = await this.openDatabase()
    if (!database) {
      return { turns: [] }
    }

    const transaction = database.transaction([TURN_STORE, ORDER_STORE], 'readonly')
    const done = transactionDone(transaction)
    const orderRequest = transaction.objectStore(ORDER_STORE).get(threadId)
    const turnsRequest = transaction.objectStore(TURN_STORE).index(THREAD_INDEX).getAll(threadId)
    const [order, records] = await Promise.all([
      requestResult(orderRequest) as Promise<CachedTurnOrder | undefined>,
      requestResult(turnsRequest) as Promise<CachedTurnRecord[]>,
    ])
    await done

    const turnsById = new Map(records.map((record) => [record.turnId, record.turn]))
    const turnIds = Array.isArray(order?.turnIds) ? order.turnIds : []
    return {
      turns: turnIds
        .map((turnId) => turnsById.get(turnId))
        .filter((turn): turn is CodexTurnState => Boolean(turn)),
    }
  }

  async update(threadId: string, turnIds: string[], changedTurns: CodexTurnState[]): Promise<void> {
    const database = await this.openDatabase()
    if (!database) {
      return
    }

    const normalizedTurnIds = [...new Set(turnIds.map((turnId) => turnId.trim()).filter(Boolean))]
    const activeTurnIds = new Set(normalizedTurnIds)
    const transaction = database.transaction([TURN_STORE, ORDER_STORE], 'readwrite')
    const done = transactionDone(transaction)
    const turnStore = transaction.objectStore(TURN_STORE)
    transaction.objectStore(ORDER_STORE).put({
      threadId,
      turnIds: normalizedTurnIds,
      updatedAt: Date.now(),
    } satisfies CachedTurnOrder)

    for (const turn of changedTurns) {
      const turnId = codexTurnId(turn)
      if (!turnId || !activeTurnIds.has(turnId)) {
        continue
      }
      turnStore.put({ threadId, turnId, turn } satisfies CachedTurnRecord)
    }

    const keysRequest = turnStore.index(THREAD_INDEX).getAllKeys(threadId)
    keysRequest.onsuccess = () => {
      for (const key of keysRequest.result) {
        const turnId = Array.isArray(key) && typeof key[1] === 'string' ? key[1] : ''
        if (turnId && !activeTurnIds.has(turnId)) {
          turnStore.delete(key)
        }
      }
    }
    keysRequest.onerror = () => transaction.abort()
    await done
  }

  async remove(threadId: string): Promise<void> {
    const database = await this.openDatabase()
    if (!database) {
      return
    }

    const transaction = database.transaction([TURN_STORE, ORDER_STORE], 'readwrite')
    const done = transactionDone(transaction)
    const turnStore = transaction.objectStore(TURN_STORE)
    transaction.objectStore(ORDER_STORE).delete(threadId)
    const keysRequest = turnStore.index(THREAD_INDEX).getAllKeys(threadId)
    keysRequest.onsuccess = () => {
      for (const key of keysRequest.result) {
        turnStore.delete(key)
      }
    }
    keysRequest.onerror = () => transaction.abort()
    await done
  }

  private openDatabase(): Promise<IDBDatabase | null> {
    if (this.databasePromise) {
      return this.databasePromise
    }
    if (typeof indexedDB === 'undefined') {
      this.databasePromise = Promise.resolve(null)
      return this.databasePromise
    }

    const databasePromise = new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open(DATABASE_NAME, DATABASE_VERSION)
      request.onupgradeneeded = () => {
        const database = request.result
        if (!database.objectStoreNames.contains(TURN_STORE)) {
          const turnStore = database.createObjectStore(TURN_STORE, {
            keyPath: ['threadId', 'turnId'],
          })
          turnStore.createIndex(THREAD_INDEX, 'threadId', { unique: false })
        }
        if (!database.objectStoreNames.contains(ORDER_STORE)) {
          database.createObjectStore(ORDER_STORE, { keyPath: 'threadId' })
        }
      }
      request.onsuccess = () => {
        request.result.onversionchange = () => request.result.close()
        resolve(request.result)
      }
      request.onerror = () => reject(request.error ?? new Error('Unable to open turn cache.'))
    }).catch(() => null)
    this.databasePromise = databasePromise
    return databasePromise
  }
}

export const codexTurnCache = new IndexedDbCodexTurnCache()
