export interface AuthSessionResponse {
  enabled: boolean
  authenticated: boolean
}

export interface AuthLoginRequest {
  password: string
}

export type AuthConfigSource = 'environment' | 'settings' | 'default'

export interface AuthConfigResponse {
  enabled: boolean
  has_password: boolean
  has_secret: boolean
  session_ttl_hours: number
  password_source: AuthConfigSource
  secret_source: AuthConfigSource
  session_ttl_source: AuthConfigSource
}

export interface SaveAuthConfigRequest {
  enabled: boolean
  password: string | null
  secret: string | null
  session_ttl_hours: number
}

export type SpeechConfigSource = 'environment' | 'settings' | 'default'
export type SpeechModelStatus = 'ready' | 'missing'

export interface SpeechConfigResponse {
  model_dir: string
  provider: string
  num_threads: number
  status: SpeechModelStatus
  detail: string
  model_dir_source: SpeechConfigSource
  provider_source: SpeechConfigSource
  num_threads_source: SpeechConfigSource
}

export interface SaveSpeechConfigRequest {
  model_dir: string
  provider: string
  num_threads: number
}

export type SpeechModelDownloadState = 'idle' | 'downloading' | 'ready' | 'error'

export interface SpeechModelDownloadRequest {
  proxy: string | null
}

export interface SpeechModelDownloadResponse {
  state: SpeechModelDownloadState
  downloaded_bytes: number
  total_bytes: number | null
  error: string
  model_dir: string
}

export interface SelectDirectoryResponse {
  selected: boolean
  project_path: string
}
