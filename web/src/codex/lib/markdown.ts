import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js/lib/common'

import { resolveHighlightLanguage } from '../../lib/codeHighlight'

const markdown = new MarkdownIt({
  html: false,
  breaks: true,
  linkify: true,
})

const markdownCopyResetTimers = new WeakMap<HTMLButtonElement, number>()
const markdownCopyButtonLabel = 'Copy code block'
const markdownCopiedButtonLabel = 'Copied'
const markdownCopyButtonIcon = '<i class="pi pi-copy" aria-hidden="true"></i>'
const markdownCopiedButtonIcon = '<i class="pi pi-check" aria-hidden="true"></i>'
const imageFileExtensionPattern = /\.(?:png|jpe?g|gif|webp|bmp)(?:[?#].*)?$/i
const renderedMarkdownCache = new Map<string, string>()
const renderedMarkdownCacheLimit = 300

export function markdownInlineText(content: string) {
  const tokens = markdown.parseInline(content, {})
  const inlineTokens = tokens.flatMap((token) => token.children ?? [])
  return markdown.renderer.renderInlineAsText(inlineTokens, markdown.options, {}).trim()
}

function highlightMarkdownCode(content: string, language = '') {
  const { requestedLanguage, highlightLanguage } = resolveHighlightLanguage(language)
  const escapedContent = markdown.utils.escapeHtml(content)

  if (!highlightLanguage || !hljs.getLanguage(highlightLanguage)) {
    return {
      classNames: requestedLanguage ? ['hljs', `language-${requestedLanguage}`] : [],
      content: escapedContent,
    }
  }

  return {
    classNames: ['hljs', `language-${requestedLanguage || highlightLanguage}`],
    content: hljs.highlight(content, { language: highlightLanguage, ignoreIllegals: true }).value,
  }
}

function renderMarkdownCodeBlock(content: string, languageClass = '', languageLabel = '') {
  const escapedLabel = languageLabel ? markdown.utils.escapeHtml(languageLabel) : ''
  return `
    <div class="markdown-code-block">
      <div class="markdown-code-toolbar">
        ${escapedLabel ? `<span class="markdown-code-language">${escapedLabel}</span>` : '<span></span>'}
        <button
          type="button"
          class="markdown-code-copy"
          data-copy-markdown-code
          aria-label="${markdownCopyButtonLabel}"
          title="${markdownCopyButtonLabel}"
        >
          ${markdownCopyButtonIcon}
        </button>
      </div>
      <pre><code${languageClass}>${content}</code></pre>
    </div>
  `
}

markdown.renderer.rules.fence = (tokens, idx) => {
  const token = tokens[idx]
  if (!token) {
    return ''
  }
  const info = token.info ? markdown.utils.unescapeAll(token.info).trim() : ''
  const language = info ? info.split(/\s+/g)[0] ?? '' : ''
  const highlightedCode = highlightMarkdownCode(token.content, language)
  const languageClasses = highlightedCode.classNames
  const languageClass = languageClasses.length
    ? ` class="${markdown.utils.escapeHtml(languageClasses.join(' '))}"`
    : ''
  return renderMarkdownCodeBlock(highlightedCode.content, languageClass, language)
}

markdown.renderer.rules.code_block = (tokens, idx) => {
  const token = tokens[idx]
  return renderMarkdownCodeBlock(highlightMarkdownCode(token?.content ?? '').content, ' class="hljs"')
}

function isExternalOrDataUrl(value: string) {
  return /^(?:[a-z][a-z\d+.-]*:|\/\/)/i.test(value)
}

function isHostImagePath(value: string) {
  if (!imageFileExtensionPattern.test(value) || isExternalOrDataUrl(value)) {
    return false
  }
  return (
    value.startsWith('/Users/') ||
    value.startsWith('/private/') ||
    value.startsWith('/tmp/') ||
    value.startsWith('/var/') ||
    /^\/(?:home|mnt|Volumes)\//.test(value) ||
    /^[a-z]:[\\/]/i.test(value) ||
    value.startsWith('~/')
  )
}

function codexMarkdownImageUrl(path: string) {
  const query = new URLSearchParams({ path })
  return `/api/codex/image?${query.toString()}`
}

markdown.renderer.rules.image = (tokens, idx, options, env, self) => {
  const token = tokens[idx]
  const src = token?.attrGet('src') ?? ''
  if (src && isHostImagePath(src)) {
    token?.attrSet('src', codexMarkdownImageUrl(src))
  }
  if (token) {
    token.attrSet('alt', self.renderInlineAsText(token.children ?? [], options, env))
  }
  return self.renderToken(tokens, idx, options)
}

export function useCodexMarkdown() {
  function renderMarkdown(content: string) {
    const cached = renderedMarkdownCache.get(content)
    if (cached != null) {
      renderedMarkdownCache.delete(content)
      renderedMarkdownCache.set(content, cached)
      return cached
    }
    const rendered = markdown.render(content)
    renderedMarkdownCache.set(content, rendered)
    if (renderedMarkdownCache.size > renderedMarkdownCacheLimit) {
      const oldestKey = renderedMarkdownCache.keys().next().value
      if (oldestKey != null) {
        renderedMarkdownCache.delete(oldestKey)
      }
    }
    return rendered
  }

  async function onMarkdownClick(event: MouseEvent) {
    const target = event.target
    if (!(target instanceof Element)) {
      return
    }

    const button = target.closest('[data-copy-markdown-code]')
    if (!(button instanceof HTMLButtonElement)) {
      return
    }

    const block = button.closest('.markdown-code-block')
    const codeElement = block?.querySelector('code')
    if (!(codeElement instanceof HTMLElement)) {
      return
    }

    const codeText = (codeElement.innerText || codeElement.textContent || '').replace(/\n$/, '')
    await navigator.clipboard.writeText(codeText)
    button.dataset.state = 'copied'
    button.innerHTML = markdownCopiedButtonIcon
    button.setAttribute('aria-label', markdownCopiedButtonLabel)
    button.setAttribute('title', markdownCopiedButtonLabel)

    const existingTimer = markdownCopyResetTimers.get(button)
    if (existingTimer) {
      window.clearTimeout(existingTimer)
    }

    const resetTimer = window.setTimeout(() => {
      delete button.dataset.state
      button.innerHTML = markdownCopyButtonIcon
      button.setAttribute('aria-label', markdownCopyButtonLabel)
      button.setAttribute('title', markdownCopyButtonLabel)
      markdownCopyResetTimers.delete(button)
    }, 1600)

    markdownCopyResetTimers.set(button, resetTimer)
  }

  return {
    renderMarkdown,
    onMarkdownClick,
  }
}
