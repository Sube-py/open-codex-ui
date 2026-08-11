import { flushPromises, shallowMount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'

import CodexView from '../../views/CodexView.vue'
import { createTestRouter } from '../../router'
import type { CodexConversationState } from '../types'

const workspaceMock: {
  activeThreadState: CodexConversationState | null
  [key: string]: unknown
} = {
  activeMode: 'build',
  activeStatus: 'idle',
  activeThreadId: '',
  activeThreadState: null,
  activeUserInputRequest: null,
  archivingThreadId: '',
  archiveThread: vi.fn(),
  compactThread: vi.fn(),
  enqueueFollowup: vi.fn(),
  errorMessage: '',
  forkingThreadId: '',
  forkThread: vi.fn(),
  isActiveTurnInProgress: false,
  isActiveThreadLoading: false,
  isArchiving: false,
  isBooting: false,
  isCommandBusy: false,
  isLoadingMoreRecentThreads: false,
  isRenaming: false,
  loadMoreRecentThreads: vi.fn(),
  openingThreadId: '',
  projectPathDraft: '',
  queuedFollowups: [],
  refreshRemoteConnections: vi.fn().mockResolvedValue(undefined),
  refreshWorkspace: vi.fn(),
  refreshWorkspaceAndSelect: vi.fn().mockResolvedValue(undefined),
  removeFollowup: vi.fn(),
  renameThread: vi.fn(),
  resumeEmbedThread: vi.fn(),
  selectThread: vi.fn(),
  sendPrompt: vi.fn(),
  setMode: vi.fn(),
  startEmbedThread: vi.fn(),
  startThread: vi.fn(),
  status: 'idle',
  steerPrompt: vi.fn(),
  submitUserInputResponse: vi.fn(),
  successMessage: '',
  workspace: { paired_editors: [], projects: [] },
  interruptTurn: vi.fn(),
}

vi.mock('../composables/useCodexWorkspace', () => ({
  useCodexWorkspace: () => workspaceMock,
}))

function mountCodexView(router: ReturnType<typeof createTestRouter>) {
  return shallowMount(CodexView, {
    global: {
      plugins: [router],
      stubs: {
        CodexComposer: true,
        CodexConversation: true,
        CodexChatPane: true,
        CodexRequestPanel: true,
        CodexSidebar: true,
        CodexThreadToolbar: true,
        RouterLink: false,
        Teleport: true,
        Transition: true,
      },
    },
  })
}

describe('Codex route separation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    workspaceMock.activeThreadState = null
    workspaceMock.isActiveThreadLoading = false
  })

  it('resolves Codex as the default workspace route', () => {
    const router = createTestRouter()
    const rootMatch = router.resolve('/').matched
    const codexMatch = router.resolve('/codex').matched
    const embedMatch = router.resolve('/codex/embed').matched
    const chatMatch = router.resolve('/chat').matched
    const codexComponent = codexMatch[codexMatch.length - 1]?.components?.default
    const embedComponent = embedMatch[embedMatch.length - 1]?.components?.default

    expect(rootMatch[0]?.redirect).toBe('/codex')
    expect(router.resolve('/codex').name).toBe('codex')
    expect(router.resolve('/codex/embed').name).toBe('codex-embed')
    expect(router.resolve('/chat').name).toBeUndefined()
    expect(codexMatch).toHaveLength(1)
    expect(embedMatch).toHaveLength(1)
    expect(chatMatch).toHaveLength(0)
    expect(embedComponent).not.toBe(codexComponent)
  })

  it('does not render a Chat route link in the Codex header', async () => {
    const router = createTestRouter()
    await router.push('/codex')
    await router.isReady()

    const wrapper = mountCodexView(router)

    expect(wrapper.findAll('a').map((link) => link.attributes('href'))).not.toContain('/chat')
  })

  it('refreshes SSH metadata before updating remote thread history', async () => {
    const router = createTestRouter()
    await router.push('/codex')
    await router.isReady()
    const wrapper = mountCodexView(router)
    const sidebar = wrapper.getComponent({ name: 'CodexSidebar' })

    sidebar.vm.$emit('remoteConnectionChanged')
    await flushPromises()

    expect(workspaceMock.refreshRemoteConnections).toHaveBeenCalledTimes(1)
    expect(workspaceMock.refreshWorkspaceAndSelect).toHaveBeenCalledTimes(1)

    sidebar.vm.$emit('projectChanged')
    await flushPromises()

    expect(workspaceMock.refreshRemoteConnections).toHaveBeenCalledTimes(1)
    expect(workspaceMock.refreshWorkspaceAndSelect).toHaveBeenCalledTimes(2)
  })

  it('centers the active thread title in the page header without hover styling', async () => {
    workspaceMock.activeThreadState = {
      id: 'thread-title',
      title: 'A very long Codex thread title that should truncate in the page header',
      turns: [],
    }
    const router = createTestRouter()
    await router.push('/codex')
    await router.isReady()

    const wrapper = mountCodexView(router)
    const title = wrapper.get('[data-codex-page-title]')

    expect(title.text()).toBe(
      'A very long Codex thread title that should truncate in the page header',
    )
    expect(title.classes()).toEqual(expect.arrayContaining(['truncate', 'text-center', 'min-w-0']))

    const linksAndButtons = [
      ...wrapper.findAll('a').map((item) => item.classes()),
      ...wrapper.findAll('button').map((item) => item.classes()),
    ].flat()
    expect(linksAndButtons).not.toContain('hover:border-[color:var(--app-accent)]')
  })

  it('hides the connection status label on mobile', async () => {
    workspaceMock.status = 'open'
    const router = createTestRouter()
    await router.push('/codex')
    await router.isReady()

    const wrapper = mountCodexView(router)

    expect(wrapper.get('[data-codex-connection-status]').text()).toBe('Codex open')
    expect(wrapper.get('[data-codex-connection-status]').classes()).toContain('max-sm:hidden')
  })

  it('opens the mobile thread drawer and closes it after selecting a thread', async () => {
    const router = createTestRouter()
    await router.push('/codex')
    await router.isReady()
    const wrapper = mountCodexView(router)

    expect(wrapper.find('[data-codex-mobile-thread-drawer]').exists()).toBe(false)

    await wrapper.get('[data-codex-mobile-thread-drawer-open]').trigger('click')

    expect(wrapper.find('[data-codex-mobile-thread-drawer]').exists()).toBe(true)
    expect(wrapper.find('[data-codex-mobile-thread-drawer-close]').exists()).toBe(false)

    const sidebars = wrapper.findAllComponents({ name: 'CodexSidebar' })
    expect(sidebars).toHaveLength(2)

    const mobileSidebar = sidebars.find(
      (sidebar) => sidebar.attributes('data-codex-mobile-thread-sidebar') !== undefined,
    )

    if (!mobileSidebar) {
      throw new Error('Expected Codex mobile drawer to render a sidebar.')
    }

    await mobileSidebar.vm.$emit('select-thread', 'thread-mobile')
    await nextTick()

    expect(workspaceMock.selectThread).toHaveBeenCalledWith('thread-mobile')
    expect(wrapper.find('[data-codex-mobile-thread-drawer]').exists()).toBe(false)
  })

  it('closes the mobile thread drawer after starting a thread', async () => {
    const router = createTestRouter()
    await router.push('/codex')
    await router.isReady()
    const wrapper = mountCodexView(router)

    await wrapper.get('[data-codex-mobile-thread-drawer-open]').trigger('click')
    const mobileSidebar = wrapper
      .findAllComponents({ name: 'CodexSidebar' })
      .find((sidebar) => sidebar.attributes('data-codex-mobile-thread-sidebar') !== undefined)

    if (!mobileSidebar) {
      throw new Error('Expected Codex mobile drawer to render a sidebar.')
    }

    await mobileSidebar.vm.$emit('start-thread', '/tmp/mobile-project')
    await nextTick()

    expect(workspaceMock.startThread).toHaveBeenCalledWith('/tmp/mobile-project')
    expect(wrapper.find('[data-codex-mobile-thread-drawer]').exists()).toBe(false)
  })

  it('passes sidebar rename events to the Codex workspace', async () => {
    const router = createTestRouter()
    await router.push('/codex')
    await router.isReady()
    const wrapper = mountCodexView(router)

    const desktopSidebar = wrapper.findAllComponents({ name: 'CodexSidebar' })[0]
    if (!desktopSidebar) {
      throw new Error('Expected Codex desktop sidebar to render.')
    }

    await desktopSidebar.vm.$emit('rename-thread', 'thread-a', 'Renamed')

    expect(workspaceMock.renameThread).toHaveBeenCalledWith('thread-a', 'Renamed')
  })

  it('passes Recents pagination events to the Codex workspace', async () => {
    const router = createTestRouter()
    await router.push('/codex')
    await router.isReady()
    const wrapper = mountCodexView(router)
    const sidebar = wrapper.findAllComponents({ name: 'CodexSidebar' })[0]

    if (!sidebar) {
      throw new Error('Expected Codex desktop sidebar to render.')
    }
    await sidebar.vm.$emit('show-more-recents')

    expect(workspaceMock.loadMoreRecentThreads).toHaveBeenCalledTimes(1)
  })
})
