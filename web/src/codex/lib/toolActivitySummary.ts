import type { JsonRecord } from '../types'
import { isRecord, textFromInput } from './format'

export interface ToolActivitySummary {
  active: boolean
  icon: string
  parts: string[]
  text: string
}

interface SummaryPart {
  icon: string
  text: string
}

const activeStatuses = new Set([
  'active',
  'inprogress',
  'in_progress',
  'pending',
  'running',
  'working',
])

export function summarizeToolActivity(items: JsonRecord[]): ToolActivitySummary {
  const activeItem = [...items].reverse().find(isItemInProgress)
  if (activeItem) {
    const part = activeSummaryPart(activeItem)
    return {
      active: true,
      icon: part.icon,
      parts: [part.text],
      text: part.text,
    }
  }

  const parts = completedSummaryParts(items)
  const textParts = parts.map((part, index) => (index === 0 ? part.text : lowerFirst(part.text)))
  return {
    active: false,
    icon: parts[0]?.icon ?? 'pi-sparkles',
    parts: textParts,
    text: formatSummaryList(textParts),
  }
}

function completedSummaryParts(items: JsonRecord[]): SummaryPart[] {
  const integrationNames = new Set<string>()
  const dynamicTools = new Map<string, string>()
  let unnamedToolCalls = 0
  let loadedTools = 0
  let changedFiles = 0
  let exploredFiles = false
  let commands = 0
  let webSearches = 0
  let agentCalls = 0
  let viewedImages = 0
  let generatedImages = 0
  let steers = 0

  for (const item of items) {
    switch (itemType(item)) {
      case 'commandExecution': {
        const commandKind = commandSummaryKind(item)
        if (commandKind === 'loaded-tool') {
          loadedTools += 1
        } else if (commandKind === 'exploration') {
          exploredFiles = true
        } else {
          commands += 1
        }
        break
      }
      case 'fileChange':
        changedFiles += fileChangeCount(item)
        break
      case 'webSearch':
      case 'search':
        webSearches += 1
        break
      case 'mcpToolCall': {
        const server = mcpServerName(item)
        if (isNodeReplServer(server)) {
          commands += 1
        } else if (server) {
          integrationNames.add(integrationDisplayName(server))
        } else {
          unnamedToolCalls += 1
        }
        break
      }
      case 'dynamicToolCall': {
        const name = toolName(item)
        dynamicTools.set(name.toLowerCase(), name)
        break
      }
      case 'collabAgentToolCall':
      case 'subAgentActivity':
        agentCalls += 1
        break
      case 'imageView':
        viewedImages += 1
        break
      case 'imageGeneration':
        generatedImages += 1
        break
      case 'steer':
      case 'steered':
      case 'steeringUserMessage':
        steers += 1
        break
    }
  }

  const parts: SummaryPart[] = []
  if (integrationNames.size) {
    const names = [...integrationNames]
    const hasBrowser = names.includes('the browser')
    const sourceList = formatSummaryList(names)
    parts.push({
      icon: hasBrowser ? 'pi-globe' : 'pi-box',
      text: hasBrowser
        ? `Used ${sourceList}`
        : `Used ${sourceList} ${names.length === 1 ? 'integration' : 'integrations'}`,
    })
  }
  pushCountPart(parts, loadedTools, 'Loaded a tool', 'Loaded tools', 'pi-book')
  pushCountPart(parts, unnamedToolCalls, 'Called a tool', 'Called tools', 'pi-wrench')
  pushCountPart(parts, changedFiles, 'Edited a file', 'Edited files', 'pi-file-edit')
  if (exploredFiles) {
    parts.push({ icon: 'pi-search', text: 'Read files' })
  }
  pushCountPart(parts, commands, 'Ran a command', 'Ran commands', 'pi-code')
  if (webSearches) {
    parts.push({ icon: 'pi-globe', text: 'Searched the web' })
  }
  for (const name of dynamicTools.values()) {
    parts.push({ icon: 'pi-wrench', text: `Called ${humanizeName(name)}` })
  }
  pushCountPart(parts, agentCalls, 'Used an agent', 'Used agents', 'pi-users')
  pushCountPart(parts, viewedImages, 'Viewed an image', 'Viewed images', 'pi-image')
  pushCountPart(parts, generatedImages, 'Generated an image', 'Generated images', 'pi-image')
  pushCountPart(parts, steers, 'Steered conversation', 'Steered conversation', 'pi-directions')

  return parts.length ? parts : [{ icon: 'pi-sparkles', text: 'Worked' }]
}

function activeSummaryPart(item: JsonRecord): SummaryPart {
  const type = itemType(item)
  if (type === 'commandExecution') {
    const action = primaryCommandAction(item)
    const actionType = commandActionType(action)
    if (actionType === 'read') {
      const path = firstString(action?.path, action?.name)
      if (isSkillDefinitionPath(path)) {
        return { icon: 'pi-book', text: `Reading ${skillName(path)} skill` }
      }
      return { icon: 'pi-file', text: `Reading ${displayPath(path) || 'a file'}` }
    }
    if (actionType === 'search') {
      const query = firstString(action?.query)
      const path = firstString(action?.path)
      if (query) {
        return { icon: 'pi-search', text: `Searching for ${query}` }
      }
      return {
        icon: 'pi-search',
        text: path ? `Searching files in ${displayPath(path)}` : 'Searching files',
      }
    }
    if (actionType === 'listfiles') {
      const path = firstString(action?.path)
      return {
        icon: 'pi-list',
        text: path ? `Listing files in ${displayPath(path)}` : 'Listing files',
      }
    }
    return {
      icon: 'pi-code',
      text: `Running ${cleanShellCommand(firstString(item.command, item.cmd)) || 'command'}`,
    }
  }
  if (type === 'fileChange') {
    return { icon: 'pi-file-edit', text: 'Editing files' }
  }
  if (type === 'webSearch' || type === 'search') {
    const query = webSearchSubject(item)
    return {
      icon: 'pi-globe',
      text: query ? `Searching the web for ${query}` : 'Searching the web',
    }
  }
  if (type === 'mcpToolCall') {
    const server = mcpServerName(item)
    const name = humanizeName(toolName(item))
    return {
      icon: isBrowserSource(server) ? 'pi-globe' : 'pi-box',
      text: `Calling ${server ? `${integrationDisplayName(server)} / ` : ''}${name}`,
    }
  }
  if (type === 'dynamicToolCall') {
    return { icon: 'pi-wrench', text: `Calling ${humanizeName(toolName(item))}` }
  }
  if (type === 'collabAgentToolCall' || type === 'subAgentActivity') {
    return { icon: 'pi-users', text: 'Using an agent' }
  }
  if (type === 'imageGeneration') {
    return { icon: 'pi-image', text: 'Generating an image' }
  }
  if (type === 'sleep') {
    return { icon: 'pi-clock', text: 'Sleeping' }
  }
  return { icon: 'pi-sparkles', text: 'Working' }
}

function commandSummaryKind(item: JsonRecord) {
  const action = primaryCommandAction(item)
  const actionType = commandActionType(action)
  if (actionType === 'read' && isSkillDefinitionPath(firstString(action?.path, action?.name))) {
    return 'loaded-tool'
  }
  if (['read', 'search', 'listfiles'].includes(actionType)) {
    return 'exploration'
  }
  const command = firstString(item.command, item.cmd)
  return /\b(rg|grep|ag|fd|find|ls|sed|head|tail|cat)\b/.test(command) ? 'exploration' : 'command'
}

function primaryCommandAction(item: JsonRecord) {
  const actions = item.commandActions ?? item.command_actions
  if (!Array.isArray(actions)) {
    return null
  }
  return actions.find(isRecord) ?? null
}

function commandActionType(action: JsonRecord | null) {
  return firstString(action?.type).replace(/[_-]/g, '').toLowerCase()
}

function isItemInProgress(item: JsonRecord) {
  if (item.completed === false) {
    return true
  }
  const status = firstString(item.status, item.executionStatus).toLowerCase()
  return activeStatuses.has(status)
}

function itemType(item: JsonRecord) {
  return typeof item.type === 'string' && item.type ? item.type : 'unknown'
}

function fileChangeCount(item: JsonRecord) {
  const changes = item.changes
  if (Array.isArray(changes)) {
    return Math.max(changes.length, 1)
  }
  if (isRecord(changes)) {
    return Math.max(Object.keys(changes).length, 1)
  }
  return 1
}

function mcpServerName(item: JsonRecord) {
  const invocation = isRecord(item.invocation) ? item.invocation : null
  return firstString(item.server, item.serverName, invocation?.server)
}

function toolName(item: JsonRecord) {
  const invocation = isRecord(item.invocation) ? item.invocation : null
  return firstString(item.tool, item.name, item.functionName, invocation?.tool) || 'tool'
}

function webSearchSubject(item: JsonRecord) {
  const action = isRecord(item.action) ? item.action : null
  const queries = action?.queries
  if (Array.isArray(queries)) {
    const query = queries.find(
      (value): value is string => typeof value === 'string' && Boolean(value),
    )
    if (query) {
      return query
    }
  }
  return firstString(item.query, item.searchTerm, item.search_term, action?.query, action?.url)
}

function firstString(...values: unknown[]) {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) {
      return value.trim()
    }
    const text = textFromInput(value).trim()
    if (text) {
      return text
    }
  }
  return ''
}

function humanizeName(value: string) {
  return value
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\b\w/g, (character) => character.toUpperCase())
}

function integrationDisplayName(server: string) {
  return isBrowserSource(server) ? 'the browser' : humanizeName(server)
}

function isBrowserSource(server: string) {
  return ['browser', 'browser-act', 'browser-use', 'playwright'].includes(server.toLowerCase())
}

function isNodeReplServer(server: string) {
  return server.replace(/[-_]/g, '').toLowerCase() === 'noderepl'
}

function isSkillDefinitionPath(path: string) {
  return /(?:^|[/\\])SKILL\.md$/i.test(path)
}

function skillName(path: string) {
  const parts = path.split(/[/\\]/).filter(Boolean)
  return humanizeName(parts[parts.length - 2] ?? 'tool')
}

function displayPath(path: string) {
  const parts = path.split(/[/\\]/).filter(Boolean)
  return parts[parts.length - 1] ?? path
}

function cleanShellCommand(command: string) {
  let text = command.trim().replace(/^\$\s+/, '')
  const shellMatch = text.match(/^(?:\/bin\/)?(?:zsh|bash|sh)\s+-lc\s+([\s\S]+)$/)
  if (shellMatch?.[1]) {
    text = shellMatch[1].trim()
  }
  if (
    (text.startsWith('"') && text.endsWith('"')) ||
    (text.startsWith("'") && text.endsWith("'"))
  ) {
    text = text.slice(1, -1)
  }
  return text.replace(/\\"/g, '"').replace(/\\'/g, "'").trim()
}

function pushCountPart(
  parts: SummaryPart[],
  count: number,
  singular: string,
  plural: string,
  icon: string,
) {
  if (count > 0) {
    parts.push({ icon, text: count === 1 ? singular : plural })
  }
}

function formatSummaryList(parts: string[]) {
  if (parts.length <= 1) {
    return parts[0] ?? 'Worked'
  }
  if (parts.length === 2) {
    return `${parts[0]} and ${parts[1]}`
  }
  return `${parts.slice(0, -1).join(', ')}, and ${parts[parts.length - 1]}`
}

function lowerFirst(value: string) {
  return value ? `${value.charAt(0).toLowerCase()}${value.slice(1)}` : value
}
