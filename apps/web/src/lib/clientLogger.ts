import * as Sentry from '@sentry/react';

export type ClientLogLevel = 'debug' | 'info' | 'warn' | 'error';
export type ClientType = 'user-desktop' | 'admin-desktop' | 'web-development';

type LogContext = Record<string, unknown> & {
  operation?: string;
  errorCode?: string;
  requestId?: string;
};

type LogEntry = {
  timestamp: string;
  level: ClientLogLevel;
  clientType: ClientType;
  version: string;
  message: string;
  context: Record<string, unknown>;
};

declare global {
  interface Window {
    __NERVA_DESKTOP_LOG__?: (line: string) => void;
  }
}

const CLIENT_TYPE = (import.meta.env.VITE_CLIENT_TYPE || 'web-development') as ClientType;
const VERSION = import.meta.env.VITE_APP_VERSION || '0.1.0';
const MAX_MEMORY_ENTRIES = 500;
export const DESKTOP_LOG_POLICY = Object.freeze({ maxFileBytes: 10 * 1024 * 1024, retainedFiles: 5 });
const entries: LogEntry[] = [];

const sensitiveKey = /(^|_)(content|markdown|text|body|data|form|files|query_string|ocr|embedding|password|passcode|verification_code|cookie|token|authorization|api_key|email)($|_)/i;

function redactString(value: string): string {
  return value
    .replace(/Bearer\s+[A-Za-z0-9._~+/=-]+/gi, 'Bearer [REDACTED]')
    .replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, '[REDACTED_EMAIL]')
    .replace(/(password|token|cookie|api[_-]?key)\s*[=:]\s*[^\s,;]+/gi, '$1=[REDACTED]')
    .slice(0, 1_000);
}

export function redact(value: unknown, key = '', depth = 0): unknown {
  if (sensitiveKey.test(key)) return '[REDACTED]';
  if (depth > 5) return '[TRUNCATED]';
  if (typeof value === 'string') return redactString(value);
  if (value instanceof Error) return { name: value.name, message: redactString(value.message) };
  if (Array.isArray(value)) return value.slice(0, 50).map((item) => redact(item, key, depth + 1));
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>)
      .map(([childKey, childValue]) => [childKey, redact(childValue, childKey, depth + 1)]));
  }
  return value;
}

function write(level: ClientLogLevel, message: string, context: LogContext = {}, error?: unknown): void {
  const safeContext = redact(context) as Record<string, unknown>;
  const entry: LogEntry = {
    timestamp: new Date().toISOString(), level, clientType: CLIENT_TYPE,
    version: VERSION, message: redactString(message), context: safeContext,
  };
  entries.push(entry);
  if (entries.length > MAX_MEMORY_ENTRIES) entries.splice(0, entries.length - MAX_MEMORY_ENTRIES);
  const line = JSON.stringify(entry);
  if (import.meta.env.DEV) {
    const method = level === 'debug' ? 'debug' : level === 'info' ? 'info' : level === 'warn' ? 'warn' : 'error';
    console[method]('[Nerva]', entry.message, safeContext);
  }
  window.__NERVA_DESKTOP_LOG__?.(line);
  if (level === 'error' && import.meta.env.PROD && import.meta.env.VITE_SENTRY_DSN) {
    Sentry.withScope((scope) => {
      scope.setTag('client_type', CLIENT_TYPE);
      scope.setTag('release', VERSION);
      if (context.requestId) scope.setTag('request_id', context.requestId);
      if (context.errorCode) scope.setTag('error_code', context.errorCode);
      scope.setContext('nerva', safeContext);
      Sentry.captureException(error instanceof Error ? error : new Error(entry.message));
    });
  }
}

export const clientLogger = {
  debug: (message: string, context?: LogContext) => write('debug', message, context),
  info: (message: string, context?: LogContext) => write('info', message, context),
  warn: (message: string, context?: LogContext) => write('warn', message, context),
  error: (message: string, error?: unknown, context?: LogContext) => write('error', message, context, error),
};

export function initializeClientMonitoring(): void {
  const dsn = import.meta.env.VITE_SENTRY_DSN;
  if (!import.meta.env.PROD || !dsn) return;
  Sentry.init({
    dsn,
    release: VERSION,
    environment: import.meta.env.VITE_APP_ENV || 'production',
    tracesSampleRate: 0.1,
    sendDefaultPii: false,
    beforeSend: (event) => {
      const safe = redact(event) as typeof event;
      safe.user = undefined;
      if (safe.request?.url) safe.request.url = safe.request.url.split('?', 1)[0];
      safe.exception?.values?.forEach((item) => { item.value = 'Client exception'; });
      safe.breadcrumbs?.forEach((breadcrumb) => {
        const url = breadcrumb.data?.url;
        if (typeof url === 'string') breadcrumb.data = { ...breadcrumb.data, url: url.split('?', 1)[0] };
      });
      return safe;
    },
  });
}

export async function exportDiagnosticLogs(): Promise<void> {
  const payload = entries.map((entry) => JSON.stringify(redact(entry))).join('\n');
  const blob = new Blob([payload], { type: 'application/x-ndjson' });
  const filename = `nerva-diagnostics-${new Date().toISOString().replace(/[:.]/g, '-')}.ndjson`;
  const picker = (window as typeof window & {
    showSaveFilePicker?: (options: unknown) => Promise<{ createWritable: () => Promise<{ write: (data: Blob) => Promise<void>; close: () => Promise<void> }> }>;
  }).showSaveFilePicker;
  if (picker) {
    const handle = await picker({ suggestedName: filename, types: [{ description: 'Nerva 诊断日志', accept: { 'application/x-ndjson': ['.ndjson'] } }] });
    const writable = await handle.createWritable();
    await writable.write(blob);
    await writable.close();
    return;
  }
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
}
