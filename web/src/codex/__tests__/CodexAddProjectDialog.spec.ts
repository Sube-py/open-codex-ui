import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import { apiPost } from '../../lib/api'
import CodexAddProjectDialog from '../components/CodexAddProjectDialog.vue'
import type { CodexWorkspaceResponse } from '../types'

vi.mock('../../lib/api', () => ({
  apiPost: vi.fn(),
}))

const apiPostMock = vi.mocked(apiPost)

const workspace: CodexWorkspaceResponse = {
  projects: [],
  recent_threads: [],
  remote_connections: [
    {
      id: 'build',
      display_name: 'Build host',
      ssh_host: 'build.example.com',
      ssh_username: 'builder',
      ssh_alias: '',
      identity_file: '',
      auto_connect: false,
    },
  ],
}

describe('CodexAddProjectDialog', () => {
  it('adds a project selected from a remote host', async () => {
    apiPostMock.mockReset()
    apiPostMock.mockResolvedValueOnce({ id: 'remote-project' })

    const wrapper = mount(CodexAddProjectDialog, {
      props: {
        visible: true,
        workspace,
      },
      global: {
        stubs: {
          Button: {
            props: ['label', 'disabled'],
            emits: ['click'],
            template:
              '<button v-bind="$attrs" :disabled="disabled" @click="$emit(\'click\')">{{ label }}</button>',
          },
          Dialog: {
            props: ['visible'],
            emits: ['update:visible'],
            template: '<section v-if="visible"><slot /><slot name="footer" /></section>',
          },
          Message: {
            template: '<div><slot /></div>',
          },
          SelectButton: {
            props: ['modelValue', 'options'],
            emits: ['update:modelValue'],
            template:
              '<div><button v-for="option in options" :key="option.value" :data-project-kind-option="option.value" @click="$emit(\'update:modelValue\', option.value)">{{ option.label }}</button></div>',
          },
          Select: {
            props: ['modelValue', 'options'],
            emits: ['update:modelValue'],
            template:
              '<select v-bind="$attrs" :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value)"><option value=""></option><option v-for="option in options" :key="option.value" :value="option.value">{{ option.label }}</option></select>',
          },
          CodexHostPathPicker: {
            props: ['visible', 'hostId', 'selectedPath'],
            emits: ['update:visible', 'select'],
            template:
              '<div v-if="visible" data-remote-picker :data-host-id="hostId" :data-selected-path="selectedPath"><button data-select-remote-path @click="$emit(\'select\', \'/srv/repo\')">Select</button></div>',
          },
        },
      },
    })

    await wrapper.get('[data-project-kind-option="remote"]').trigger('click')
    await wrapper.get('[data-codex-project-connection]').setValue('build')
    await wrapper.get('[data-codex-project-browse]').trigger('click')

    expect(wrapper.get('[data-remote-picker]').attributes('data-host-id')).toBe('ssh:build')
    expect(wrapper.get('[data-remote-picker]').attributes('data-selected-path')).toBe('')

    await wrapper.get('[data-select-remote-path]').trigger('click')
    await wrapper.get('[data-codex-project-save]').trigger('click')

    expect(apiPostMock).toHaveBeenCalledWith('/api/codex/projects', {
      name: '',
      kind: 'remote',
      host_id: 'ssh:build',
      project_path: '/srv/repo',
    })
    expect(wrapper.emitted('projectChanged')).toEqual([[]])
  })
})
