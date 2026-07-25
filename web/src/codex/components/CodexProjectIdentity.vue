<script setup lang="ts">
import { computed } from 'vue'

import type {
  CodexRemoteConnectionRuntimeStatus,
  CodexWorkspaceResponse,
} from '../types'

const props = defineProps<{
  expanded: boolean
  hostId: string
  workspace: CodexWorkspaceResponse
}>()

const isRemote = computed(() => props.hostId !== 'local')
const connectionId = computed(() =>
  props.hostId.startsWith('ssh:') ? props.hostId.slice(4) : props.hostId,
)
const connection = computed(() =>
  props.workspace.remote_connections?.find((item) => item.id === connectionId.value),
)
const hostLabel = computed(
  () =>
    connection.value?.ssh_alias ||
    connection.value?.display_name ||
    connection.value?.ssh_host ||
    connectionId.value ||
    'Remote',
)
const runtimeStatus = computed<CodexRemoteConnectionRuntimeStatus>(() =>
  props.workspace.remote_connection_statuses?.[connectionId.value]?.status ??
  'disconnected',
)
const runtimeDetail = computed(
  () => props.workspace.remote_connection_statuses?.[connectionId.value]?.detail?.trim() ?? '',
)
const statusLabel = computed(() => {
  switch (runtimeStatus.value) {
    case 'connected':
      return 'Connected'
    case 'connecting':
      return 'Connecting'
    case 'error':
      return 'Error'
    default:
      return 'Disconnected'
  }
})
const statusTitle = computed(() =>
  runtimeDetail.value &&
  runtimeDetail.value.toLocaleLowerCase() !== statusLabel.value.toLocaleLowerCase()
    ? `${hostLabel.value}: ${statusLabel.value} - ${runtimeDetail.value}`
    : `${hostLabel.value}: ${statusLabel.value}`,
)
</script>

<template>
  <span
    class="grid min-w-0 flex-1 grid-cols-[1.15rem_minmax(0,1fr)_auto] items-center gap-2"
    data-codex-project-identity
    :data-host-id="hostId"
  >
    <span
      class="inline-flex h-[1.15rem] w-[1.15rem] items-center justify-center text-[color:var(--app-text-soft)]"
      data-codex-project-source-icon
      :data-source="isRemote ? 'remote' : 'local'"
    >
      <i
        v-if="!isRemote"
        class="pi text-sm"
        :class="expanded ? 'pi-folder-open' : 'pi-folder'"
      ></i>
      <svg
        v-else
        aria-hidden="true"
        class="h-4 w-4"
        viewBox="0 0 16 16"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <path
          fill-rule="evenodd"
          clip-rule="evenodd"
          d="M11.3341 8.99774C13.0412 8.99817 14.4259 10.3823 14.4259 12.0895C14.4257 13.7967 13.0403 15.1802 11.3331 15.1804C9.62649 15.1796 8.24255 13.7963 8.24231 12.0895C8.24231 10.3821 9.62663 8.99774 11.3341 8.99774ZM10.88 12.53C10.9107 13.0499 10.9942 13.5041 11.1066 13.8405C11.1789 14.0567 11.2559 14.2013 11.3204 14.2829C11.3244 14.2878 11.3296 14.2914 11.3331 14.2956C11.3368 14.2913 11.3427 14.2881 11.3468 14.2829C11.4113 14.2012 11.4884 14.0568 11.5607 13.8405C11.6731 13.5041 11.7556 13.0499 11.7863 12.53H10.88ZM9.13489 12.53C9.2686 13.2 9.70172 13.7611 10.2882 14.071C10.1507 13.6447 10.0609 13.1116 10.0304 12.53H9.13489ZM12.6368 12.53C12.6061 13.1117 12.5146 13.6446 12.3771 14.071C12.964 13.7613 13.3976 13.2005 13.5314 12.53H12.6368ZM10.2882 10.1061C9.69233 10.421 9.25628 10.9962 9.13 11.6804H10.0284C10.0573 11.0859 10.1481 10.5404 10.2882 10.1061ZM11.3204 9.8952C11.2559 9.97691 11.1789 10.1221 11.1066 10.3386C10.9919 10.6818 10.9081 11.1473 10.879 11.6804H11.7872C11.7581 11.1474 11.6753 10.6818 11.5607 10.3386C11.4884 10.1223 11.4113 9.97695 11.3468 9.8952C11.3425 9.88982 11.3369 9.88594 11.3331 9.88153C11.3294 9.88589 11.3246 9.88996 11.3204 9.8952ZM12.3771 10.1052C12.5175 10.5396 12.6087 11.0853 12.6378 11.6804H13.5363C13.4099 10.9956 12.9736 10.4198 12.3771 10.1052Z"
          fill="var(--app-accent)"
        />
        <path
          fill-rule="evenodd"
          clip-rule="evenodd"
          d="M5.36926 2.1413C5.9238 2.14134 6.36032 2.23675 6.73254 2.38934C7.09763 2.53904 7.38165 2.73785 7.61829 2.90399C8.07618 3.22547 8.42082 3.47434 9.16614 3.4743H11.9474C13.3337 3.47453 14.4454 4.61186 14.4454 5.99969V7.06512C14.4453 7.48137 14.1213 7.85614 13.6564 7.85614H2.60559V11.3307C2.60559 12.1518 3.26039 12.8051 4.05383 12.8054H6.16907C6.45883 12.8056 6.69348 13.0409 6.69348 13.3307C6.69348 13.6206 6.45883 13.8559 6.16907 13.8561H4.05383C2.66749 13.8559 1.55579 12.7186 1.55579 11.3307V7.35028C1.55557 7.34411 1.55383 7.33795 1.55383 7.33173C1.55383 7.32523 1.55555 7.31864 1.55579 7.31219V4.66669C1.55579 3.27887 2.66749 2.14155 4.05383 2.1413H5.36926ZM4.05383 3.19208C3.26039 3.19233 2.60559 3.84568 2.60559 4.66669V6.80634H13.3956V5.99969C13.3956 5.17867 12.7408 4.52531 11.9474 4.52509H9.16711C8.07977 4.52528 7.5071 4.10834 7.01575 3.76337C6.77774 3.59627 6.57866 3.46129 6.33411 3.36102C6.09669 3.26369 5.79658 3.19212 5.36926 3.19208H4.05383Z"
          fill="currentColor"
        />
      </svg>
    </span>

    <slot />

    <span
      v-if="isRemote"
      class="inline-flex min-w-0 shrink-0 items-center gap-1.5 text-[0.68rem] font-medium text-[color:var(--app-text-soft)] group-hover/project:hidden group-focus-within/project:hidden"
      data-codex-project-remote-meta
    >
      <span
        class="max-w-20 truncate"
        data-codex-project-alias
        :title="hostLabel"
      >
        {{ hostLabel }}
      </span>
      <span
        class="inline-flex h-3 w-3 shrink-0 items-center justify-center"
        data-codex-project-status
        :data-status="runtimeStatus"
        :aria-label="statusTitle"
        :title="statusTitle"
        role="img"
      >
        <i
          v-if="runtimeStatus === 'connecting'"
          class="pi pi-spinner pi-spin text-[0.58rem]"
        ></i>
        <i
          v-else-if="runtimeStatus === 'error'"
          class="pi pi-exclamation-circle text-[0.62rem] text-red-600"
        ></i>
        <span
          v-else
          aria-hidden="true"
          class="block h-2 w-2 rounded-full"
          :class="runtimeStatus === 'connected' ? 'bg-emerald-500' : 'bg-gray-400'"
        ></span>
      </span>
    </span>
    <span
      aria-hidden="true"
      class="hidden w-7 shrink-0 group-hover/project:block group-focus-within/project:block"
      data-codex-project-action-spacer
    ></span>
  </span>
</template>
