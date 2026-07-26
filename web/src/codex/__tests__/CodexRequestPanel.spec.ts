import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import CodexRequestPanel from '../components/CodexRequestPanel.vue'
import type { CodexPendingRequest } from '../types'

describe('CodexRequestPanel', () => {
  it('walks multiple structured questions one at a time with back navigation', async () => {
    const request: CodexPendingRequest = {
      id: 'request-many',
      method: 'item/tool/requestUserInput',
      params: {
        turnId: 'turn-many',
        questions: [
          {
            id: 'mode',
            header: 'Mode',
            question: 'How should Codex proceed?',
            options: [
              { label: 'Plan', description: 'Ask before editing.' },
              { label: 'Build', description: 'Make the change.' },
            ],
          },
          {
            id: 'scope',
            header: 'Scope',
            question: 'How broad should the change be?',
            options: [
              { label: 'Focused', description: 'Touch the narrowest surface.' },
              { label: 'Complete', description: 'Cover adjacent cleanup too.' },
            ],
          },
        ],
      },
    }
    const wrapper = mount(CodexRequestPanel, { props: { request } })

    expect(wrapper.text()).toContain('Question 1 of 2')
    expect(wrapper.text()).toContain('How should Codex proceed?')
    expect(wrapper.text()).not.toContain('How broad should the change be?')

    await wrapper
      .findAll('button')
      .find((button) => button.text().includes('Plan'))!
      .trigger('click')

    expect(wrapper.text()).toContain('Question 2 of 2')
    expect(wrapper.text()).toContain('How broad should the change be?')
    expect(wrapper.text()).not.toContain('How should Codex proceed?')

    await wrapper
      .findAll('button')
      .find((button) => button.text().includes('Back'))!
      .trigger('click')
    await wrapper
      .findAll('button')
      .find((button) => button.text().includes('Build'))!
      .trigger('click')
    await wrapper
      .findAll('button')
      .find((button) => button.text().includes('Focused'))!
      .trigger('click')
    await wrapper
      .findAll('button')
      .find((button) => button.text().includes('Submit'))!
      .trigger('click')

    expect(wrapper.emitted('submitResponse')).toEqual([
      [
        'request-many',
        {
          answers: {
            mode: {
              answers: ['Build'],
            },
            scope: {
              answers: ['Focused'],
            },
          },
        },
      ],
    ])
  })

  it('keeps request actions outside the scrollable body on mobile', () => {
    const request: CodexPendingRequest = {
      id: 'request-mobile',
      method: 'item/tool/requestUserInput',
      params: {
        turnId: 'turn-mobile',
        questions: [
          {
            id: 'scope',
            header: 'Scope',
            question: 'How broad should the change be?',
            options: [
              { label: 'Focused', description: 'Touch the narrowest surface.' },
              { label: 'Complete', description: 'Cover adjacent cleanup too.' },
            ],
          },
        ],
      },
    }
    const wrapper = mount(CodexRequestPanel, { props: { request } })

    expect(wrapper.get('section').classes()).toEqual(
      expect.arrayContaining([
        'flex',
        'flex-col',
        'max-sm:max-h-[min(56dvh,26rem)]',
        'max-sm:overflow-hidden',
      ]),
    )
    expect(wrapper.get('[data-codex-request-body]').classes()).toEqual(
      expect.arrayContaining(['min-h-0', 'flex-1', 'overflow-y-auto']),
    )
    expect(wrapper.get('[data-codex-request-actions]').classes()).toContain('shrink-0')
    expect(wrapper.get('[data-codex-request-actions]').text()).toContain('Submit')
  })

  it('submits structured open-codex-bridge question answers', async () => {
    const request: CodexPendingRequest = {
      id: 'request-1',
      method: 'item/tool/requestUserInput',
      params: {
        turnId: 'turn-1',
        questions: [
          {
            id: 'mode',
            header: 'Mode',
            question: 'How should Codex proceed?',
            options: [
              { label: 'Plan', description: 'Ask before editing.' },
              { label: 'Build', description: 'Make the change.' },
            ],
          },
        ],
      },
    }
    const wrapper = mount(CodexRequestPanel, { props: { request } })

    await wrapper
      .findAll('button')
      .find((button) => button.text().includes('Plan'))!
      .trigger('click')
    await wrapper
      .findAll('button')
      .find((button) => button.text().includes('Submit'))!
      .trigger('click')

    expect(wrapper.emitted('submitResponse')).toEqual([
      [
        'request-1',
        {
          answers: {
            mode: {
              answers: ['Plan'],
            },
          },
        },
      ],
    ])
  })

  it('keeps a JSON fallback for unsupported request shapes', async () => {
    const request: CodexPendingRequest = {
      id: 'request-json',
      method: 'item/tool/requestUserInput',
      params: {
        turnId: 'turn-json',
      },
    }
    const wrapper = mount(CodexRequestPanel, { props: { request } })

    await wrapper
      .find('textarea')
      .setValue(JSON.stringify({ answers: { custom: { answers: ['ok'] } } }))
    await wrapper
      .findAll('button')
      .find((button) => button.text().includes('Submit'))!
      .trigger('click')

    expect(wrapper.emitted('submitResponse')).toEqual([
      [
        'request-json',
        {
          answers: {
            custom: {
              answers: ['ok'],
            },
          },
        },
      ],
    ])
  })

  it('submits plan implementation requests with optional feedback', async () => {
    const request: CodexPendingRequest = {
      id: 'implement-plan:turn-1',
      method: 'item/plan/requestImplementation',
      params: {
        turnId: 'turn-1',
        planContent: '1. Update composer\n2. Add tests',
      },
    }
    const wrapper = mount(CodexRequestPanel, { props: { request } })

    expect(wrapper.text()).toContain('Plan ready')
    expect(wrapper.text()).toContain('Implement this plan?')
    expect(wrapper.text()).toContain('1. Update composer')

    await wrapper.find('textarea').setValue('Please keep the patch focused.')
    await wrapper
      .findAll('button')
      .find((button) => button.text().includes('Implement plan'))!
      .trigger('click')

    expect(wrapper.emitted('submitResponse')).toEqual([
      [
        'implement-plan:turn-1',
        {
          decision: 'accept',
          planContent: '1. Update composer\n2. Add tests',
          followupMessage: 'Please keep the patch focused.',
        },
      ],
    ])
  })
})
