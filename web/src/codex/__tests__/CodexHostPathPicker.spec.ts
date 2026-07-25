import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiGet } from '../../lib/api'
import CodexHostPathPicker from '../components/CodexHostPathPicker.vue'
import type { CodexFilesystemResponse } from '../types'

vi.mock('../../lib/api', () => ({
  apiGet: vi.fn(),
}))

const apiGetMock = vi.mocked(apiGet)

function filesystemResponse(
  path: string,
  entries: CodexFilesystemResponse['entries'] = [],
): CodexFilesystemResponse {
  return {
    path,
    parent_path: path === '/' ? null : '/',
    roots: [
      {
        name: '/',
        path: '/',
        kind: 'directory',
        extension: '',
        readable: true,
      },
    ],
    entries,
  }
}

function mountPicker(props: Partial<InstanceType<typeof CodexHostPathPicker>['$props']> = {}) {
  const wrapper = mount(CodexHostPathPicker, {
    props: {
      visible: true,
      selectedPath: '',
      disabled: false,
      ...props,
      'onUpdate:visible': (value: boolean) => wrapper.setProps({ visible: value }),
    },
    global: {
      stubs: {
        Breadcrumb: {
          props: ['home', 'model'],
          template:
            '<nav data-codex-breadcrumb-stub><button v-for="item in [home, ...model]" :key="item.path" data-codex-breadcrumb-item @click="item.command">{{ item.label }}</button></nav>',
        },
        Button: {
          props: ['label', 'disabled'],
          emits: ['click'],
          template:
            '<button v-bind="$attrs" :disabled="disabled" @click="$emit(\'click\', $event)"><span>{{ label }}</span><slot /></button>',
        },
        Drawer: {
          props: ['visible'],
          emits: ['update:visible'],
          template: '<section v-if="visible" data-codex-drawer-stub><slot /></section>',
        },
        Message: {
          template: '<div data-codex-message-stub><slot /></div>',
        },
        ProgressSpinner: {
          template: '<div data-codex-spinner-stub />',
        },
        ScrollPanel: {
          template: '<div data-codex-scroll-panel-stub><slot /></div>',
        },
      },
    },
  })
  return wrapper
}

describe('CodexHostPathPicker', () => {
  beforeEach(() => {
    apiGetMock.mockReset()
    vi.stubGlobal('matchMedia', () => ({
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      matches: false,
    }))
  })

  it('loads host folders and selects only the current folder', async () => {
    apiGetMock.mockResolvedValueOnce(
      filesystemResponse('/tmp', [
        {
          name: 'alpha',
          path: '/tmp/alpha',
          kind: 'directory',
          extension: '',
          readable: true,
        },
        {
          name: 'main.py',
          path: '/tmp/main.py',
          kind: 'file',
          extension: '.py',
          readable: true,
        },
      ]),
    )

    const wrapper = mountPicker({ selectedPath: '/tmp' })
    await flushPromises()

    expect(apiGetMock).toHaveBeenCalledWith('/api/codex/filesystem?path=%2Ftmp')
    expect(wrapper.get('[data-codex-host-path-current]').text()).toContain('/tmp')
    expect(wrapper.get('[data-codex-host-path-folder]').text()).toContain('alpha')
    expect(wrapper.get('[data-codex-host-path-file]').text()).toContain('main.py')

    await wrapper.get('[data-codex-host-path-confirm]').trigger('click')

    expect(wrapper.emitted('select')).toEqual([['/tmp']])
    const visibleUpdates = wrapper.emitted('update:visible') ?? []
    expect(visibleUpdates[visibleUpdates.length - 1]).toEqual([false])
  })

  it('navigates into folders and through breadcrumb items', async () => {
    apiGetMock
      .mockResolvedValueOnce(
        filesystemResponse('/tmp', [
          {
            name: 'alpha',
            path: '/tmp/alpha',
            kind: 'directory',
            extension: '',
            readable: true,
          },
        ]),
      )
      .mockResolvedValueOnce(filesystemResponse('/tmp/alpha'))
      .mockResolvedValueOnce(filesystemResponse('/tmp'))

    const wrapper = mountPicker({ selectedPath: '/tmp' })
    await flushPromises()

    await wrapper.get('[data-codex-host-path-folder]').trigger('click')
    await flushPromises()

    expect(apiGetMock).toHaveBeenLastCalledWith('/api/codex/filesystem?path=%2Ftmp%2Falpha')
    expect(wrapper.get('[data-codex-host-path-current]').text()).toContain('/tmp/alpha')

    const breadcrumbItems = wrapper.findAll('[data-codex-breadcrumb-item]')
    await breadcrumbItems[1]!.trigger('click')
    await flushPromises()

    expect(apiGetMock).toHaveBeenLastCalledWith('/api/codex/filesystem?path=%2Ftmp')
  })

  it('selects files when file selection is enabled', async () => {
    apiGetMock.mockResolvedValueOnce(
      filesystemResponse('/tmp', [
        {
          name: 'main.py',
          path: '/tmp/main.py',
          kind: 'file',
          extension: '.py',
          readable: true,
        },
      ]),
    )

    const wrapper = mountPicker({ selectedPath: '/tmp', allowFiles: true })
    await flushPromises()

    await wrapper.get('[data-codex-host-path-file]').trigger('click')

    expect(wrapper.emitted('select')).toEqual([['/tmp/main.py']])
    const visibleUpdates = wrapper.emitted('update:visible') ?? []
    expect(visibleUpdates[visibleUpdates.length - 1]).toEqual([false])
  })

  it('hides folder confirmation when only files may be selected', async () => {
    apiGetMock.mockResolvedValueOnce(filesystemResponse('/home/test/.ssh'))

    const wrapper = mountPicker({
      selectedPath: '~/.ssh',
      allowFiles: true,
      allowCurrentFolder: false,
    })
    await flushPromises()

    expect(apiGetMock).toHaveBeenCalledWith('/api/codex/filesystem?path=~%2F.ssh')
    expect(wrapper.find('[data-codex-host-path-confirm]').exists()).toBe(false)
  })

  it('shows load errors without selecting a path', async () => {
    apiGetMock.mockRejectedValueOnce(new Error('Permission denied: /private'))

    const wrapper = mountPicker({ selectedPath: '/private' })
    await flushPromises()

    expect(wrapper.get('[data-codex-host-path-error]').text()).toContain('Permission denied')
    expect(wrapper.emitted('select')).toBeUndefined()
  })

  it('browses the selected remote host', async () => {
    apiGetMock.mockResolvedValueOnce(filesystemResponse('/srv/app'))

    mountPicker({ selectedPath: '/srv/app', hostId: 'ssh:build' })
    await flushPromises()

    expect(apiGetMock).toHaveBeenCalledWith(
      '/api/codex/filesystem?path=%2Fsrv%2Fapp&host_id=ssh%3Abuild',
    )
  })
})
