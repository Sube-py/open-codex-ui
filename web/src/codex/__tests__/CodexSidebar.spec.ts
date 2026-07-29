import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, ref } from 'vue'
import PrimeVue from 'primevue/config'

import { apiGet, apiPost, apiPut } from '../../lib/api'
import CodexSidebar from '../components/CodexSidebar.vue'
import type { CodexNativeSessionSummary, CodexWorkspaceResponse } from '../types'

vi.mock('../../lib/api', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPut: vi.fn(),
}))

const apiGetMock = vi.mocked(apiGet)
const apiPostMock = vi.mocked(apiPost)
const apiPutMock = vi.mocked(apiPut)

function thread(
  threadId: string,
  project: string,
  projectPath: string,
  updatedAt: number,
  overrides: Partial<CodexNativeSessionSummary> = {},
) {
  return {
    thread_id: threadId,
    title: threadId,
    preview: `${threadId} preview`,
    updated_at: updatedAt,
    started_at: updatedAt - 1,
    status: 'idle',
    cwd: projectPath,
    project,
    project_path: projectPath,
    source: 'appServer',
    ...overrides,
  }
}

function workspace(): CodexWorkspaceResponse {
  return {
    projects: [
      {
        project: 'beta',
        project_path: '/tmp/beta',
        session_count: 1,
        sessions: [thread('thread-beta', 'beta', '/tmp/beta', 10)],
      },
      {
        project: 'alpha',
        project_path: '/tmp/alpha',
        session_count: 2,
        sessions: [
          thread('thread-alpha-old', 'alpha', '/tmp/alpha', 15),
          thread('thread-alpha-new', 'alpha', '/tmp/alpha', 30),
        ],
      },
    ],
    paired_editors: [],
    remote_connections: [],
    recent_threads: [],
    active_remote_connection_id: '',
    remote_connection_statuses: {},
  }
}

const MenuStub = defineComponent({
  name: 'CodexMenuStub',
  props: {
    model: {
      type: Array,
      default: () => [],
    },
  },
  setup(props, { expose }) {
    const visible = ref(false)
    expose({
      toggle: () => {
        visible.value = !visible.value
      },
    })
    return () =>
      h(
        'div',
        { 'data-codex-thread-action-menu': '' },
        visible.value
          ? (props.model as Array<{ label: string; disabled?: boolean; command?: () => void }>).map(
              (item) =>
                h(
                  'button',
                  {
                    disabled: item.disabled,
                    'data-codex-thread-menu-item': item.label,
                    onClick: item.command,
                  },
                  item.label,
                ),
            )
          : [],
      )
  },
})

function mountSidebar(props: Partial<InstanceType<typeof CodexSidebar>['$props']> = {}) {
  const wrapper = mount(CodexSidebar, {
    props: {
      projectPath: '',
      workspace: workspace(),
      activeThreadId: '',
      ...props,
      'onUpdate:projectPath': (value: string) => wrapper.setProps({ projectPath: value }),
    },
    global: {
      plugins: [PrimeVue],
      directives: {
        tooltip: {
          mounted(element: HTMLElement, binding: { value: string }) {
            element.dataset.tooltip = binding.value
          },
        },
      },
      stubs: {
        Dialog: {
          props: ['visible', 'header'],
          emits: ['update:visible'],
          template:
            '<section v-if="visible" data-dialog-stub><h2>{{ header }}</h2><slot /><footer><slot name="footer" /></footer></section>',
        },
        CodexHostPathPicker: {
          props: [
            'visible',
            'selectedPath',
            'disabled',
            'title',
            'allowFiles',
            'allowCurrentFolder',
            'hostId',
          ],
          emits: ['update:visible', 'select'],
          template:
            "<div data-codex-host-path-picker-stub :data-selected-path=\"selectedPath\" :data-host-id=\"hostId\"><button v-if=\"allowFiles\" data-codex-identity-picker-select @click=\"$emit('select', '/home/test/.ssh/id_ed25519')\">Select identity</button><button v-else data-codex-picker-select @click=\"$emit('select', hostId && hostId !== 'local' ? '/srv/selected' : '/tmp/selected')\">Select</button></div>",
        },
        Select: {
          inheritAttrs: false,
          props: ['modelValue', 'options', 'optionLabel', 'optionValue'],
          emits: ['update:modelValue'],
          template:
            '<select v-bind="$attrs" :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value)"><option value=""></option><option v-for="option in options" :key="option[optionValue]" :value="option[optionValue]">{{ option[optionLabel] }}</option></select>',
        },
        Menu: MenuStub,
      },
    },
  })
  return wrapper
}

describe('CodexSidebar', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
    apiGetMock.mockReset()
    apiGetMock.mockResolvedValue({ hosts: [] })
    apiPostMock.mockReset()
    apiPutMock.mockReset()
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: vi.fn().mockResolvedValue(undefined),
      },
    })
  })

  it('uses native scrolling for the thread list', () => {
    const wrapper = mountSidebar()
    const scrollContainer = wrapper.get('[data-codex-sidebar-scroll]')

    expect(scrollContainer.classes()).toEqual(
      expect.arrayContaining([
        'codex-scrollbar',
        'overflow-y-auto',
        'overscroll-contain',
        'touch-pan-y',
      ]),
    )
    expect(wrapper.find('.p-scrollpanel').exists()).toBe(false)
  })

  it('sorts project groups and threads by latest usage time', () => {
    const wrapper = mountSidebar()
    const projectButtons = wrapper.findAll('[data-codex-project-toggle]')

    expect(projectButtons[0]?.text()).toContain('alpha')
    expect(projectButtons[1]?.text()).toContain('beta')

    const text = wrapper.text()
    expect(text.indexOf('thread-alpha-new')).toBeLessThan(text.indexOf('thread-alpha-old'))
  })

  it('expands the latest project and the active thread project by default', () => {
    const wrapper = mountSidebar({ activeThreadId: 'thread-beta' })
    const projectButtons = wrapper.findAll('[data-codex-project-toggle]')

    expect(projectButtons[0]?.attributes('aria-expanded')).toBe('true')
    expect(projectButtons[1]?.attributes('aria-expanded')).toBe('true')
    expect(wrapper.text()).toContain('thread-alpha-new')
    expect(wrapper.text()).toContain('thread-beta')
  })

  it('persists project collapse toggles', async () => {
    const wrapper = mountSidebar()
    const alphaButton = wrapper.findAll('[data-codex-project-toggle]')[0]!

    await alphaButton.trigger('click')

    expect(alphaButton.attributes('aria-expanded')).toBe('false')
    expect(
      JSON.parse(localStorage.getItem('yier.codex.sidebar.expanded-projects') ?? '{}'),
    ).toEqual({
      'local::/tmp/alpha': false,
    })
  })

  it('adds a local project without starting a thread', async () => {
    apiPostMock.mockResolvedValueOnce({ id: 'project-local' })
    const wrapper = mountSidebar()

    expect(wrapper.find('input[placeholder="Project path"]').exists()).toBe(false)
    expect(wrapper.find('[data-codex-project-path-display]').exists()).toBe(false)
    expect(wrapper.find('[data-codex-start-thread]').exists()).toBe(false)
    expect(wrapper.find('[aria-label="Refresh Codex threads"]').exists()).toBe(false)

    await wrapper.get('[data-codex-add-project]').trigger('click')
    await wrapper.get('[data-codex-project-browse]').trigger('click')
    await wrapper.get('[data-codex-picker-select]').trigger('click')
    await wrapper.get('[data-codex-project-save]').trigger('click')

    expect(apiPostMock).toHaveBeenCalledWith('/api/codex/projects', {
      name: '',
      kind: 'local',
      host_id: 'local',
      project_path: '/tmp/selected',
    })
    expect(wrapper.emitted('startThread')).toBeUndefined()
    expect(wrapper.emitted('projectChanged')).toHaveLength(1)
  })

  it('starts new threads from project row actions', async () => {
    const wrapper = mountSidebar()

    await wrapper.findAll('[data-codex-project-start-thread]')[0]!.trigger('click')

    expect(wrapper.emitted('startThread')).toEqual([['/tmp/alpha', 'local']])
  })

  it('renders projects before projectless Chats and settings at the sidebar bottom', () => {
    const wrapper = mountSidebar({
      workspace: {
        ...workspace(),
        recent_threads: [thread('thread-recent', 'other', '/tmp/other', 40)],
      },
    })

    const projectButtons = wrapper.findAll('[data-codex-project-toggle]')
    expect(projectButtons.map((button) => button.text())).toEqual(
      expect.arrayContaining(['alpha', 'beta', 'Chats']),
    )
    expect(projectButtons[0]?.text()).toContain('alpha')
    expect(projectButtons[1]?.text()).toContain('beta')
    expect(projectButtons[2]?.text()).toContain('Chats')
    expect(wrapper.text()).toContain('thread-recent')
    expect(wrapper.find('[data-codex-add-remote]').exists()).toBe(false)
    expect(wrapper.get('[data-codex-open-settings]').text()).toContain('Settings')
  })

  it('limits expanded sections while keeping the active thread visible', async () => {
    const projectThreads = Array.from({ length: 15 }, (_, index) =>
      thread(`project-thread-${index + 1}`, 'large', '/tmp/large', 200 - index),
    )
    const chatThreads = Array.from({ length: 52 }, (_, index) =>
      thread(`chat-thread-${index + 1}`, 'other', '/tmp/other', 100 - index),
    )
    const wrapper = mountSidebar({
      activeThreadId: 'project-thread-15',
      workspace: {
        projects: [
          {
            project: 'large',
            project_path: '/tmp/large',
            session_count: projectThreads.length,
            sessions: projectThreads,
          },
        ],
        paired_editors: [],
        recent_threads: chatThreads,
      },
    })

    const projectSection = wrapper.get('[data-codex-section-key="local::/tmp/large"]')
    const chatsSection = wrapper.get('[data-codex-section-key="chats"]')
    expect(projectSection.findAll('[data-codex-thread-row]')).toHaveLength(11)
    expect(projectSection.text()).toContain('project-thread-15')
    expect(projectSection.text()).not.toContain('project-thread-11')
    expect(projectSection.get('[data-codex-show-more-threads]').text()).toContain('Show 4 more')
    expect(chatsSection.findAll('[data-codex-thread-row]')).toHaveLength(50)
    expect(chatsSection.get('[data-codex-show-more-threads]').text()).toContain('Show 2 more')

    await projectSection.get('[data-codex-show-more-threads]').trigger('click')
    await chatsSection.get('[data-codex-show-more-threads]').trigger('click')

    expect(projectSection.findAll('[data-codex-thread-row]')).toHaveLength(15)
    expect(projectSection.find('[data-codex-show-more-threads]').exists()).toBe(false)
    expect(chatsSection.findAll('[data-codex-thread-row]')).toHaveLength(52)
    expect(chatsSection.find('[data-codex-show-more-threads]').exists()).toBe(false)
  })

  it('creates and manages SSH remote connections without switching the thread list', async () => {
    apiPostMock
      .mockResolvedValueOnce({
        connection: {
          id: 'remote-1',
          display_name: 'Build host',
          ssh_host: 'user@host',
          ssh_port: 2222,
          ssh_alias: '',
          identity_file: '~/.ssh/build',
          auto_connect: true,
        },
      })
      .mockResolvedValueOnce({ ok: true, detail: 'codex 1.2.3' })
      .mockResolvedValueOnce({ ok: true })
      .mockResolvedValueOnce({ ok: true, detail: 'installed' })

    const wrapper = mountSidebar({
      workspace: {
        ...workspace(),
        remote_connections: [
          {
            id: 'remote-1',
            display_name: 'Build host',
            ssh_host: 'user@host',
            ssh_port: 2222,
            ssh_alias: '',
            identity_file: '~/.ssh/build',
            auto_connect: true,
          },
        ],
        remote_connection_statuses: {
          'remote-1': { status: 'connected', detail: 'codex 1.2.3' },
        },
      },
    })

    await wrapper.get('[data-codex-open-settings]').trigger('click')
    await wrapper.get('[data-codex-add-remote]').trigger('click')
    expect(wrapper.get('[data-codex-remote-host]').attributes('placeholder')).toBe(
      'server.example.com',
    )
    expect(wrapper.get('[data-codex-remote-port]').classes()).toEqual(
      expect.arrayContaining(['min-w-0', 'w-full']),
    )
    await wrapper.get('[data-codex-remote-display-name]').setValue('Build host')
    await wrapper.get('[data-codex-remote-host]').setValue('host')
    await wrapper.get('[data-codex-remote-username]').setValue('user')
    await wrapper.get('[data-codex-remote-port]').setValue('2222')
    await wrapper.get('[data-codex-browse-remote-identity]').trigger('click')
    await wrapper.get('[data-codex-remote-identity]').setValue('/home/test/.ssh/id_ed25519')
    expect(wrapper.get('[data-codex-remote-identity]').element).toHaveProperty(
      'value',
      '/home/test/.ssh/id_ed25519',
    )
    await wrapper.get('[data-codex-save-remote]').trigger('click')

    expect(apiPostMock).toHaveBeenNthCalledWith(1, '/api/codex/remote-connections', {
      display_name: 'Build host',
      ssh_host: 'host',
      ssh_username: 'user',
      ssh_port: 2222,
      ssh_alias: '',
      identity_file: '/home/test/.ssh/id_ed25519',
      auto_connect: false,
    })
    expect(wrapper.emitted('remoteConnectionChanged')).toHaveLength(1)

    await wrapper.get('[data-codex-test-remote]').trigger('click')
    expect(apiPostMock).toHaveBeenNthCalledWith(
      2,
      '/api/codex/remote-connections/remote-1/test',
      {},
    )

    expect(wrapper.get('[data-codex-remote-runtime-status]').text()).toContain('Connected')
    expect(wrapper.get('[data-codex-restart-remote]').attributes('data-tooltip')).toBe(
      'Restart the remote Codex connection',
    )
    expect(wrapper.get('[data-codex-install-remote]').attributes('data-tooltip')).toBe(
      'Install Codex on this server',
    )
    expect(wrapper.get('[data-codex-test-remote]').attributes('data-tooltip')).toBe(
      'Test SSH and Codex availability',
    )
    expect(wrapper.get('[data-codex-edit-remote]').attributes('data-tooltip')).toBe(
      'Edit this SSH connection',
    )
    expect(wrapper.get('[data-codex-delete-remote]').attributes('data-tooltip')).toBe(
      'Delete this SSH connection',
    )

    await wrapper.get('[data-codex-restart-remote]').trigger('click')
    expect(apiPostMock).toHaveBeenNthCalledWith(
      3,
      '/api/codex/remote-connections/remote-1/restart',
      {},
    )

    await wrapper.get('[data-codex-install-remote]').trigger('click')
    expect(apiPostMock).toHaveBeenNthCalledWith(
      4,
      '/api/codex/remote-connections/remote-1/install',
      {},
    )

    const connectionToggle = wrapper.get('[data-codex-toggle-remote]')
    expect(connectionToggle.attributes('data-tooltip')).toBe('Disconnect this SSH server')
    await connectionToggle.get('input').setValue(false)
    await flushPromises()
    expect(apiPutMock).toHaveBeenCalledWith('/api/codex/remote-connections/remote-1/auto-connect', {
      auto_connect: false,
    })
    expect(wrapper.get('[data-codex-restart-remote]').attributes('disabled')).toBeDefined()
    expect(wrapper.emitted('remoteConnectionChanged')).toHaveLength(4)

    expect(wrapper.find('[data-codex-login-api-key-remote]').exists()).toBe(false)
    expect(wrapper.find('[data-codex-start-remote-thread]').exists()).toBe(false)
    expect(apiPostMock).toHaveBeenCalledTimes(4)
  })

  it('updates SSH remote connections from the edit dialog', async () => {
    apiPutMock.mockResolvedValueOnce({
      connection: {
        id: 'remote-1',
        display_name: 'Edited',
        ssh_host: 'user@host',
        ssh_port: null,
        ssh_alias: 'prod',
        identity_file: '',
        auto_connect: false,
      },
    })
    const wrapper = mountSidebar({
      workspace: {
        ...workspace(),
        remote_connections: [
          {
            id: 'remote-1',
            display_name: 'Build host',
            ssh_host: 'user@host',
            ssh_port: null,
            ssh_alias: 'prod',
            identity_file: '',
            auto_connect: false,
          },
        ],
      },
    })

    await wrapper.get('[data-codex-open-settings]').trigger('click')
    await wrapper.get('[data-codex-edit-remote]').trigger('click')
    const modeButtons = wrapper.get('[data-codex-remote-connection-mode]').findAll('button')
    expect(modeButtons[1]?.attributes('aria-pressed')).toBe('true')
    expect(wrapper.find('[data-codex-remote-host]').exists()).toBe(false)
    await wrapper.get('[data-codex-remote-display-name]').setValue('Edited')
    await wrapper.get('[data-codex-save-remote]').trigger('click')

    expect(apiPutMock).toHaveBeenCalledWith('/api/codex/remote-connections/remote-1', {
      display_name: 'Edited',
      ssh_host: '',
      ssh_username: '',
      ssh_port: null,
      ssh_alias: 'prod',
      identity_file: '',
      auto_connect: false,
    })
    expect(wrapper.emitted('remoteConnectionChanged')).toHaveLength(1)
  })

  it('selects SSH config aliases discovered from the user config', async () => {
    apiGetMock.mockResolvedValueOnce({
      hosts: [
        {
          alias: 'build-box',
          hostname: 'build.example.com',
          port: 2222,
          identity_file: '~/.ssh/id_ed25519',
        },
      ],
    })
    apiPostMock.mockResolvedValueOnce({ connection: { id: 'build' } })
    const wrapper = mountSidebar()

    await wrapper.get('[data-codex-open-settings]').trigger('click')
    await wrapper.get('[data-codex-add-remote]').trigger('click')
    const modeButtons = wrapper.get('[data-codex-remote-connection-mode]').findAll('button')
    await modeButtons[1]!.trigger('click')
    await flushPromises()

    expect(apiGetMock).toHaveBeenCalledWith('/api/codex/ssh-config-hosts')
    await wrapper.get('[data-codex-remote-alias]').setValue('build-box')
    await wrapper.get('[data-codex-save-remote]').trigger('click')

    expect(apiPostMock).toHaveBeenCalledWith('/api/codex/remote-connections', {
      display_name: '',
      ssh_host: '',
      ssh_username: '',
      ssh_port: null,
      ssh_alias: 'build-box',
      identity_file: '',
      auto_connect: false,
    })
  })

  it('renders compact thread rows under project names', () => {
    const recentUpdatedAt = Math.floor(Date.now() / 1000) - 180
    const wrapper = mountSidebar({
      workspace: {
        projects: [
          {
            project: 'gamma',
            project_path: '/tmp/gamma',
            session_count: 1,
            sessions: [
              thread('thread-gamma', 'gamma', '/tmp/gamma', recentUpdatedAt, {
                title: 'Investigate bug',
              }),
            ],
          },
        ],
        paired_editors: [],
      },
    })

    expect(wrapper.get('[data-codex-project-toggle]').text()).toContain('gamma')
    const threadRow = wrapper.get('[data-codex-thread-row]')
    expect(threadRow.text()).toContain('Investigate bug')
    expect(threadRow.text()).toContain('3m')
    expect(threadRow.text()).not.toContain('/tmp/gamma')
  })

  it('keeps local and remote projects separate when paths match', async () => {
    const wrapper = mountSidebar({
      workspace: {
        projects: [
          {
            project: 'app',
            project_path: '/srv/app',
            host_id: 'local',
            session_count: 1,
            sessions: [
              thread('thread-local', 'app', '/srv/app', 20, {
                host_id: 'local',
                title: 'Local work',
              }),
            ],
          },
          {
            project: 'app',
            project_path: '/srv/app',
            host_id: 'ssh:build',
            session_count: 1,
            sessions: [
              thread('thread-remote', 'app', '/srv/app', 30, {
                host_id: 'ssh:build',
                title: 'Remote work',
              }),
            ],
          },
        ],
        paired_editors: [],
        remote_connections: [
          {
            id: 'build',
            display_name: 'Build host',
            ssh_host: 'build.example.com',
            ssh_port: 22,
            ssh_alias: 'build-box',
            identity_file: '~/.ssh/id_ed25519',
            auto_connect: false,
          },
        ],
        remote_connection_statuses: {
          build: { status: 'connected', detail: 'Codex ready' },
        },
      },
    })

    expect(wrapper.findAll('[data-codex-project-toggle]')).toHaveLength(2)
    expect(wrapper.text()).toContain('Remote work')
    expect(wrapper.find('[data-codex-thread-host]').exists()).toBe(false)

    const projectIcons = wrapper.findAll('[data-codex-project-source-icon]')
    expect(projectIcons.map((item) => item.attributes('data-source'))).toEqual(['remote', 'local'])
    expect(projectIcons[0]?.find('svg').exists()).toBe(true)
    expect(wrapper.get('[data-codex-project-alias]').text()).toBe('build-box')
    expect(wrapper.get('[data-codex-project-status]').attributes()).toMatchObject({
      'aria-label': 'build-box: Connected - Codex ready',
      'data-status': 'connected',
    })
    expect(wrapper.get('[data-codex-project-remote-meta]').classes()).toEqual(
      expect.arrayContaining(['group-hover/project:hidden', 'group-focus-within/project:hidden']),
    )
    expect(wrapper.get('[data-codex-project-row]').classes()).toContain('relative')
    expect(wrapper.get('[data-codex-project-action-spacer]').classes()).toEqual(
      expect.arrayContaining(['hidden', 'w-7', 'group-hover/project:block']),
    )
    expect(wrapper.findAll('[data-codex-project-start-thread]')[0]!.classes()).toEqual(
      expect.arrayContaining(['!absolute', 'right-0', 'group-hover/project:opacity-100']),
    )

    await wrapper
      .findAll('[data-codex-thread-name]')
      .find((row) => row.text().includes('Remote work'))!
      .trigger('click')

    expect(wrapper.emitted('selectThread')?.[0]).toEqual(['thread-remote'])
  })

  it('emits fork, copy, and archive actions from thread controls', async () => {
    const wrapper = mountSidebar()

    await wrapper
      .get('button[aria-label="Open Codex thread actions thread-alpha-new"]')
      .trigger('click')
    await wrapper.get('[data-codex-thread-menu-item="Fork"]').trigger('click')
    await wrapper.get('[data-codex-thread-menu-item="Copy ID"]').trigger('click')
    await wrapper.get('[data-codex-archive-thread]').trigger('click')

    expect(wrapper.emitted('forkThread')).toEqual([['thread-alpha-new']])
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('thread-alpha-new')
    expect(wrapper.emitted('archiveThread')).toEqual([['thread-alpha-new']])
  })

  it('emits a copy error when clipboard access fails', async () => {
    vi.mocked(navigator.clipboard.writeText).mockRejectedValueOnce(new Error('blocked'))
    const wrapper = mountSidebar()

    await wrapper
      .get('button[aria-label="Open Codex thread actions thread-alpha-new"]')
      .trigger('click')
    await wrapper.get('[data-codex-thread-menu-item="Copy ID"]').trigger('click')

    expect(wrapper.emitted('copyError')).toEqual([['Unable to copy thread id.']])
  })

  it('shows a spinner and hides archive controls for working threads', async () => {
    const wrapper = mountSidebar({
      workspace: {
        projects: [
          {
            project: 'alpha',
            project_path: '/tmp/alpha',
            session_count: 1,
            sessions: [
              thread('thread-working', 'alpha', '/tmp/alpha', 30, {
                status: 'in_progress',
              }),
            ],
          },
        ],
        paired_editors: [],
      },
    })

    expect(wrapper.find('[data-codex-thread-working-indicator]').exists()).toBe(true)
    expect(wrapper.find('[data-codex-thread-time]').exists()).toBe(false)
    expect(wrapper.find('[data-codex-archive-thread]').exists()).toBe(false)

    await wrapper
      .get('button[aria-label="Open Codex thread actions thread-working"]')
      .trigger('click')

    expect(wrapper.get('[data-codex-thread-menu-item="Fork"]').attributes('disabled')).toBeDefined()
    expect(
      wrapper.get('[data-codex-thread-menu-item="Copy ID"]').attributes('disabled'),
    ).toBeUndefined()
  })

  it('renames threads inline from the thread row', async () => {
    const wrapper = mountSidebar()

    await wrapper.get('[data-codex-thread-name]').trigger('dblclick')
    await wrapper.get('[data-codex-thread-rename-input]').setValue('Renamed thread')
    await wrapper.get('[data-codex-thread-rename-input]').trigger('keydown.enter')

    expect(wrapper.emitted('renameThread')).toEqual([['thread-alpha-new', 'Renamed thread']])
  })

  it('cancels inline thread rename with Escape', async () => {
    const wrapper = mountSidebar()

    await wrapper.get('[data-codex-thread-name]').trigger('dblclick')
    await wrapper.get('[data-codex-thread-rename-input]').setValue('Renamed thread')
    await wrapper.get('[data-codex-thread-rename-input]').trigger('keydown.esc')

    expect(wrapper.find('[data-codex-thread-rename-input]').exists()).toBe(false)
    expect(wrapper.emitted('renameThread')).toBeUndefined()
  })
})
