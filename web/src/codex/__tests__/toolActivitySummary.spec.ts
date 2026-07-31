import { describe, expect, it } from 'vitest'

import { summarizeToolActivity } from '../lib/toolActivitySummary'

describe('summarizeToolActivity', () => {
  it('builds the official semantic summary order without exposing counts', () => {
    const summary = summarizeToolActivity([
      {
        type: 'commandExecution',
        command: 'rg summary web/src',
        commandActions: [{ type: 'search', query: 'summary', path: 'web/src' }],
      },
      {
        type: 'commandExecution',
        command: 'pnpm test:unit',
        commandActions: [{ type: 'unknown', command: 'pnpm test:unit' }],
      },
      {
        type: 'mcpToolCall',
        server: 'node_repl',
        tool: 'js',
      },
      {
        type: 'mcpToolCall',
        server: 'figma',
        tool: 'get_design_context',
      },
      {
        type: 'fileChange',
        changes: {
          'src/App.vue': { type: 'update' },
          'src/main.ts': { type: 'update' },
        },
      },
      {
        type: 'webSearch',
        action: { type: 'search', queries: ['tool summary UI'] },
      },
      {
        type: 'dynamicToolCall',
        tool: 'generate_diagram',
      },
    ])

    expect(summary).toEqual({
      active: false,
      icon: 'pi-box',
      parts: [
        'Used Figma integration',
        'edited files',
        'read files',
        'ran commands',
        'searched the web',
        'called Generate Diagram',
      ],
      text: 'Used Figma integration, edited files, read files, ran commands, searched the web, and called Generate Diagram',
    })
    expect(summary.text).not.toMatch(/\b2\b/)
  })

  it('shows the latest active operation instead of a completed aggregate', () => {
    const summary = summarizeToolActivity([
      {
        type: 'commandExecution',
        command: 'pnpm test',
        status: 'completed',
      },
      {
        type: 'commandExecution',
        command: 'rg tool-summary web/src',
        commandActions: [{ type: 'search', query: 'tool-summary', path: 'web/src' }],
        status: 'running',
      },
    ])

    expect(summary).toEqual({
      active: true,
      icon: 'pi-search',
      parts: ['Searching for tool-summary'],
      text: 'Searching for tool-summary',
    })
  })

  it('uses an icon available in PrimeIcons for command-only summaries', () => {
    const summary = summarizeToolActivity([
      {
        type: 'commandExecution',
        command: 'pnpm test',
        status: 'completed',
      },
    ])

    expect(summary.icon).toBe('pi-code')
    expect(summary.text).toBe('Ran a command')
  })

  it('separates loaded skills and browser activity from generic commands and tools', () => {
    const summary = summarizeToolActivity([
      {
        type: 'commandExecution',
        command: 'sed -n 1,200p .agents/skills/inspect/SKILL.md',
        commandActions: [
          {
            type: 'read',
            path: '.agents/skills/inspect/SKILL.md',
            name: 'SKILL.md',
          },
        ],
      },
      {
        type: 'mcpToolCall',
        server: 'browser-use',
        tool: 'navigate',
      },
    ])

    expect(summary.icon).toBe('pi-globe')
    expect(summary.text).toBe('Used the browser and loaded a tool')
  })
})
