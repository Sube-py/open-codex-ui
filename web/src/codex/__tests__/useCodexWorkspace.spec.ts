import { defineComponent, h, nextTick } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { apiGet } from '../../lib/api'
import { mergeTurnDelta, type CodexTurnCache } from '../lib/codexTurnCache'
import {
  useCodexWorkspace,
  type CodexRealtimeClient,
  type UseCodexWorkspaceOptions,
} from '../composables/useCodexWorkspace'
import type {
  CodexClientCommand,
  CodexServerEvent,
  CodexSocketStatus,
  CodexTurnState,
  JsonRecord,
} from '../types'

vi.mock('../../lib/api', () => ({
  apiGet: vi.fn(),
}))

const apiGetMock = vi.mocked(apiGet)

type CommandCall = {
  type: CodexClientCommand
  payload: JsonRecord
}

class FakeCodexSocket implements CodexRealtimeClient {
  readonly commands: CommandCall[] = []
  readonly eventListeners = new Set<(event: CodexServerEvent) => void>()
  readonly statusListeners = new Set<(status: CodexSocketStatus) => void>()
  closed = false
  connectCount = 0
  readonly forkedThread = {
    thread_id: 'thread-forked',
    title: 'Forked',
    preview: 'forked',
    updated_at: 30,
    started_at: 30,
    status: 'idle',
    cwd: '/tmp/alpha',
    project: 'alpha',
    project_path: '/tmp/alpha',
    source: 'appServer',
  }
  includeForkedThread = false
  includeRemoteThread = false
  goalObjective = 'Existing goal'
  getThreadGoalResponse: unknown = { goal: null }
  returnDirectGoalResponse = false
  readonly deferredSubscribeThreadIds = new Set<string>()
  readonly subscribeResolvers = new Map<string, (value: unknown) => void>()
  readonly threadDeltaResponses = new Map<string, unknown>()

  async connect() {
    this.connectCount += 1
    this.statusListeners.forEach((listener) => listener('open'))
    this.emit({ type: 'connection_ready', payload: { ok: true } })
  }

  close() {
    this.closed = true
  }

  async sendCommand<TPayload = unknown>(
    type: CodexClientCommand,
    payload: JsonRecord = {},
  ): Promise<TPayload> {
    this.commands.push({ type, payload })
    if (type === 'list_threads') {
      return {
        projects: [
          {
            project: 'alpha',
            project_path: '/tmp/alpha',
            session_count: 2,
            sessions: [
              {
                thread_id: 'thread-a',
                title: 'Alpha A',
                preview: 'first',
                updated_at: 20,
                started_at: 10,
                status: 'idle',
                cwd: '/tmp/alpha',
                project: 'alpha',
                project_path: '/tmp/alpha',
                source: 'appServer',
              },
              {
                thread_id: 'thread-b',
                title: 'Alpha B',
                preview: 'second',
                updated_at: 10,
                started_at: 5,
                status: 'idle',
                cwd: '/tmp/alpha',
                project: 'alpha',
                project_path: '/tmp/alpha',
                source: 'appServer',
              },
              ...(this.includeForkedThread ? [this.forkedThread] : []),
            ],
          },
          ...(this.includeRemoteThread
            ? [
                {
                  project: 'remote-app',
                  project_path: '/srv/app',
                  host_id: 'ssh:remote-1',
                  session_count: 1,
                  sessions: [
                    {
                      thread_id: 'thread-remote',
                      host_id: 'ssh:remote-1',
                      title: 'Remote thread',
                      preview: 'remote',
                      updated_at: 40,
                      started_at: 30,
                      status: 'idle',
                      cwd: '/srv/app',
                      project: 'remote-app',
                      project_path: '/srv/app',
                      source: 'appServer',
                    },
                  ],
                },
              ]
            : []),
        ],
        paired_editors: [],
      } as TPayload
    }
    if (type === 'subscribe_thread_delta') {
      const threadId = String(payload.thread_id)
      const response = this.threadDeltaResponses.get(threadId) ?? {
        thread_id: threadId,
        state: { id: threadId, requests: [] },
        turn_ids: [],
        turns: [],
        stream_role: null,
        queued_followups: [],
      }
      if (this.deferredSubscribeThreadIds.has(threadId)) {
        return new Promise<TPayload>((resolve) => {
          this.subscribeResolvers.set(threadId, resolve as (value: unknown) => void)
        })
      }
      return response as TPayload
    }
    if (type === 'get_thread_goal') {
      return this.getThreadGoalResponse as TPayload
    }
    if (type === 'set_thread_goal') {
      if (typeof payload.objective === 'string') {
        this.goalObjective = payload.objective
      }
      const goal = {
        threadId: String(payload.thread_id),
        objective: this.goalObjective,
        status: typeof payload.status === 'string' ? payload.status : 'active',
        tokenBudget: typeof payload.token_budget === 'number' ? payload.token_budget : null,
        tokensUsed: 0,
        timeUsedSeconds: 0,
        createdAt: 1,
        updatedAt: 2,
      }
      return (this.returnDirectGoalResponse ? goal : { goal }) as TPayload
    }
    if (type === 'clear_thread_goal') {
      return { cleared: true } as TPayload
    }
    if (type === 'fork_thread') {
      this.includeForkedThread = true
      return {
        thread_id: this.forkedThread.thread_id,
        state: { id: this.forkedThread.thread_id, turns: [], requests: [] },
      } as TPayload
    }
    if (type === 'start_thread') {
      return {
        thread_id: 'thread-created',
        state: {
          id: 'thread-created',
          turns: [],
          requests: [],
          cwd: String(payload.project_path ?? '/tmp/created'),
        },
      } as TPayload
    }
    return { ok: true } as TPayload
  }

  onEvent(listener: (event: CodexServerEvent) => void) {
    this.eventListeners.add(listener)
    return () => this.eventListeners.delete(listener)
  }

  onStatus(listener: (status: CodexSocketStatus) => void) {
    this.statusListeners.add(listener)
    return () => this.statusListeners.delete(listener)
  }

  emit(event: CodexServerEvent) {
    this.eventListeners.forEach((listener) => listener(event))
  }

  emitStatus(status: CodexSocketStatus) {
    this.statusListeners.forEach((listener) => listener(status))
  }

  resolveSubscribe(threadId: string) {
    const resolve = this.subscribeResolvers.get(threadId)
    if (!resolve) {
      throw new Error(`No deferred subscribe for ${threadId}`)
    }
    this.subscribeResolvers.delete(threadId)
    this.deferredSubscribeThreadIds.delete(threadId)
    resolve({
      thread_id: threadId,
      state: { id: threadId, requests: [] },
      turn_ids: [],
      turns: [],
      stream_role: null,
      queued_followups: [],
    })
  }
}

class FakeTurnCache implements CodexTurnCache {
  readonly snapshots = new Map<string, CodexTurnState[]>()
  readonly updates: Array<{
    threadId: string
    turnIds: string[]
    changedTurns: CodexTurnState[]
  }> = []
  readonly removedThreadIds: string[] = []

  async load(threadId: string) {
    return { turns: this.snapshots.get(threadId) ?? [] }
  }

  async update(threadId: string, turnIds: string[], changedTurns: CodexTurnState[]) {
    this.updates.push({ threadId, turnIds, changedTurns })
    this.snapshots.set(
      threadId,
      mergeTurnDelta(this.snapshots.get(threadId) ?? [], turnIds, changedTurns),
    )
  }

  async remove(threadId: string) {
    this.removedThreadIds.push(threadId)
    this.snapshots.delete(threadId)
  }
}

function mountHarness(
  socket: FakeCodexSocket,
  options: Omit<UseCodexWorkspaceOptions, 'socket'> = {},
) {
  const turnCache = options.turnCache ?? new FakeTurnCache()
  const holder: { workspace?: ReturnType<typeof useCodexWorkspace> } = {}
  const wrapper = mount(
    defineComponent({
      setup() {
        holder.workspace = useCodexWorkspace({ socket, turnCache, ...options })
        return () => h('div')
      },
    }),
  )
  if (!holder.workspace) {
    throw new Error('Expected Codex workspace harness to initialize.')
  }
  return { wrapper, workspace: holder.workspace, turnCache }
}

describe('useCodexWorkspace', () => {
  beforeEach(() => {
    localStorage.clear()
    apiGetMock.mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('reconnects after a dropped socket and resubscribes to the active thread', async () => {
    vi.useFakeTimers()
    const socket = new FakeCodexSocket()
    const { wrapper, workspace } = mountHarness(socket)
    await flushPromises()
    await workspace.selectThread('thread-b')
    const commandCount = socket.commands.length

    socket.emitStatus('closed')
    await vi.advanceTimersByTimeAsync(1_000)
    await flushPromises()

    expect(socket.connectCount).toBe(2)
    expect(socket.commands.slice(commandCount).map((command) => command.type)).toEqual([
      'list_threads',
      'subscribe_thread_delta',
      'get_thread_goal',
    ])
    expect(socket.commands[socket.commands.length - 2]).toEqual({
      type: 'subscribe_thread_delta',
      payload: { thread_id: 'thread-b', cached_turn_ids: [] },
    })
    expect(workspace.status.value).toBe('open')
    wrapper.unmount()
  })

  it('waits while backgrounded and reconnects immediately on return', async () => {
    vi.useFakeTimers()
    let visibilityState: DocumentVisibilityState = 'visible'
    vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visibilityState)
    const socket = new FakeCodexSocket()
    const { wrapper } = mountHarness(socket)
    await flushPromises()

    visibilityState = 'hidden'
    socket.emitStatus('closed')
    await vi.advanceTimersByTimeAsync(15_000)
    expect(socket.connectCount).toBe(1)

    visibilityState = 'visible'
    document.dispatchEvent(new Event('visibilitychange'))
    await flushPromises()

    expect(socket.connectCount).toBe(2)
    wrapper.unmount()
  })

  it('refreshes SSH connection metadata without listing remote threads', async () => {
    const socket = new FakeCodexSocket()
    const { workspace } = mountHarness(socket)
    await flushPromises()
    apiGetMock.mockResolvedValueOnce({
      connections: [
        {
          id: 'remote-1',
          display_name: 'Build host',
          ssh_host: 'build.example.com',
          ssh_alias: '',
          identity_file: '',
          auto_connect: false,
        },
      ],
      active_connection_id: '',
      statuses: {
        'remote-1': { status: 'disconnected', detail: 'Not connected yet' },
      },
    })
    const commandCount = socket.commands.length

    await workspace.refreshRemoteConnections()

    expect(apiGetMock).toHaveBeenCalledWith('/api/codex/remote-connections')
    expect(socket.commands).toHaveLength(commandCount)
    expect(workspace.workspace.value.remote_connections?.[0]?.id).toBe('remote-1')
    expect(workspace.workspace.value.remote_connection_statuses?.['remote-1']?.status).toBe(
      'disconnected',
    )
  })

  it('subscribes to one visible thread while leaving server sessions alive', async () => {
    const socket = new FakeCodexSocket()
    const { workspace } = mountHarness(socket)
    await flushPromises()

    expect(workspace.activeThreadId.value).toBe('thread-a')
    expect(socket.commands.map((command) => command.type)).toEqual([
      'list_threads',
      'subscribe_thread_delta',
      'get_thread_goal',
    ])

    await workspace.selectThread('thread-b')
    await flushPromises()

    expect(socket.commands.slice(-3)).toEqual([
      { type: 'unsubscribe_thread', payload: { thread_id: 'thread-a' } },
      {
        type: 'subscribe_thread_delta',
        payload: { thread_id: 'thread-b', cached_turn_ids: [] },
      },
      { type: 'get_thread_goal', payload: { thread_id: 'thread-b' } },
    ])
    expect(socket.closed).toBe(false)

    socket.emit({
      type: 'thread_state',
      payload: {
        thread_id: 'thread-b',
        state: {
          id: 'thread-b',
          turns: [{ turnId: 'turn-1', status: 'inProgress', items: [] }],
          requests: [],
        },
        queued_followups: [],
      },
    })
    await nextTick()

    expect(workspace.activeStatus.value).toBe('inProgress')
    expect(workspace.isActiveTurnInProgress.value).toBe(true)
    expect(
      workspace.workspace.value.projects
        .flatMap((project) => project.sessions)
        .find((thread) => thread.thread_id === 'thread-b')?.status,
    ).toBe('inProgress')
  })

  it('hydrates cached turns and applies authoritative realtime deltas', async () => {
    const socket = new FakeCodexSocket()
    const turnCache = new FakeTurnCache()
    turnCache.snapshots.set('thread-a', [
      {
        turnId: 'turn-0',
        status: 'completed',
        items: [{ type: 'agentMessage', text: 'cached' }],
      },
      {
        turnId: 'turn-1',
        status: 'inProgress',
        items: [{ type: 'agentMessage', text: 'stale' }],
      },
    ])
    socket.threadDeltaResponses.set('thread-a', {
      thread_id: 'thread-a',
      state: { id: 'thread-a', title: 'Initial title', requests: [] },
      turn_ids: ['turn-0', 'turn-1', 'turn-2'],
      turns: [
        {
          turnId: 'turn-1',
          status: 'completed',
          items: [{ type: 'agentMessage', text: 'finished' }],
        },
        {
          turnId: 'turn-2',
          status: 'inProgress',
          items: [{ type: 'agentMessage', text: 'streaming' }],
        },
      ],
      queued_followups: [],
    })

    const { workspace } = mountHarness(socket, { turnCache })
    await flushPromises()

    expect(socket.commands).toContainEqual({
      type: 'subscribe_thread_delta',
      payload: {
        thread_id: 'thread-a',
        cached_turn_ids: ['turn-0', 'turn-1'],
        refresh_turn_ids: ['turn-1'],
      },
    })
    expect(workspace.activeThreadState.value?.turns?.map((turn) => turn.turnId)).toEqual([
      'turn-0',
      'turn-1',
      'turn-2',
    ])
    expect(workspace.activeThreadState.value?.turns?.[0]?.items).toEqual([
      { type: 'agentMessage', text: 'cached' },
    ])
    expect(workspace.activeThreadState.value?.turns?.[1]?.items).toEqual([
      { type: 'agentMessage', text: 'finished' },
    ])

    socket.emit({
      type: 'thread_state',
      payload: {
        thread_id: 'thread-a',
        state: {
          id: 'thread-a',
          title: 'Live title',
          requests: [],
          turns: [
            {
              turnId: 'turn-2',
              status: 'completed',
              items: [{ type: 'agentMessage', text: 'done' }],
            },
          ],
        },
        queued_followups: [],
      },
    })
    await nextTick()

    expect(workspace.activeThreadState.value?.title).toBe('Live title')
    expect(workspace.activeThreadState.value?.turns).toEqual([
      {
        turnId: 'turn-2',
        status: 'completed',
        items: [{ type: 'agentMessage', text: 'done' }],
      },
    ])
    expect(turnCache.snapshots.get('thread-a')).toEqual(workspace.activeThreadState.value?.turns)
  })

  it('routes remote thread selection and creation through its host', async () => {
    const socket = new FakeCodexSocket()
    socket.includeRemoteThread = true
    const { workspace } = mountHarness(socket)
    await flushPromises()

    expect(workspace.activeThreadId.value).toBe('thread-remote')
    expect(socket.commands.slice(0, 2)).toEqual([
      { type: 'list_threads', payload: {} },
      {
        type: 'subscribe_thread_delta',
        payload: {
          thread_id: 'thread-remote',
          cached_turn_ids: [],
          host_id: 'ssh:remote-1',
        },
      },
    ])

    await workspace.startThread('/srv/app', 'ssh:remote-1')
    await flushPromises()

    expect(socket.commands).toContainEqual({
      type: 'start_thread',
      payload: { project_path: '/srv/app', host_id: 'ssh:remote-1' },
    })
    expect(socket.commands).toContainEqual({
      type: 'subscribe_thread_delta',
      payload: {
        thread_id: 'thread-created',
        cached_turn_ids: [],
        host_id: 'ssh:remote-1',
      },
    })
  })

  it('reports active thread loading while a thread subscription is pending', async () => {
    const socket = new FakeCodexSocket()
    const { workspace } = mountHarness(socket)
    await flushPromises()

    socket.deferredSubscribeThreadIds.add('thread-b')
    const selection = workspace.selectThread('thread-b')
    await flushPromises()

    expect(workspace.activeThreadId.value).toBe('thread-b')
    expect(workspace.openingThreadId.value).toBe('thread-b')
    expect(workspace.isActiveThreadLoading.value).toBe(true)

    socket.resolveSubscribe('thread-b')
    await selection
    await flushPromises()

    expect(workspace.openingThreadId.value).toBe('')
    expect(workspace.activeThreadState.value?.id).toBe('thread-b')
    expect(workspace.isActiveThreadLoading.value).toBe(false)
  })

  it('sends user input responses through the websocket command envelope', async () => {
    const socket = new FakeCodexSocket()
    const { workspace } = mountHarness(socket)
    await flushPromises()

    await workspace.submitUserInputResponse('request-1', {
      answers: { mode: { answers: ['Plan'] } },
    })

    expect(socket.commands[socket.commands.length - 1]).toEqual({
      type: 'submit_user_input_response',
      payload: {
        thread_id: 'thread-a',
        request_id: 'request-1',
        response: { answers: { mode: { answers: ['Plan'] } } },
      },
    })
  })

  it('sends model and reasoning overrides with prompt submissions', async () => {
    const socket = new FakeCodexSocket()
    const { workspace } = mountHarness(socket)
    await flushPromises()

    await workspace.sendPrompt({
      prompt: 'Use the selected model',
      model: 'gpt-5.4-mini',
      reasoningEffort: 'high',
    })

    expect(socket.commands[socket.commands.length - 1]).toEqual({
      type: 'send_prompt',
      payload: {
        thread_id: 'thread-a',
        prompt: 'Use the selected model',
        collaboration_mode: {
          mode: 'default',
          settings: {
            model: 'gpt-5.4-mini',
            reasoning_effort: 'high',
            developer_instructions: null,
          },
        },
      },
    })
  })

  it('sends image attachments with prompt submissions', async () => {
    const socket = new FakeCodexSocket()
    const { workspace } = mountHarness(socket)
    await flushPromises()

    await workspace.sendPrompt({
      prompt: '',
      attachments: [
        {
          type: 'image',
          imageUrl: 'data:image/png;base64,abc',
          name: 'preview.png',
        },
      ],
    })

    expect(socket.commands[socket.commands.length - 1]).toEqual({
      type: 'send_prompt',
      payload: {
        thread_id: 'thread-a',
        prompt: '',
        attachments: [
          {
            type: 'image',
            imageUrl: 'data:image/png;base64,abc',
            name: 'preview.png',
          },
        ],
        collaboration_mode: {
          mode: 'default',
          settings: {
            model: '',
            reasoning_effort: null,
            developer_instructions: null,
          },
        },
      },
    })
  })

  it('sends permission overrides with prompt submissions', async () => {
    const socket = new FakeCodexSocket()
    const { workspace } = mountHarness(socket)
    await flushPromises()

    await workspace.sendPrompt({
      prompt: 'Use full access',
      approvalPolicy: 'never',
      approvalsReviewer: 'user',
      sandboxPolicy: { type: 'dangerFullAccess' },
    })

    expect(socket.commands[socket.commands.length - 1]).toEqual({
      type: 'send_prompt',
      payload: {
        thread_id: 'thread-a',
        prompt: 'Use full access',
        approval_policy: 'never',
        approvals_reviewer: 'user',
        sandbox_policy: { type: 'dangerFullAccess' },
        collaboration_mode: {
          mode: 'default',
          settings: {
            model: '',
            reasoning_effort: null,
            developer_instructions: null,
          },
        },
      },
    })
  })

  it('sets, updates, and clears thread goals', async () => {
    const socket = new FakeCodexSocket()
    const { workspace } = mountHarness(socket)
    await flushPromises()

    await workspace.setThreadGoal('Ship the web goal mode', 20000)
    await flushPromises()

    expect(socket.commands[socket.commands.length - 1]).toEqual({
      type: 'set_thread_goal',
      payload: {
        thread_id: 'thread-a',
        objective: 'Ship the web goal mode',
        status: 'active',
        token_budget: 20000,
      },
    })
    expect(workspace.activeThreadState.value?.threadGoal?.objective).toBe('Ship the web goal mode')
    expect(workspace.activeThreadState.value?.turns).toEqual([])

    await workspace.updateThreadGoalStatus('complete')
    await flushPromises()

    expect(socket.commands[socket.commands.length - 1]).toEqual({
      type: 'set_thread_goal',
      payload: {
        thread_id: 'thread-a',
        status: 'complete',
      },
    })
    expect(workspace.activeThreadState.value?.threadGoal?.status).toBe('complete')
    expect(workspace.activeThreadState.value?.completedThreadGoal?.status).toBe('complete')
    expect(workspace.activeThreadState.value?.turns).toEqual([])

    await workspace.clearThreadGoal()
    await flushPromises()

    expect(socket.commands[socket.commands.length - 1]).toEqual({
      type: 'clear_thread_goal',
      payload: { thread_id: 'thread-a' },
    })
    expect(workspace.activeThreadState.value?.threadGoal).toBeNull()
  })

  it('hydrates a directly returned thread goal without synthesizing a turn', async () => {
    const socket = new FakeCodexSocket()
    socket.getThreadGoalResponse = {
      thread_id: 'thread-a',
      objective: 'Keep going until green',
      status: 'active',
      token_budget: 9000,
      tokens_used: 100,
      time_used_seconds: 12,
      updated_at: 4,
    }
    const { workspace } = mountHarness(socket)
    await flushPromises()

    expect(workspace.activeThreadState.value?.threadGoal?.objective).toBe('Keep going until green')
    expect(workspace.activeThreadState.value?.threadGoal?.tokenBudget).toBe(9000)
    expect(workspace.activeThreadState.value?.turns).toEqual([])
  })

  it('accepts directly returned goals when setting a thread goal', async () => {
    const socket = new FakeCodexSocket()
    socket.returnDirectGoalResponse = true
    const { workspace } = mountHarness(socket)
    await flushPromises()

    await workspace.setThreadGoal('Direct response goal')
    await flushPromises()

    expect(workspace.activeThreadState.value?.threadGoal?.objective).toBe('Direct response goal')
    expect(workspace.activeThreadState.value?.turns).toEqual([])
  })

  it('implements plan requests by returning to build mode and sending the plan prompt', async () => {
    const socket = new FakeCodexSocket()
    const { workspace } = mountHarness(socket)
    await flushPromises()

    socket.emit({
      type: 'thread_state',
      payload: {
        thread_id: 'thread-a',
        state: {
          id: 'thread-a',
          latestCollaborationMode: {
            mode: 'plan',
            settings: {
              model: 'gpt-5.4',
              reasoning_effort: 'medium',
              developer_instructions: null,
            },
          },
          latestModel: 'gpt-5.4',
          latestReasoningEffort: 'medium',
          turns: [],
          requests: [
            {
              id: 'implement-plan:turn-1',
              method: 'item/plan/requestImplementation',
              params: {
                threadId: 'thread-a',
                turnId: 'turn-1',
                planContent: '1. Update composer\n2. Add tests',
              },
            },
          ],
        },
        queued_followups: [],
      },
    })
    await nextTick()

    expect(workspace.activeMode.value).toBe('plan')
    expect(workspace.activeUserInputRequest.value?.method).toBe('item/plan/requestImplementation')

    await workspace.submitUserInputResponse('implement-plan:turn-1', {
      decision: 'accept',
      planContent: '1. Update composer\n2. Add tests',
    })

    const defaultCollaborationMode = {
      mode: 'default',
      settings: {
        model: 'gpt-5.4',
        reasoning_effort: 'medium',
        developer_instructions: null,
      },
    }
    expect(socket.commands.slice(-2)).toEqual([
      {
        type: 'set_collaboration_mode',
        payload: {
          thread_id: 'thread-a',
          collaboration_mode: defaultCollaborationMode,
        },
      },
      {
        type: 'send_prompt',
        payload: {
          thread_id: 'thread-a',
          prompt: 'PLEASE IMPLEMENT THIS PLAN:\n1. Update composer\n2. Add tests',
          collaboration_mode: defaultCollaborationMode,
        },
      },
    ])
    expect(workspace.activeMode.value).toBe('build')
    expect(workspace.activeUserInputRequest.value).toBeNull()
  })

  it('renames the active thread with the existing single-argument call shape', async () => {
    const socket = new FakeCodexSocket()
    const { workspace } = mountHarness(socket)
    await flushPromises()

    await workspace.renameThread('Renamed active thread')
    await flushPromises()

    expect(socket.commands.slice(-2)).toEqual([
      {
        type: 'rename_thread',
        payload: {
          thread_id: 'thread-a',
          name: 'Renamed active thread',
        },
      },
      { type: 'list_threads', payload: {} },
    ])
    expect(workspace.activeThreadState.value?.title).toBe('Renamed active thread')
    expect(workspace.successMessage.value).toBe('Thread renamed.')
  })

  it('renames a specified thread without changing the active thread title', async () => {
    const socket = new FakeCodexSocket()
    const { workspace } = mountHarness(socket)
    await flushPromises()

    await workspace.renameThread('thread-b', 'Renamed inactive thread')
    await flushPromises()

    expect(socket.commands.slice(-2)).toEqual([
      {
        type: 'rename_thread',
        payload: {
          thread_id: 'thread-b',
          name: 'Renamed inactive thread',
        },
      },
      { type: 'list_threads', payload: {} },
    ])
    expect(workspace.activeThreadId.value).toBe('thread-a')
    expect(workspace.activeThreadState.value?.title).toBeUndefined()
    expect(workspace.successMessage.value).toBe('Thread renamed.')
  })

  it('forks a thread, refreshes the workspace, and selects the forked thread', async () => {
    const socket = new FakeCodexSocket()
    const { workspace } = mountHarness(socket)
    await flushPromises()

    await workspace.forkThread('thread-a')
    await flushPromises()

    expect(socket.commands.slice(-5)).toEqual([
      { type: 'fork_thread', payload: { thread_id: 'thread-a' } },
      { type: 'list_threads', payload: {} },
      { type: 'unsubscribe_thread', payload: { thread_id: 'thread-a' } },
      {
        type: 'subscribe_thread_delta',
        payload: { thread_id: 'thread-forked', cached_turn_ids: [] },
      },
      { type: 'get_thread_goal', payload: { thread_id: 'thread-forked' } },
    ])
    expect(workspace.activeThreadId.value).toBe('thread-forked')
    expect(workspace.successMessage.value).toBe('Thread forked.')
    expect(workspace.forkingThreadId.value).toBe('')
  })

  it('starts embed threads without using the persisted active thread', async () => {
    localStorage.setItem('yier.codex.active-thread-id', 'thread-a')
    const socket = new FakeCodexSocket()
    const { workspace } = mountHarness(socket, {
      persistActiveThread: false,
      selectInitialThread: false,
    })
    await flushPromises()

    expect(workspace.activeThreadId.value).toBe('')

    await workspace.startEmbedThread('/tmp/embed')
    await flushPromises()

    expect(socket.commands.slice(-4)).toEqual([
      { type: 'start_thread', payload: { project_path: '/tmp/embed' } },
      { type: 'list_threads', payload: {} },
      {
        type: 'subscribe_thread_delta',
        payload: { thread_id: 'thread-created', cached_turn_ids: [] },
      },
      { type: 'get_thread_goal', payload: { thread_id: 'thread-created' } },
    ])
    expect(workspace.activeThreadId.value).toBe('thread-created')
    expect(localStorage.getItem('yier.codex.active-thread-id')).toBe('thread-a')
  })

  it('resumes embed threads by subscribing to the requested thread', async () => {
    const socket = new FakeCodexSocket()
    const { workspace } = mountHarness(socket, {
      persistActiveThread: false,
      selectInitialThread: false,
    })
    await flushPromises()

    await workspace.resumeEmbedThread('thread-b')
    await flushPromises()

    expect(socket.commands.slice(-2)).toEqual([
      {
        type: 'subscribe_thread_delta',
        payload: { thread_id: 'thread-b', cached_turn_ids: [] },
      },
      { type: 'get_thread_goal', payload: { thread_id: 'thread-b' } },
    ])
    expect(workspace.activeThreadId.value).toBe('thread-b')
  })
})
