const USER_REQUEST_MARKER = '## My request for Codex:'
const COMMENT_SECTION_MARKERS = ['# Browser comments:', '# Diff comments:']
const COMMENT_HEADING_PATTERN = /^## (?:User Comment|Comment|Requested annotation)(?:\s|$)/
const COMMENT_BODY_LABELS = ['Comment:', 'Requested changes:']
const COMMENT_BODY_END_PATTERNS = [
  /^<in-app-browser-context source="ambient-ui-state">$/,
  /^# In app browser:$/,
  /^# Chrome tabs:$/,
  /^Style provenance:/,
  /^Apply each annotation to the source code or design tokens that own the current UI\./,
]

function commentSectionStart(text: string) {
  return COMMENT_SECTION_MARKERS.reduce((earliest, marker) => {
    const index = text.indexOf(marker)
    if (index < 0) {
      return earliest
    }
    return earliest < 0 ? index : Math.min(earliest, index)
  }, -1)
}

function commentBody(lines: string[]) {
  const labelIndex = lines.findIndex((line) => COMMENT_BODY_LABELS.includes(line.trim()))
  const legacyHeading = /^## Comment \d+ \(.+\)$/.test(lines[0]?.trim() ?? '')
  const start = labelIndex >= 0 ? labelIndex + 1 : legacyHeading ? 1 : -1
  if (start < 0) {
    return ''
  }
  const endOffset = lines
    .slice(start)
    .findIndex((line) => COMMENT_BODY_END_PATTERNS.some((pattern) => pattern.test(line.trim())))
  const bodyLines = lines.slice(start, endOffset < 0 ? undefined : start + endOffset)
  const requestedChanges = lines[labelIndex]?.trim() === 'Requested changes:'
  return bodyLines
    .map((line) => (requestedChanges && line.startsWith('- ') ? line.slice(2) : line))
    .join('\n')
    .trim()
}

function commentDisplayText(text: string) {
  const start = commentSectionStart(text)
  if (start < 0) {
    return ''
  }
  const finalRequestStart = text.lastIndexOf(USER_REQUEST_MARKER)
  const requestStart = finalRequestStart >= start ? finalRequestStart : -1
  const section = text.slice(start, requestStart < 0 ? undefined : requestStart)
  const lines = section.split('\n')
  const headingIndexes = lines.flatMap((line, index) =>
    COMMENT_HEADING_PATTERN.test(line.trim()) ? [index] : [],
  )
  return headingIndexes
    .map((headingIndex, index) =>
      commentBody(lines.slice(headingIndex, headingIndexes[index + 1] ?? undefined)),
    )
    .filter(Boolean)
    .join('\n\n')
}

export function userMessageDisplayText(text: string) {
  const comments = commentDisplayText(text)
  if (comments) {
    return comments
  }
  const sections = text.split(USER_REQUEST_MARKER)
  if (sections.length <= 1) {
    return text
  }
  return (sections[sections.length - 1] ?? '').trim()
}
