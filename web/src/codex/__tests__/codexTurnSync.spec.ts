import { describe, expect, it, vi } from 'vitest'

import { mergeTurnPatches } from '../lib/codexTurnCache'
import { CodexTurnSync, normalizeThreadDeltaPayload } from '../lib/codexTurnSync'
import type { CodexTurnCache } from '../lib/codexTurnCache'

describe('Codex turn delta synchronization', () => {
  it('applies appended text and authoritative item replacements', () => {
    const turns = mergeTurnPatches(
      [
        {
          turnId: 'turn-1',
          status: 'inProgress',
          durationMs: 10,
          items: [
            { id: 'message-1', type: 'agentMessage', text: 'Hello' },
            { id: 'tool-1', type: 'commandExecution', status: 'running' },
          ],
        },
      ],
      [
        {
          turn_id: 'turn-1',
          set: { durationMs: 20 },
          remove: [],
          item_count: 3,
          item_patches: [
            { index: 0, append_fields: { text: ' world' } },
            {
              index: 1,
              item: { id: 'tool-1', type: 'commandExecution', status: 'completed' },
            },
            { index: 2, item: { id: 'message-2', type: 'agentMessage', text: 'Done' } },
          ],
        },
      ],
    )

    expect(turns).toEqual([
      {
        turnId: 'turn-1',
        status: 'inProgress',
        durationMs: 20,
        items: [
          { id: 'message-1', type: 'agentMessage', text: 'Hello world' },
          { id: 'tool-1', type: 'commandExecution', status: 'completed' },
          { id: 'message-2', type: 'agentMessage', text: 'Done' },
        ],
      },
    ])
  })

  it('normalizes and persists patched turns as complete cache records', async () => {
    const update = vi.fn().mockResolvedValue(undefined)
    const cache: CodexTurnCache = {
      load: vi.fn().mockResolvedValue({ turns: [] }),
      update,
      remove: vi.fn().mockResolvedValue(undefined),
    }
    const sync = new CodexTurnSync(cache)
    const initial = sync.applyDelta({
      thread_id: 'thread-1',
      state: { id: 'thread-1' },
      turn_ids: ['turn-1'],
      turns: [
        {
          turnId: 'turn-1',
          status: 'inProgress',
          items: [{ type: 'agentMessage', text: 'Hello' }],
        },
      ],
      turn_patches: [],
    })
    const normalized = normalizeThreadDeltaPayload(
      {
        thread_id: 'thread-1',
        state: { id: 'thread-1' },
        turn_ids: ['turn-1'],
        turns: [],
        turn_patches: [
          {
            turn_id: 'turn-1',
            set: {},
            remove: [],
            item_count: 1,
            item_patches: [{ index: 0, append_fields: { text: ' world' } }],
          },
        ],
      },
      '',
    )

    expect(normalized).not.toBeNull()
    const updated = sync.applyDelta(normalized!, initial.state?.turns)
    await Promise.resolve()

    expect(updated.state?.turns?.[0]?.items).toEqual([
      { type: 'agentMessage', text: 'Hello world' },
    ])
    expect(update).toHaveBeenLastCalledWith('thread-1', ['turn-1'], [
      {
        turnId: 'turn-1',
        status: 'inProgress',
        items: [{ type: 'agentMessage', text: 'Hello world' }],
      },
    ])
  })
})
