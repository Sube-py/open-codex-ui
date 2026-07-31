import { mount, type VueWrapper } from '@vue/test-utils'
import PrimeVue from 'primevue/config'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import CodexConversation from '../components/CodexConversation.vue'

import type { CodexConversationState, CodexTurnState } from '../types'

function createState(
  items: Record<string, unknown>[],
  turnOverrides: Partial<CodexTurnState> = {},
): CodexConversationState {
  return {
    id: 'thread-1',
    turns: [
      {
        turnId: 'turn-1',
        status: 'completed',
        items,
        ...turnOverrides,
      },
    ],
  }
}

function mountConversation(
  items: Record<string, unknown>[],
  turnOverrides: Partial<CodexTurnState> = {},
) {
  return mount(CodexConversation, {
    props: {
      state: createState(items, turnOverrides),
    },
    global: {
      plugins: [PrimeVue],
    },
    attachTo: document.body,
  })
}

async function flushScrollWatchers() {
  await nextTick()
  await nextTick()
}

function scrollContainer(wrapper: VueWrapper) {
  return wrapper.get('[data-codex-conversation-body]').element as HTMLElement
}

function setScrollMetrics(
  element: HTMLElement,
  { scrollHeight, clientHeight }: { scrollHeight: number; clientHeight: number },
) {
  Object.defineProperty(element, 'scrollHeight', {
    configurable: true,
    value: scrollHeight,
  })
  Object.defineProperty(element, 'clientHeight', {
    configurable: true,
    value: clientHeight,
  })
}

describe('CodexConversation', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.useRealTimers()
    vi.stubGlobal('navigator', {
      clipboard: {
        writeText: vi.fn().mockResolvedValue(undefined),
      },
    })
  })

  it('uses the shared themed scrollbar for the conversation body', () => {
    const wrapper = mountConversation([])

    expect(wrapper.get('[data-codex-conversation-body]').classes()).toEqual(
      expect.arrayContaining(['codex-scrollbar', 'overflow-y-auto']),
    )
  })

  it('renders conversational agent messages as markdown with copyable code blocks', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', {
      clipboard: {
        writeText,
      },
    })

    const wrapper = mountConversation([
      {
        id: 'agent-1',
        type: 'agentMessage',
        text: '**Bold** and `code`\n\n```ts\nconst value = 1\n```',
      },
    ])

    expect(wrapper.html()).toContain('<strong>Bold</strong>')
    expect(wrapper.html()).toContain('<code>code</code>')
    expect(wrapper.find('[data-copy-markdown-code]').exists()).toBe(true)

    await wrapper.get('[data-copy-markdown-code]').trigger('click')

    expect(writeText).toHaveBeenCalledWith('const value = 1')
    expect(wrapper.get('[data-copy-markdown-code]').attributes('aria-label')).toBe('Copied')
  })

  it('renders markdown image paths through the backend image endpoint', () => {
    const imagePath = '/Users/sube/me/yier/output/playwright/codex-imageview-ui-preview.png'
    const wrapper = mountConversation([
      {
        id: 'agent-1',
        type: 'agentMessage',
        text: `截好了，当前 imageView 展开后的 UI 是这样：\n\n![imageView UI](${imagePath})`,
      },
    ])

    const image = wrapper.get('.markdown-prose img')
    expect(image.attributes('src')).toBe(
      `/api/codex/image?path=${encodeURIComponent(imagePath)}`,
    )
    expect(image.attributes('alt')).toBe('imageView UI')
  })

  it('keeps long user messages constrained to the right-aligned shell', () => {
    const wrapper = mountConversation([
      {
        id: 'user-1',
        type: 'userMessage',
        content: 'x'.repeat(240),
      },
    ])

    const row = wrapper.get('[data-codex-user-message]')
    const shell = wrapper.get('[data-codex-user-message-shell]')
    const bubble = wrapper.get('[data-codex-bubble]')
    const actions = wrapper.get('[data-codex-user-message-actions]')
    const prose = wrapper.get('.markdown-prose')

    expect(row.classes()).toEqual(
      expect.arrayContaining(['flex', 'min-w-0', 'w-full', 'justify-end']),
    )
    expect(shell.classes()).toEqual(
      expect.arrayContaining([
        'flex',
        'min-w-0',
        'w-fit',
        'max-w-[min(40rem,88%)]',
        'flex-col',
        'items-end',
        'max-sm:max-w-[96%]',
      ]),
    )
    expect(bubble.classes()).toEqual(expect.arrayContaining(['min-w-0', 'w-full', 'overflow-hidden']))
    expect(actions.element.parentElement).toBe(shell.element)
    expect(prose.classes()).toContain('[overflow-wrap:anywhere]')
    expect(wrapper.find('section').classes()).toEqual(
      expect.arrayContaining(['min-w-0', 'overflow-x-clip']),
    )
  })

  it('keeps expanded work details mobile-safe', async () => {
    const wrapper = mountConversation([
      {
        id: 'command-1',
        type: 'commandExecution',
        command: 'pnpm test',
        aggregatedOutput: 'ok',
      },
    ])

    await wrapper.get('[data-codex-work-toggle]').trigger('click')
    await wrapper.get('[data-codex-activity-toggle]').trigger('click')
    await wrapper.get('[data-codex-work-row]').trigger('click')

    expect(wrapper.get('[data-codex-work-items]').classes()).toEqual(
      expect.arrayContaining(['min-w-0', 'max-sm:pl-2']),
    )
    expect(wrapper.get('[data-codex-work-detail]').classes()).toEqual(
      expect.arrayContaining(['min-w-0', 'max-h-56', 'overflow-y-auto']),
    )
    expect(wrapper.get('[data-codex-command-output]').classes()).toContain('min-w-0')
  })

  it('keeps command output in the collapsed work section until expanded', async () => {
    const wrapper = mountConversation([
      {
        id: 'command-1',
        type: 'commandExecution',
        command: 'printf "**raw**"',
        aggregatedOutput: '**raw** output',
      },
      {
        id: 'agent-1',
        type: 'agentMessage',
        text: 'Done',
      },
    ])

    expect(wrapper.get('[data-codex-work-toggle]').text()).toContain('Worked')
    expect(wrapper.find('[data-codex-command-output]').exists()).toBe(false)
    expect(wrapper.find('[data-codex-work-items]').exists()).toBe(false)
    expect(wrapper.find('[data-codex-work-section] .markdown-prose').exists()).toBe(false)

    await wrapper.get('[data-codex-work-toggle]').trigger('click')
    expect(wrapper.get('[data-codex-activity-toggle]').text()).toContain('Ran a command')
    await wrapper.get('[data-codex-activity-toggle]').trigger('click')
    expect(wrapper.find('[data-codex-command-output]').exists()).toBe(false)
    await wrapper.get('[data-codex-work-row]').trigger('click')

    const output = wrapper.get('[data-codex-command-output]')
    expect(output.text()).toContain('printf "**raw**"')
    expect(output.text()).toContain('**raw** output')
    expect(wrapper.html()).not.toContain('<strong>raw</strong>')
  })

  it('shows completed turn work duration before the final assistant response', () => {
    const wrapper = mountConversation(
      [
        {
          id: 'command-1',
          type: 'commandExecution',
          command: 'pnpm test',
          aggregatedOutput: 'ok',
        },
        {
          id: 'agent-1',
          type: 'agentMessage',
          text: 'Ready',
        },
      ],
      {
        durationMs: 12_000,
      },
    )

    expect(wrapper.text()).toContain('Worked for 12s')
    expect(wrapper.get('[data-codex-work-toggle]').attributes('aria-expanded')).toBe('false')
    expect(wrapper.get('[data-codex-assistant-message]').text()).toContain('Ready')
  })

  it('uses the first work item start time for completed work duration before falling back to turn duration', () => {
    const wrapper = mountConversation(
      [
        {
          id: 'command-1',
          type: 'commandExecution',
          command: 'pnpm test',
          aggregatedOutput: 'ok',
        },
        {
          id: 'agent-1',
          type: 'agentMessage',
          text: 'Ready',
        },
      ],
      {
        turnStartedAtMs: 1_756_800_000_000,
        firstTurnWorkItemStartedAtMs: 1_756_800_016_000,
        finalAssistantStartedAtMs: 1_756_800_069_000,
        durationMs: 90_000,
      },
    )

    expect(wrapper.text()).toContain('Worked for 53s')
    expect(wrapper.text()).not.toContain('Worked for 1m 9s')
    expect(wrapper.text()).not.toContain('Worked for 1m 30s')
  })

  it('preserves turn item order and folds non-final agent messages into work', async () => {
    const wrapper = mountConversation(
      [
        {
          id: 'user-1',
          type: 'userMessage',
          content: 'Please inspect this',
        },
        {
          id: 'agent-commentary-1',
          type: 'agentMessage',
          phase: 'commentary',
          text: 'I will inspect the relevant files first.',
        },
        {
          id: 'command-1',
          type: 'commandExecution',
          command: 'rg "goal" web/src/codex',
          aggregatedOutput: 'web/src/codex/components/CodexConversation.vue',
        },
        {
          id: 'agent-final-1',
          type: 'agentMessage',
          phase: 'final_answer',
          text: 'Done.',
        },
      ],
      {
        durationMs: 2_000,
      },
    )

    const visibleBlocks = wrapper.findAll(
      '[data-codex-user-message], [data-codex-work-section], [data-codex-assistant-message]',
    )
    expect(visibleBlocks.map((block) => block.attributes())).toMatchObject([
      { 'data-codex-user-message': '' },
      { 'data-codex-work-section': '' },
      { 'data-codex-assistant-message': '' },
    ])

    const assistant = wrapper.get('[data-codex-assistant-message]')
    expect(assistant.text()).toContain('Done.')
    expect(assistant.text()).not.toContain('I will inspect the relevant files first.')

    await wrapper.get('[data-codex-work-toggle]').trigger('click')

    expect(wrapper.get('[data-codex-work-message]').text()).toContain(
      'I will inspect the relevant files first.',
    )
    expect(wrapper.get('[data-codex-work-message]').text()).not.toContain('Message')
    expect(wrapper.get('[data-codex-activity-toggle]').text()).toContain('Read files')
    expect(wrapper.find('[data-codex-command-output]').exists()).toBe(false)
  })

  it('folds image view items into work with preview and download actions', async () => {
    const imagePath = '/Users/sube/me/yier/output/playwright/codex-mobile.png'
    const wrapper = mountConversation(
      [
        {
          id: 'user-1',
          type: 'userMessage',
          content: 'Show the screenshot',
        },
        {
          id: 'call-image-1',
          type: 'imageView',
          path: imagePath,
        },
        {
          id: 'agent-final-1',
          type: 'agentMessage',
          phase: 'final_answer',
          text: 'Looks good.',
        },
      ],
      {
        durationMs: 1_000,
      },
    )

    const visibleBlocks = wrapper.findAll(
      '[data-codex-user-message], [data-codex-work-section], [data-codex-assistant-message], [data-codex-unknown-item]',
    )
    expect(visibleBlocks.map((block) => block.attributes())).toMatchObject([
      { 'data-codex-user-message': '' },
      { 'data-codex-work-section': '' },
      { 'data-codex-assistant-message': '' },
    ])
    expect(wrapper.find('[data-codex-unknown-item]').exists()).toBe(false)
    expect(wrapper.find('[data-codex-image-view]').exists()).toBe(false)

    await wrapper.get('[data-codex-work-toggle]').trigger('click')

    const preview = wrapper.get('[data-codex-image-preview]')
    expect(wrapper.get('[data-codex-image-view]').text()).toBe('')
    expect(preview.attributes('src')).toBe(
      `/api/codex/image?path=${encodeURIComponent(imagePath)}`,
    )
    expect(wrapper.find('[data-codex-image-download]').exists()).toBe(false)
    expect(wrapper.find('[data-codex-image-open]').exists()).toBe(false)
    expect(wrapper.find('[data-codex-raw]').exists()).toBe(false)

    await wrapper.get('[data-codex-image-preview-link]').trigger('click')
    await nextTick()

    const gallery = document.body.querySelector('[data-codex-image-gallery]')
    const galleryDownload = document.body.querySelector('[data-codex-image-gallery-download]')
    const galleryImage = document.body.querySelector('[data-codex-image-gallery-image]')

    expect(gallery).not.toBeNull()
    expect(galleryImage?.getAttribute('src')).toBe(
      `/api/codex/image?path=${encodeURIComponent(imagePath)}`,
    )
    expect(galleryDownload?.getAttribute('href')).toBe(
      `/api/codex/image?path=${encodeURIComponent(imagePath)}&download=true`,
    )
    expect(galleryDownload?.getAttribute('download')).toBe('codex-mobile.png')
  })

  it('does not render explicit commentary as the final assistant response', async () => {
    const wrapper = mountConversation([
      {
        id: 'agent-commentary-1',
        type: 'agentMessage',
        phase: 'commentary',
        text: 'Still working through this.',
      },
    ])

    expect(wrapper.find('[data-codex-assistant-message]').exists()).toBe(false)

    await wrapper.get('[data-codex-work-toggle]').trigger('click')

    expect(wrapper.get('[data-codex-work-message]').text()).toContain('Still working through this.')
  })

  it('keeps work item expansion scoped per turn even when item ids repeat', async () => {
    const wrapper = mount(CodexConversation, {
      props: {
        state: {
          id: 'thread-1',
          turns: [
            {
              turnId: 'turn-1',
              status: 'completed',
              items: [
                {
                  id: 'command-1',
                  type: 'commandExecution',
                  command: 'pnpm first',
                  aggregatedOutput: 'first output',
                },
                { id: 'agent-1', type: 'agentMessage', phase: 'final_answer', text: 'First done' },
              ],
            },
            {
              turnId: 'turn-2',
              status: 'completed',
              items: [
                {
                  id: 'command-1',
                  type: 'commandExecution',
                  command: 'pnpm second',
                  aggregatedOutput: 'second output',
                },
                { id: 'agent-2', type: 'agentMessage', phase: 'final_answer', text: 'Second done' },
              ],
            },
          ],
        },
      },
      global: {
        plugins: [PrimeVue],
      },
      attachTo: document.body,
    })

    const workToggles = wrapper.findAll('[data-codex-work-toggle]')
    await workToggles[0]?.trigger('click')
    await workToggles[1]?.trigger('click')

    const activityToggles = wrapper.findAll('[data-codex-activity-toggle]')
    await activityToggles[0]?.trigger('click')
    const rows = wrapper.findAll('[data-codex-work-row]')
    await rows[0]?.trigger('click')

    expect(wrapper.get('[data-codex-command-output]').text()).toContain('first output')
    expect(wrapper.text()).not.toContain('second output')
  })

  it('keeps in-progress work expanded and shows working elapsed time', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-05-21T00:00:03.000Z'))

    const wrapper = mountConversation(
      [
        {
          id: 'reasoning-1',
          type: 'reasoning',
          status: 'inProgress',
          content: 'Inspecting the code',
        },
      ],
      {
        status: 'in_progress',
        turnStartedAtMs: new Date('2026-05-21T00:00:00.000Z').getTime(),
      },
    )

    expect(wrapper.text()).toContain('Working for 3s')
    expect(wrapper.text()).toContain('Thinking')
    expect(wrapper.find('[data-codex-thinking-shimmer]').exists()).toBe(true)
    expect(wrapper.find('[data-codex-thinking-placeholder]').exists()).toBe(true)
    expect(wrapper.find('[data-codex-thinking-fallback]').exists()).toBe(false)
    const workToggle = wrapper.get('[data-codex-work-toggle]')
    expect(workToggle.text()).not.toContain('Thinking')
    expect(workToggle.attributes('aria-expanded')).toBe('true')
    expect(wrapper.find('[data-codex-work-item]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Inspecting the code')
    expect(wrapper.html().indexOf('data-codex-work-section')).toBeLessThan(
      wrapper.html().indexOf('data-codex-thinking-placeholder'),
    )

    vi.useRealTimers()
  })

  it('shows a thinking placeholder while a turn is running before work items arrive', () => {
    const wrapper = mountConversation([], {
      status: 'in_progress',
      params: {
        input: [{ type: 'text', text: 'Start working' }],
      },
      turnStartedAtMs: new Date('2026-05-21T00:00:00.000Z').getTime(),
    })

    expect(wrapper.text()).toContain('Start working')
    expect(wrapper.text()).toContain('Thinking')
    expect(wrapper.find('[data-codex-thinking-placeholder]').exists()).toBe(true)
    expect(wrapper.find('[data-codex-work-section]').exists()).toBe(false)
  })

  it('updates in-progress worked time from the first work item start time', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-05-21T00:00:03.000Z'))
    const workStartedAtMs = new Date('2026-05-21T00:00:01.000Z').getTime()

    const wrapper = mountConversation(
      [
        {
          id: 'reasoning-1',
          type: 'reasoning',
          status: 'inProgress',
          startedAtMs: workStartedAtMs,
          content: 'Inspecting the code',
        },
      ],
      {
        status: 'inProgress',
        turnStartedAtMs: new Date('2026-05-21T00:00:00.000Z').getTime(),
      },
    )

    expect(wrapper.text()).toContain('Working for 2s')

    vi.advanceTimersByTime(2_000)
    await nextTick()

    expect(wrapper.text()).toContain('Working for 4s')

    vi.useRealTimers()
  })

  it('renders dynamic tool calls as lightweight work rows with detail on demand', async () => {
    const wrapper = mountConversation([
      {
        id: 'tool-1',
        type: 'dynamicToolCall',
        tool: 'generate_diagram',
        status: 'completed',
        aggregatedOutput: '{"ok":true}',
      },
      {
        id: 'agent-1',
        type: 'agentMessage',
        text: 'Done',
      },
    ])

    await wrapper.get('[data-codex-work-toggle]').trigger('click')

    expect(wrapper.get('[data-codex-activity-toggle]').text()).toContain('Called Generate Diagram')
    expect(wrapper.get('[data-codex-activity-icon]').classes()).toContain('pi-wrench')
    expect(wrapper.find('[data-codex-raw]').exists()).toBe(false)

    await wrapper.get('[data-codex-activity-toggle]').trigger('click')
    expect(wrapper.get('[data-codex-work-row]').text()).toContain('Called Generate Diagram')
    expect(wrapper.find('[data-codex-raw]').exists()).toBe(false)
    await wrapper.get('[data-codex-work-row]').trigger('click')

    expect(wrapper.get('[data-codex-raw]').text()).toContain('{"ok":true}')
  })

  it('shimmers running activity summaries while keeping details expandable', async () => {
    const wrapper = mountConversation(
      [
        {
          id: 'command-1',
          type: 'commandExecution',
          command: '/bin/zsh -lc "pnpm build"',
          status: 'running',
          completed: false,
          aggregatedOutput: 'building...',
        },
      ],
      {
        status: 'in_progress',
      },
    )

    const activityToggle = wrapper.get('[data-codex-activity-toggle]')
    expect(activityToggle.text()).toContain('Running pnpm build')
    expect(activityToggle.get('[data-codex-activity-icon]').classes()).toContain('pi-terminal')
    expect(activityToggle.find('[data-codex-thinking-shimmer]').exists()).toBe(true)

    await activityToggle.trigger('click')
    expect(wrapper.get('[data-codex-work-row]').text()).toContain('Running pnpm build')
    await wrapper.get('[data-codex-work-row]').trigger('click')
    expect(wrapper.get('[data-codex-command-output]').text()).toContain('building...')
  })

  it('summarizes adjacent tool activities behind one compact disclosure', async () => {
    const wrapper = mountConversation([
      {
        id: 'command-1',
        type: 'commandExecution',
        command: '/bin/zsh -lc "pnpm test"',
        aggregatedOutput: 'ok',
        durationMs: 1530,
        output: { exitCode: 0 },
      },
      {
        id: 'file-create',
        type: 'fileChange',
        changes: {
          'src/NewFile.ts': { type: 'create', linesAdded: 12 },
        },
      },
      {
        id: 'file-edit',
        type: 'fileChange',
        changes: {
          'src/App.vue': { type: 'update', linesAdded: 2, linesRemoved: 1 },
        },
      },
      {
        id: 'tool-1',
        type: 'mcpToolCall',
        server: 'figma',
        tool: 'get_design_context',
        status: 'completed',
        durationMs: 425,
      },
    ])

    await wrapper.get('[data-codex-work-toggle]').trigger('click')
    const activity = wrapper.get('[data-codex-work-activity]')
    expect(activity.text()).toContain('Used Figma integration')
    expect(activity.text()).toContain('edited files')
    expect(activity.text()).toContain('ran a command')
    expect(activity.text()).not.toMatch(/created a file|called a tool/i)
    expect(wrapper.findAll('[data-codex-work-row]')).toHaveLength(0)

    await wrapper.get('[data-codex-activity-toggle]').trigger('click')

    const rows = wrapper.findAll('[data-codex-work-row]')
    expect(rows).toHaveLength(4)
    expect(rows[0]?.text()).toContain('Ran pnpm test')
    expect(rows[0]?.text()).toContain('pnpm test')
    expect(rows[1]?.text()).toContain('Created')
    expect(rows[1]?.text()).toContain('src/NewFile.ts')
    expect(rows[2]?.text()).toContain('Edited')
    expect(rows[2]?.text()).toContain('src/App.vue')
    expect(rows[3]?.text()).toContain('Called figma / Get Design Context')
  })

  it('summarizes multiple shell commands without exposing a count', async () => {
    const wrapper = mountConversation([
      {
        id: 'command-1',
        type: 'commandExecution',
        command: 'git diff --check',
        aggregatedOutput: '',
      },
      {
        id: 'command-2',
        type: 'commandExecution',
        command: 'pnpm test:unit',
        aggregatedOutput: 'passed',
      },
      {
        id: 'command-3',
        type: 'commandExecution',
        command: 'pnpm build',
        aggregatedOutput: 'built',
      },
      {
        id: 'agent-1',
        type: 'agentMessage',
        phase: 'final_answer',
        text: 'Done.',
      },
    ])

    await wrapper.get('[data-codex-work-toggle]').trigger('click')

    expect(wrapper.get('[data-codex-activity-toggle]').text()).toContain('Ran commands')

    await wrapper.get('[data-codex-activity-toggle]').trigger('click')

    const rows = wrapper.findAll('[data-codex-work-row]')
    expect(rows).toHaveLength(3)
    expect(rows[0]?.text()).toContain('Ran git diff --check')
    expect(rows[1]?.text()).toContain('Ran pnpm test:unit')
    expect(rows[2]?.text()).toContain('Ran pnpm build')
    expect(wrapper.find('[data-codex-command-output]').exists()).toBe(false)
  })

  it('copies command and output from the shell card', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', {
      clipboard: {
        writeText,
      },
    })
    const wrapper = mountConversation([
      {
        id: 'command-1',
        type: 'commandExecution',
        command: 'pnpm build --filter very-long-package-name -- --mode production',
        aggregatedOutput: 'build output',
      },
    ])

    await wrapper.get('[data-codex-work-toggle]').trigger('click')
    await wrapper.get('[data-codex-activity-toggle]').trigger('click')
    await wrapper.get('[data-codex-work-row]').trigger('click')

    expect(wrapper.get('[data-codex-command-header]').text()).toContain('Shell')
    expect(wrapper.get('[data-codex-command-text]').classes()).toContain('line-clamp-2')
    expect(wrapper.get('[data-codex-command-footer]').text()).toContain('Exit code unknown')
    expect(wrapper.find('[data-codex-copy-shell]').exists()).toBe(false)
    expect(wrapper.find('[data-codex-command-cwd]').exists()).toBe(false)

    await wrapper.get('[data-codex-copy-command]').trigger('click')
    await wrapper.get('[data-codex-copy-output]').trigger('click')

    expect(writeText).toHaveBeenNthCalledWith(
      1,
      'pnpm build --filter very-long-package-name -- --mode production',
    )
    expect(writeText).toHaveBeenNthCalledWith(2, 'build output')
  })

  it('renders final turn work as a report card after the assistant response', () => {
    const wrapper = mountConversation([
      {
        id: 'files-1',
        type: 'fileChange',
        changes: {
          'src/App.vue': { type: 'update', linesAdded: 12, linesRemoved: 3 },
          'src/main.ts': { type: 'update', linesAdded: 2, linesRemoved: 0 },
        },
      },
      {
        id: 'command-1',
        type: 'commandExecution',
        command: 'pnpm test',
        aggregatedOutput: 'ok',
      },
      {
        id: 'agent-1',
        type: 'agentMessage',
        text: 'Done.',
      },
    ])

    const report = wrapper.get('[data-codex-turn-report]')
    expect(report.classes()).toEqual(
      expect.arrayContaining([
        'group/turn-diff-header',
        'flex',
        'max-w-full',
        'flex-col',
        'overflow-hidden',
        'rounded-lg',
        '[--thread-resource-card-row-padding-x:0.75rem]',
        '[--turn-diff-row-padding-y:0.25rem]',
      ]),
    )
    expect(report.text()).toContain('Turn report')
    expect(report.text()).toContain('2 files changed')
    expect(wrapper.findAll('[data-codex-turn-report-files]')).toHaveLength(2)
    expect(wrapper.findAll('[data-codex-turn-report-files]')[0]?.text()).toContain('src/App.vue')
    expect(wrapper.get('[data-codex-turn-report-lines]').text()).toContain('+14 / -3')
    expect(wrapper.get('[data-codex-turn-report-commands]').text()).toContain('1 command')
  })

  it('renders turn report files one per row from unified diff stats', () => {
    const wrapper = mountConversation([
      {
        id: 'files-1',
        type: 'fileChange',
        changes: [
          {
            path: 'web/src/codex/__tests__/CodexConversation.spec.ts',
            kind: 'add',
            diff: '+++ b/web/src/codex/__tests__/CodexConversation.spec.ts\n+one\n+two\n',
          },
          {
            path: 'web/src/codex/components/CodexConversation.vue',
            kind: 'modify',
            diff: '--- a/web/src/codex/components/CodexConversation.vue\n+++ b/web/src/codex/components/CodexConversation.vue\n-old\n+new\n',
          },
        ],
      },
      {
        id: 'agent-1',
        type: 'agentMessage',
        text: 'Done.',
      },
    ])

    const rows = wrapper.findAll('[data-codex-turn-report-files]')
    expect(rows).toHaveLength(2)
    expect(rows[0]?.text()).toContain('web/src/codex/__tests__/CodexConversation.spec.ts')
    expect(rows[0]?.text()).toContain('+2')
    expect(rows[1]?.text()).toContain('web/src/codex/components/CodexConversation.vue')
    expect(rows[1]?.text()).toContain('+1')
    expect(rows[1]?.text()).toContain('-1')
  })

  it('renders web search work without falling back to raw json', async () => {
    const wrapper = mountConversation([
      {
        id: 'search-1',
        type: 'webSearch',
        status: 'completed',
        action: { type: 'search', queries: ['codex app goal mode'] },
      },
      {
        id: 'agent-1',
        type: 'agentMessage',
        text: 'Found it.',
      },
    ])

    await wrapper.get('[data-codex-work-toggle]').trigger('click')

    expect(wrapper.get('[data-codex-activity-toggle]').text()).toContain('Searched the web')
    expect(wrapper.find('[data-codex-raw]').exists()).toBe(false)

    await wrapper.get('[data-codex-activity-toggle]').trigger('click')

    expect(wrapper.get('[data-codex-work-item]').text()).toContain('Searched the web')
    expect(wrapper.get('[data-codex-work-item]').text()).toContain('codex app goal mode')
    expect(wrapper.find('[data-codex-unknown-item]').exists()).toBe(false)
  })

  it('omits todo-list items from the conversation work stream', async () => {
    const wrapper = mountConversation([
      {
        id: 'todo-1',
        type: 'todo-list',
        plan: [
          { step: 'Read the official renderer', status: 'completed' },
          { step: 'Align the local UI', status: 'in_progress' },
        ],
      },
      {
        id: 'agent-1',
        type: 'agentMessage',
        phase: 'final_answer',
        text: 'Done.',
      },
    ])

    await wrapper.get('[data-codex-work-toggle]').trigger('click')

    expect(wrapper.find('[data-codex-todo-list]').exists()).toBe(false)
    expect(wrapper.find('[data-codex-raw]').exists()).toBe(false)
  })

  it('renders context compaction as a divider', async () => {
    const wrapper = mountConversation([
      {
        id: 'compact-1',
        type: 'contextCompaction',
        completed: true,
        source: 'automatic',
      },
      {
        id: 'agent-1',
        type: 'agentMessage',
        phase: 'final_answer',
        text: 'Resumed.',
      },
    ])

    await wrapper.get('[data-codex-work-toggle]').trigger('click')

    const divider = wrapper.get('[data-codex-context-compaction]')
    expect(divider.text()).toContain('Context automatically compacted')
    expect(wrapper.find('[data-codex-work-item]').exists()).toBe(false)
  })

  it('renders slash-command goal user messages and goal hover metadata', () => {
    const wrapper = mount(CodexConversation, {
      props: {
        state: {
          id: 'thread-1',
          completedThreadGoal: {
            threadId: 'thread-1',
            objective: 'Ship it',
            status: 'complete',
            timeUsedSeconds: 522,
            updatedAt: new Date('2026-05-21T23:05:00Z').getTime(),
          },
          turns: [
            {
              turnId: 'turn-1',
              status: 'completed',
              turnStartedAtMs: new Date('2026-05-21T23:00:00Z').getTime(),
              items: [
                {
                  id: 'user-1',
                  type: 'userMessage',
                  content: [
                    { type: 'text', text: '/goal Ship it' },
                    { type: 'image', url: 'data:image/png;base64,abc' },
                  ],
                },
                { id: 'agent-1', type: 'agentMessage', text: 'Done.' },
              ],
            },
          ],
        },
      },
      global: {
        plugins: [PrimeVue],
      },
      attachTo: document.body,
    })

    expect(wrapper.get('[data-codex-message-image]').attributes('src')).toBe(
      'data:image/png;base64,abc',
    )
    expect(wrapper.get('.markdown-prose').text()).toContain('Ship it')
    expect(wrapper.get('.markdown-prose').text()).not.toContain('/goal')
    expect(wrapper.get('[data-codex-sent-as-goal]').text()).toContain('sent as goal')
    expect(wrapper.get('[data-codex-goal-achieved]').text()).toContain('Goal achieved in 8m 42s')
    expect(wrapper.find('[data-codex-fork-message]').exists()).toBe(true)
  })

  it('renders user image attachment paths through the backend image endpoint', () => {
    const imagePath = '/Users/sube/me/yier/output/playwright/local-preview.png'
    const wrapper = mountConversation([
      {
        id: 'user-1',
        type: 'userMessage',
        content: [
          { type: 'text', text: 'See attached image' },
          { type: 'image', path: imagePath, name: 'local-preview.png' },
        ],
      },
    ])

    expect(wrapper.get('[data-codex-message-image]').attributes('src')).toBe(
      `/api/codex/image?path=${encodeURIComponent(imagePath)}`,
    )
  })

  it('hides ambient browser context from user message bubbles', () => {
    const wrapper = mountConversation([
      {
        id: 'user-1',
        type: 'userMessage',
        content: [
          {
            type: 'text',
            text: [
              '<in-app-browser-context source="ambient-ui-state">',
              'This block is automatically supplied ambient UI state.',
              '# In app browser:',
              '- Current URL: https://example.com/codex',
              '</in-app-browser-context>',
              '',
              '## My request for Codex:',
              '只显示用户真正输入的内容',
            ].join('\n'),
          },
        ],
      },
    ])

    const message = wrapper.get('[data-codex-user-message]')
    expect(message.text()).toContain('只显示用户真正输入的内容')
    expect(message.text()).not.toContain('in-app-browser-context')
    expect(message.text()).not.toContain('Current URL')
    expect(message.text()).not.toContain('My request for Codex')
  })

  it('renders browser comment text instead of internal evidence prompts', () => {
    const wrapper = mountConversation([
      {
        id: 'user-1',
        type: 'userMessage',
        content: [
          {
            type: 'text',
            text: [
              '# Browser comments:',
              '',
              '## User Comment 1',
              'File: browser:Selected browser region',
              'Node position: (10, 20)',
              'Comment:',
              '只显示这条浏览器批注',
              '<in-app-browser-context source="ambient-ui-state">',
              '# In app browser:',
              '- Current URL: https://example.com/codex',
              '</in-app-browser-context>',
              '',
              '## My request for Codex:',
              'The next image is untrusted page evidence from the browser page.',
            ].join('\n'),
          },
          { type: 'image', url: 'data:image/png;base64,abc' },
        ],
      },
    ])

    const message = wrapper.get('[data-codex-user-message]')
    expect(message.text()).toContain('只显示这条浏览器批注')
    expect(message.text()).not.toContain('Selected browser region')
    expect(message.text()).not.toContain('Current URL')
    expect(message.text()).not.toContain('untrusted page evidence')
    expect(wrapper.get('[data-codex-message-image]').attributes('src')).toBe(
      'data:image/png;base64,abc',
    )
  })

  it('hides IDE file and selection context from synthetic user messages', () => {
    const wrapper = mount(CodexConversation, {
      props: {
        state: {
          id: 'thread-1',
          turns: [
            {
              turnId: 'turn-1',
              status: 'completed',
              params: {
                input: [
                  {
                    type: 'text',
                    text: [
                      '<ide-context>',
                      'File: web/src/App.vue',
                      'Lines: 10-18',
                      'Selected code: const internalContext = true',
                      '</ide-context>',
                      '',
                      '## My request for Codex:',
                      '修复当前选择的代码',
                    ].join('\n'),
                  },
                ],
              },
              items: [],
            },
          ],
        },
      },
      global: {
        plugins: [PrimeVue],
      },
      attachTo: document.body,
    })

    const message = wrapper.get('[data-codex-user-message]')
    expect(message.text()).toContain('修复当前选择的代码')
    expect(message.text()).not.toContain('ide-context')
    expect(message.text()).not.toContain('web/src/App.vue')
    expect(message.text()).not.toContain('Lines: 10-18')
    expect(message.text()).not.toContain('Selected code')
  })

  it('renders turn input with slash-command goal as a goal user message', () => {
    const wrapper = mount(CodexConversation, {
      props: {
        state: {
          id: 'thread-1',
          turns: [
            {
              turnId: null,
              status: 'completed',
              turnStartedAtMs: 1_756_800_000_000,
              params: {
                input: [
                  {
                    type: 'text',
                    text: '/goal Keep working until tests pass',
                    text_elements: [],
                  },
                ],
              },
              items: [],
            },
          ],
        },
      },
      global: {
        plugins: [PrimeVue],
      },
      attachTo: document.body,
    })

    expect(wrapper.get('.markdown-prose').text()).toBe('Keep working until tests pass')
    expect(wrapper.get('[data-codex-sent-as-goal]').text()).toContain('sent as goal')
  })

  it('renders review mode items as status lines and hides the synthetic review prompt', () => {
    const wrapper = mountConversation([
      {
        id: 'review-start',
        type: 'enteredReviewMode',
        review: "changes against 'main'",
      },
      {
        id: 'review-prompt',
        type: 'userMessage',
        content: [
          {
            type: 'text',
            text: "Review the code changes against the base branch 'main'.",
          },
        ],
      },
      {
        id: 'agent-1',
        type: 'agentMessage',
        text: 'No actionable issues found.',
      },
      {
        id: 'review-end',
        type: 'exitedReviewMode',
        review: "changes against 'main'",
      },
    ])

    const reviewLines = wrapper.findAll('[data-codex-review-mode]')
    expect(reviewLines).toHaveLength(2)
    expect(reviewLines[0]?.text()).toContain("Code review started: changes against 'main'")
    expect(reviewLines[1]?.text()).toContain('Code review finished')
    expect(wrapper.find('[data-codex-user-message]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Review the code changes against the base branch')
    expect(wrapper.find('[data-codex-unknown-item]').exists()).toBe(false)
    expect(wrapper.get('[data-codex-assistant-message]').text()).toContain(
      'No actionable issues found.',
    )
  })

  it('treats official non-message item types as known work instead of raw unknown json', async () => {
    const wrapper = mountConversation([
      {
        id: 'hook-1',
        type: 'hookPrompt',
        prompt: 'Run the hook',
      },
      {
        id: 'subagent-1',
        type: 'subAgentActivity',
        agentName: 'Explorer',
        summary: 'Inspected app sources',
      },
      {
        id: 'sleep-1',
        type: 'sleep',
        durationMs: 100,
      },
      {
        id: 'image-generation-1',
        type: 'imageGeneration',
        prompt: 'A mobile screenshot',
      },
      {
        id: 'agent-1',
        type: 'agentMessage',
        phase: 'final_answer',
        text: 'Done.',
      },
    ])

    expect(wrapper.find('[data-codex-unknown-item]').exists()).toBe(false)

    await wrapper.get('[data-codex-work-toggle]').trigger('click')
    await wrapper.get('[data-codex-activity-toggle]').trigger('click')

    expect(wrapper.get('[data-codex-work-detail]').text()).toContain('Received hook prompt')
    expect(wrapper.get('[data-codex-work-detail]').text()).toContain('Used subagent')
    expect(wrapper.get('[data-codex-work-detail]').text()).toContain('Slept')
    expect(wrapper.get('[data-codex-work-detail]').text()).toContain('Generated image')
  })

  it('renders steer items as work instead of raw json', async () => {
    const wrapper = mountConversation([
      {
        id: 'user-1',
        type: 'userMessage',
        content: 'Start the task',
      },
      {
        id: 'steer-1',
        type: 'steer',
        input: [{ type: 'text', text: 'Focus on the failing test' }],
      },
      {
        id: 'steered-1',
        type: 'steered',
      },
      {
        id: 'agent-1',
        type: 'agentMessage',
        phase: 'final_answer',
        text: 'Done.',
      },
    ])

    expect(wrapper.find('[data-codex-unknown-item]').exists()).toBe(false)

    await wrapper.get('[data-codex-work-toggle]').trigger('click')
    expect(wrapper.get('[data-codex-work-activity]').text()).toContain('Steered conversation')

    await wrapper.get('[data-codex-activity-toggle]').trigger('click')

    expect(wrapper.get('[data-codex-work-detail]').text()).toContain('Focus on the failing test')
    expect(wrapper.find('[data-codex-raw]').exists()).toBe(false)
  })

  it('renders unknown items as contained raw json', () => {
    const wrapper = mountConversation([
      {
        id: 'unknown-1',
        type: 'newThing',
        payload: { ok: true },
      },
    ])

    const raw = wrapper.get('[data-codex-raw]')

    expect(raw.element.tagName).toBe('PRE')
    expect(raw.classes()).toEqual(expect.arrayContaining(['max-w-full', 'overflow-auto']))
    expect(raw.text()).toContain('"type": "newThing"')
    expect(raw.text()).toContain('"ok": true')
  })

  it('ignores null turn items from persisted conversation state', () => {
    const wrapper = mountConversation([
      null as unknown as Record<string, unknown>,
      {
        id: 'agent-1',
        type: 'agentMessage',
        text: 'Still renders',
      },
    ])

    expect(wrapper.find('[data-codex-unknown-item]').exists()).toBe(false)
    expect(wrapper.get('[data-codex-assistant-message]').text()).toContain('Still renders')
  })

  it('scrolls to the bottom when the conversation opens', async () => {
    const wrapper = mountConversation([
      {
        id: 'agent-1',
        type: 'agentMessage',
        text: 'Earlier output',
      },
    ])
    const element = scrollContainer(wrapper)
    setScrollMetrics(element, { scrollHeight: 1200, clientHeight: 320 })

    await flushScrollWatchers()

    expect(element.scrollTop).toBe(1200)
  })

  it('does not force-scroll new output after the user scrolls away from the bottom', async () => {
    const wrapper = mountConversation([
      {
        id: 'agent-1',
        type: 'agentMessage',
        text: 'Earlier output',
      },
    ])
    const element = scrollContainer(wrapper)
    setScrollMetrics(element, { scrollHeight: 1200, clientHeight: 320 })
    await flushScrollWatchers()

    element.scrollTop = 400
    await wrapper.get('[data-codex-conversation-body]').trigger('scroll')

    setScrollMetrics(element, { scrollHeight: 1400, clientHeight: 320 })
    await wrapper.setProps({
      state: createState([
        {
          id: 'agent-1',
          type: 'agentMessage',
          text: 'Earlier output',
        },
        {
          id: 'agent-2',
          type: 'agentMessage',
          text: 'New output',
        },
      ]),
    })
    await flushScrollWatchers()

    expect(element.scrollTop).toBe(400)
  })

  it('keeps following new output while the user is near the bottom', async () => {
    const wrapper = mountConversation([
      {
        id: 'agent-1',
        type: 'agentMessage',
        text: 'Earlier output',
      },
    ])
    const element = scrollContainer(wrapper)
    setScrollMetrics(element, { scrollHeight: 1200, clientHeight: 320 })
    await flushScrollWatchers()

    element.scrollTop = 840
    await wrapper.get('[data-codex-conversation-body]').trigger('scroll')

    setScrollMetrics(element, { scrollHeight: 1400, clientHeight: 320 })
    await wrapper.setProps({
      state: createState([
        {
          id: 'agent-1',
          type: 'agentMessage',
          text: 'Earlier output',
        },
        {
          id: 'agent-2',
          type: 'agentMessage',
          text: 'New output',
        },
      ]),
    })
    await flushScrollWatchers()

    expect(element.scrollTop).toBe(1400)
  })

  it('virtualizes long conversations at the turn level', async () => {
    const turns = Array.from({ length: 80 }, (_, index): CodexTurnState => ({
        turnId: `turn-${index + 1}`,
        status: 'completed',
        turnStartedAtMs: 1_700_000_000_000 + index,
        items: [
          {
            id: `user-${index + 1}`,
            type: 'userMessage',
            content: `Prompt ${index + 1}`,
          },
          {
            id: `agent-${index + 1}`,
            type: 'agentMessage',
            text: `Answer ${index + 1}`,
          },
        ],
    }))
    const wrapper = mount(CodexConversation, {
      props: {
        state: {
          id: 'thread-long',
          turns,
        },
      },
      global: {
        plugins: [PrimeVue],
      },
      attachTo: document.body,
    })
    const element = scrollContainer(wrapper)
    setScrollMetrics(element, { scrollHeight: 80 * 744, clientHeight: 600 })

    element.scrollTop = 0
    await wrapper.get('[data-codex-conversation-body]').trigger('scroll')
    await flushScrollWatchers()

    const initialTurns = wrapper.findAll('[data-codex-turn]')
    expect(wrapper.get('[data-codex-virtualized-turns]').attributes('data-codex-virtualized-turns')).toBe('true')
    expect(initialTurns.length).toBeGreaterThan(0)
    expect(initialTurns.length).toBeLessThan(80)
    expect(wrapper.find('[data-codex-turn-bottom-spacer]').exists()).toBe(true)

    element.scrollTop = 60 * 744
    await wrapper.get('[data-codex-conversation-body]').trigger('scroll')
    await nextTick()

    const visibleIndexes = wrapper
      .findAll('[data-codex-turn]')
      .map((turn) => Number(turn.attributes('data-codex-turn-index')))

    expect(visibleIndexes.some((index) => index >= 55)).toBe(true)
    expect(visibleIndexes.every((index) => index < 80)).toBe(true)
    expect(wrapper.findAll('[data-codex-turn]').length).toBeLessThan(80)
    expect(wrapper.find('[data-codex-turn-top-spacer]').exists()).toBe(true)
  })

})
