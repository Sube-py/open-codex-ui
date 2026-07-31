import { shallowMount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import CodexChatPane from '../components/CodexChatPane.vue'
import type {
  CodexConversationState,
  CodexPendingRequest,
  CodexQueuedFollowup,
  CodexSocketStatus,
  CodexWorkMode,
} from '../types'

const baseProps: {
  activeThreadId: string
  activeThreadState: CodexConversationState
  activeUserInputRequest: CodexPendingRequest | null
  activeStatus: string
  activeMode: CodexWorkMode
  queuedFollowups: CodexQueuedFollowup[]
  socketStatus: CodexSocketStatus
  reconnectState: {
    phase: 'idle' | 'open' | 'scheduled' | 'connecting' | 'offline'
    attempt: number
    nextDelayMs: number | null
  }
  isThreadLoading: boolean
} = {
  activeThreadId: 'thread-1',
  activeThreadState: { id: 'thread-1', turns: [] },
  activeUserInputRequest: null,
  activeStatus: 'idle',
  activeMode: 'build',
  queuedFollowups: [],
  socketStatus: 'open',
  reconnectState: { phase: 'open', attempt: 0, nextDelayMs: null },
  isThreadLoading: false,
}

function mountPane(activeUserInputRequest: CodexPendingRequest | null = null) {
  return shallowMount(CodexChatPane, {
    props: {
      ...baseProps,
      activeUserInputRequest,
    },
    global: {
      stubs: {
        CodexComposer: true,
        CodexConversation: true,
        CodexRequestPanel: true,
        CodexThreadToolbar: true,
      },
    },
  })
}

describe('CodexChatPane', () => {
  it('hides the composer while a user input request is active', () => {
    const request: CodexPendingRequest = {
      id: 'request-1',
      method: 'item/tool/requestUserInput',
      params: {
        turnId: 'turn-1',
      },
    }
    const wrapper = mountPane(request)

    expect(wrapper.findComponent({ name: 'CodexRequestPanel' }).exists()).toBe(true)
    expect(wrapper.findComponent({ name: 'CodexComposer' }).exists()).toBe(false)
  })

  it('shows the composer when no user input request is active', () => {
    const wrapper = mountPane()

    expect(wrapper.findComponent({ name: 'CodexRequestPanel' }).exists()).toBe(true)
    expect(wrapper.findComponent({ name: 'CodexComposer' }).exists()).toBe(true)
  })

  it('shows a conversation loading overlay and disables the composer while loading a thread', () => {
    const wrapper = shallowMount(CodexChatPane, {
      props: {
        ...baseProps,
        isThreadLoading: true,
      },
      global: {
        stubs: {
          CodexComposer: true,
          CodexConversation: true,
          CodexRequestPanel: true,
          CodexThreadToolbar: true,
        },
      },
    })

    expect(wrapper.get('[data-codex-thread-loading]').text()).toContain('Loading conversation')
    expect(wrapper.getComponent({ name: 'CodexComposer' }).props('disabled')).toBe(true)
  })

  it('shows thread git info when present', () => {
    const wrapper = shallowMount(CodexChatPane, {
      props: {
        ...baseProps,
        activeThreadState: {
          id: 'thread-1',
          turns: [],
          gitInfo: {
            branch: 'feature/goal-mode',
            sha: 'abcdef1234567890',
            originUrl: 'git@example.com:app/repo.git',
          },
        },
      },
      global: {
        stubs: {
          CodexComposer: true,
          CodexConversation: true,
          CodexRequestPanel: true,
          CodexThreadToolbar: true,
        },
      },
    })

    const gitInfo = wrapper.get('[data-codex-git-info]')
    expect(gitInfo.text()).toContain('feature/goal-mode')
    expect(gitInfo.text()).toContain('abcdef1')
    expect(gitInfo.text()).toContain('git@example.com:app/repo.git')
  })

  it('shows reconnect progress and removes it after recovery', async () => {
    const wrapper = shallowMount(CodexChatPane, {
      props: {
        ...baseProps,
        socketStatus: 'closed',
        reconnectState: { phase: 'scheduled', attempt: 3, nextDelayMs: 4_000 },
      },
      global: {
        stubs: {
          CodexComposer: true,
          CodexConversation: true,
          CodexRequestPanel: true,
          CodexThreadToolbar: true,
        },
      },
    })

    expect(wrapper.get('[data-codex-reconnect-notice]').text()).toContain(
      'Connection lost. Reconnecting (attempt 3) in 4s...',
    )

    await wrapper.setProps({
      socketStatus: 'open',
      reconnectState: { phase: 'open', attempt: 0, nextDelayMs: null },
    })

    expect(wrapper.find('[data-codex-reconnect-notice]').exists()).toBe(false)
  })

  it('shows an offline-specific reconnect notice', () => {
    const wrapper = shallowMount(CodexChatPane, {
      props: {
        ...baseProps,
        socketStatus: 'closed',
        reconnectState: { phase: 'offline', attempt: 1, nextDelayMs: null },
      },
      global: {
        stubs: {
          CodexComposer: true,
          CodexConversation: true,
          CodexRequestPanel: true,
          CodexThreadToolbar: true,
        },
      },
    })

    expect(wrapper.get('[data-codex-reconnect-notice]').text()).toContain(
      "You're offline. Reconnection will resume when online.",
    )
  })
})
