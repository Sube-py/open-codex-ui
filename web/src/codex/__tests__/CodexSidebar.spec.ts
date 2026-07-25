import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, ref } from 'vue'
import PrimeVue from 'primevue/config'

import { apiPost, apiPut } from '../../lib/api'
import CodexSidebar from '../components/CodexSidebar.vue'
import type { CodexNativeSessionSummary, CodexWorkspaceResponse } from '../types'

vi.mock('../../lib/api', () => ({
  apiPost: vi.fn(),
  apiPut: vi.fn(),
}))

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
    active_remote_connection_id: '',
    remote_connection_statuses: {},
  }
}

const MenuStub = defineComponent({
  name: 'Menu',
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
  let wrapper: ReturnType<typeof mount>
  wrapper = mount(CodexSidebar, {
    props: {
      projectPath: '',
      workspace: workspace(),
      activeThreadId: '',
      ...props,
      'onUpdate:projectPath': (value: string) =>
        wrapper.setProps({ projectPath: value }),
    },
    global: {
      plugins: [PrimeVue],
      stubs: {
        CodexHostPathPicker: {
          props: [
            'visible',
            'selectedPath',
            'disabled',
            'title',
            'allowFiles',
            'allowCurrentFolder',
          ],
          emits: ['update:visible', 'select'],
          template:
            '<div data-codex-host-path-picker-stub :data-selected-path="selectedPath"><button v-if="title" data-codex-identity-picker-select @click="$emit(\'select\', \'/home/test/.ssh/id_ed25519\')">Select identity</button><button v-else data-codex-picker-select @click="$emit(\'select\', \'/tmp/selected\')">Select</button></div>',
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
    apiPostMock.mockReset()
    apiPutMock.mockReset()
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: vi.fn().mockResolvedValue(undefined),
      },
    })
  })

  it('sorts project groups and threads by latest usage time', () => {
    const wrapper = mountSidebar()
    const projectButtons = wrapper.findAll('[data-codex-project-toggle]')

    expect(projectButtons[0]?.text()).toContain('alpha')
    expect(projectButtons[1]?.text()).toContain('beta')

    const text = wrapper.text()
    expect(text.indexOf('thread-alpha-new')).toBeLessThan(
      text.indexOf('thread-alpha-old'),
    )
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
    expect(JSON.parse(localStorage.getItem('yier.codex.sidebar.expanded-projects') ?? '{}')).toEqual({
      'local::/tmp/alpha': false,
    })
  })

  it('starts a thread immediately after selecting a host folder', async () => {
    const wrapper = mountSidebar()

    expect(wrapper.find('input[placeholder="Project path"]').exists()).toBe(false)
    expect(wrapper.find('[data-codex-project-path-display]').exists()).toBe(false)
    expect(wrapper.find('[data-codex-start-thread]').exists()).toBe(false)
    expect(wrapper.find('[aria-label="Refresh Codex threads"]').exists()).toBe(false)

    await wrapper.get('[data-codex-picker-select]').trigger('click')

    expect(wrapper.emitted('startThread')).toEqual([['/tmp/selected', 'local']])
  })

  it('starts new threads from project row actions', async () => {
    const wrapper = mountSidebar()

    await wrapper.findAll('[data-codex-project-start-thread]')[0]!.trigger('click')

    expect(wrapper.emitted('startThread')).toEqual([['/tmp/alpha', 'local']])
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
          remote_path: '/srv/app',
          auto_connect: true,
        },
      })
      .mockResolvedValueOnce({ ok: true, detail: 'codex 1.2.3' })
      .mockResolvedValueOnce({ ok: true })
      .mockResolvedValueOnce({ ok: true, detail: 'installed' })
      .mockResolvedValueOnce({ ok: true, detail: 'Signed in with apiKey.' })

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
            remote_path: '/srv/app',
            auto_connect: true,
          },
        ],
        remote_connection_statuses: {
          'remote-1': { status: 'connected', detail: 'codex 1.2.3' },
        },
      },
    })

    await wrapper.get('[data-codex-add-remote]').trigger('click')
    await wrapper.get('[data-codex-remote-display-name]').setValue('Build host')
    await wrapper.get('[data-codex-remote-host]').setValue('host')
    await wrapper.get('[data-codex-remote-username]').setValue('user')
    await wrapper.get('[data-codex-remote-port]').setValue('2222')
    await wrapper.get('[data-codex-browse-remote-identity]').trigger('click')

    const identityPicker = wrapper
      .findAll('[data-codex-host-path-picker-stub]')
      .find((picker) => picker.find('[data-codex-identity-picker-select]').exists())
    expect(identityPicker).toBeDefined()
    expect(identityPicker?.attributes('data-selected-path')).toBe('~/.ssh')

    await identityPicker!.get('[data-codex-identity-picker-select]').trigger('click')
    expect(wrapper.get('[data-codex-remote-identity]').element).toHaveProperty(
      'value',
      '/home/test/.ssh/id_ed25519',
    )
    await wrapper.get('[data-codex-remote-path]').setValue('/srv/app')
    await wrapper.get('[data-codex-save-remote]').trigger('click')

    expect(apiPostMock).toHaveBeenNthCalledWith(1, '/api/codex/remote-connections', {
      display_name: 'Build host',
      ssh_host: 'host',
      ssh_username: 'user',
      ssh_port: 2222,
      ssh_alias: '',
      identity_file: '/home/test/.ssh/id_ed25519',
      remote_path: '/srv/app',
      auto_connect: false,
    })
    expect(wrapper.emitted('remoteConnectionChanged')).toHaveLength(1)

    await wrapper.get('[data-codex-test-remote]').trigger('click')
    expect(apiPostMock).toHaveBeenNthCalledWith(
      2,
      '/api/codex/remote-connections/remote-1/test',
      {},
    )

    expect(wrapper.get('[data-codex-remote-runtime-status]').text()).toContain(
      'Connected',
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

    await wrapper.get('[data-codex-login-api-key-remote]').trigger('click')
    await wrapper.get('[data-codex-remote-api-key]').setValue('sk-test')
    await wrapper.get('[data-codex-remote-api-key-submit]').trigger('click')
    expect(apiPostMock).toHaveBeenNthCalledWith(
      5,
      '/api/codex/remote-connections/remote-1/login-api-key',
      { apiKey: 'sk-test' },
    )

    await wrapper.get('[data-codex-start-remote-thread]').trigger('click')
    expect(wrapper.emitted('startThread')).toContainEqual([
      '/srv/app',
      'ssh:remote-1',
    ])
    expect(apiPostMock).toHaveBeenCalledTimes(5)
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
        remote_path: '~',
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
            remote_path: '~',
            auto_connect: false,
          },
        ],
      },
    })

    await wrapper.get('[data-codex-edit-remote]').trigger('click')
    const modeButtons = wrapper
      .get('[data-codex-remote-connection-mode]')
      .findAll('button')
    expect(modeButtons[1]?.attributes('aria-pressed')).toBe('true')
    expect(wrapper.find('[data-codex-remote-host]').exists()).toBe(false)
    await wrapper.get('[data-codex-remote-display-name]').setValue('Edited')
    await wrapper.get('[data-codex-save-remote]').trigger('click')

    expect(apiPutMock).toHaveBeenCalledWith(
      '/api/codex/remote-connections/remote-1',
      {
        display_name: 'Edited',
        ssh_host: '',
        ssh_username: '',
        ssh_port: null,
        ssh_alias: 'prod',
        identity_file: '',
        remote_path: '~',
        auto_connect: false,
      },
    )
    expect(wrapper.emitted('remoteConnectionChanged')).toHaveLength(1)
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
            remote_path: '/srv/app',
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
    expect(projectIcons.map((item) => item.attributes('data-source'))).toEqual([
      'remote',
      'local',
    ])
    expect(projectIcons[0]?.find('svg').exists()).toBe(true)
    expect(wrapper.get('[data-codex-project-alias]').text()).toBe('build-box')
    expect(wrapper.get('[data-codex-project-status]').attributes()).toMatchObject({
      'aria-label': 'build-box: Connected - Codex ready',
      'data-status': 'connected',
    })
    expect(wrapper.get('[data-codex-project-remote-meta]').classes()).toEqual(
      expect.arrayContaining([
        'group-hover/project:hidden',
        'group-focus-within/project:hidden',
      ]),
    )
    expect(wrapper.get('[data-codex-project-row]').classes()).toContain('relative')
    expect(wrapper.get('[data-codex-project-action-spacer]').classes()).toEqual(
      expect.arrayContaining([
        'hidden',
        'w-7',
        'group-hover/project:block',
      ]),
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
    await wrapper
      .get('[data-codex-thread-menu-item="Fork"]')
      .trigger('click')
    await wrapper
      .get('[data-codex-thread-menu-item="Copy ID"]')
      .trigger('click')
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
    await wrapper
      .get('[data-codex-thread-menu-item="Copy ID"]')
      .trigger('click')

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
    expect(wrapper.get('[data-codex-thread-menu-item="Copy ID"]').attributes('disabled')).toBeUndefined()
  })

  it('renames threads inline from the thread row', async () => {
    const wrapper = mountSidebar()

    await wrapper.get('[data-codex-thread-name]').trigger('dblclick')
    await wrapper.get('[data-codex-thread-rename-input]').setValue('Renamed thread')
    await wrapper.get('[data-codex-thread-rename-input]').trigger('keydown.enter')

    expect(wrapper.emitted('renameThread')).toEqual([
      ['thread-alpha-new', 'Renamed thread'],
    ])
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
