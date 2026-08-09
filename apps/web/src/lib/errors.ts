export type ErrorCategory = 'auth' | 'permission' | 'validation' | 'conflict' | 'network' | 'rate-limit' | 'server' | 'unknown';
export type ErrorAction = 'retry' | 'login' | 'refresh' | 'reupload' | 'none';

export function createClientErrorId(): string {
  const random = globalThis.crypto?.randomUUID?.().replaceAll('-', '').slice(0, 12)
    || Math.random().toString(36).slice(2, 14);
  return `client-${random}`;
}

export class ApiError extends Error {
  public requestId?: string;
  public category: ErrorCategory;
  public action: ErrorAction;

  constructor(
    message: string,
    public status: number,
    public code = 'UNKNOWN_ERROR',
    public sourceId?: string,
    public retryable = false,
    public currentVersion?: number,
    public requiresReupload = false,
    requestId?: string,
    category: ErrorCategory = 'unknown',
    action: ErrorAction = 'none',
  ) {
    const effectiveRequestId = requestId || (status === 0 || status >= 500 ? createClientErrorId() : undefined);
    super(effectiveRequestId ? `${message}（错误编号：${effectiveRequestId}）` : message);
    this.name = 'ApiError';
    this.requestId = effectiveRequestId;
    this.category = category;
    this.action = action;
  }
}

export function categoryForStatus(status: number): ErrorCategory {
  if (status === 401) return 'auth';
  if (status === 403) return 'permission';
  if (status === 409) return 'conflict';
  if ([413, 422].includes(status)) return 'validation';
  if (status === 429) return 'rate-limit';
  if (status >= 500) return 'server';
  if (status === 0) return 'network';
  return 'unknown';
}

export function actionForError(status: number, retryable: boolean, requiresReupload = false): ErrorAction {
  if (requiresReupload) return 'reupload';
  if (status === 401) return 'login';
  if (status === 409) return 'refresh';
  if (retryable || status === 0 || status === 429 || status >= 500) return 'retry';
  return 'none';
}

export function fallbackMessage(status: number): string {
  if (status === 0) return '服务暂时不可用，请检查网络';
  if (status === 401) return '登录已失效，请重新登录';
  if (status === 403) return '当前账号没有执行此操作的权限';
  if (status === 404) return '请求的内容不存在或已被移除';
  if (status === 409) return '内容已更新，请刷新后重试';
  if (status === 413) return '上传内容过大，请缩小文件后重新上传';
  if (status === 422) return '输入内容有误，请检查后重试';
  if (status === 429) return '操作过于频繁，请稍后重试';
  if (status >= 500) return '服务暂时不可用，请稍后重试';
  return '操作失败，请稍后重试';
}

export function displayError(error: unknown): string {
  if (!(error instanceof ApiError)) return `操作失败，请稍后重试（错误编号：${createClientErrorId()}）`;
  return error.message;
}

export function signalSessionExpired(): void {
  window.dispatchEvent(new CustomEvent('nerva:session-expired'));
}

export function signalOperationFailure(error: ApiError): void {
  window.dispatchEvent(new CustomEvent('nerva:global-error', { detail: error.message }));
}
