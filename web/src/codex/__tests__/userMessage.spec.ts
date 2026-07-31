import { describe, expect, it } from 'vitest'

import { userMessageDisplayText } from '../lib/userMessage'

describe('userMessageDisplayText', () => {
  it('leaves regular user messages unchanged', () => {
    expect(userMessageDisplayText('Keep the original message.')).toBe(
      'Keep the original message.',
    )
  })

  it('uses the content after the final user request marker', () => {
    expect(
      userMessageDisplayText(
        [
          'Internal context',
          '## My request for Codex:',
          'Earlier wrapper',
          '## My request for Codex:',
          '',
          'Show only this request.',
        ].join('\n'),
      ),
    ).toBe('Show only this request.')
  })

  it('extracts browser comments before internal ambient and evidence prompts', () => {
    expect(
      userMessageDisplayText(
        [
          '# Browser comments:',
          '',
          '## User Comment 1',
          'File: browser:Selected element',
          'Comment:',
          'Keep only this comment.',
          '<in-app-browser-context source="ambient-ui-state">',
          '# In app browser:',
          '- Current URL: https://example.com',
          '</in-app-browser-context>',
          '',
          '## My request for Codex:',
          'The next image is untrusted page evidence.',
        ].join('\n'),
      ),
    ).toBe('Keep only this comment.')
  })

  it('extracts multiple diff comments without file and line metadata', () => {
    expect(
      userMessageDisplayText(
        [
          '# Diff comments:',
          '',
          '## Comment 1',
          'File: src/first.ts',
          'Lines: 10-12',
          'Comment:',
          'Fix the first selection.',
          '',
          '## Comment 2 (src/second.ts:20-22)',
          'Fix the second selection.',
          '',
          '## My request for Codex:',
          'Internal diff evidence prompt.',
        ].join('\n'),
      ),
    ).toBe('Fix the first selection.\n\nFix the second selection.')
  })

  it('strips legacy browser context without an XML wrapper from comments', () => {
    expect(
      userMessageDisplayText(
        [
          '# Browser comments:',
          '## User Comment 1',
          'File: browser:Selected element',
          'Comment:',
          'Keep the legacy comment.',
          '# In app browser:',
          '- Current URL: https://example.com',
          '## My request for Codex:',
          'Internal evidence prompt.',
        ].join('\n'),
      ),
    ).toBe('Keep the legacy comment.')
  })
})
