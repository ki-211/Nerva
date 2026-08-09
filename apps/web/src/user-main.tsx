import React from 'react';
import { createRoot } from 'react-dom/client';
import { HashRouter } from 'react-router-dom';
import { invoke } from '@tauri-apps/api/core';
import { save } from '@tauri-apps/plugin-dialog';
import { writeFile } from '@tauri-apps/plugin-fs';
import { fetch as tauriFetch } from '@tauri-apps/plugin-http';
import { debug, error, info, warn } from '@tauri-apps/plugin-log';
import { openUrl } from '@tauri-apps/plugin-opener';
import { UserApplication } from './app/UserApplication';
import { ErrorBoundary } from './app/ErrorBoundary';
import { GlobalErrorNotice, notifyGlobalError } from './app/GlobalErrorNotice';
import { configureApiTransport } from './lib/api';
import { configureDesktopRuntime } from './lib/desktopRuntime';
import { ApiError } from './lib/errors';
import { clientLogger, initializeClientMonitoring } from './lib/clientLogger';
import './styles.css';

configureApiTransport((input, init) => tauriFetch(input, init));
configureDesktopRuntime({
  async saveBlob(blob, filename) {
    const path = await save({ defaultPath: filename, filters: [{ name: 'Nerva 文件', extensions: filename.includes('.') ? [filename.split('.').pop()!] : [] }] });
    if (!path) return;
    await writeFile(path, new Uint8Array(await blob.arrayBuffer()));
  },
  openPrintView: (query) => invoke('open_print_window', { query }),
  openExternalUrl: (url) => openUrl(url),
  writeLog(level, line) {
    const writer = level === 'debug' ? debug : level === 'warn' ? warn : level === 'error' ? error : info;
    void writer(line);
  },
});
initializeClientMonitoring();

function reportGlobalFailure(operation: string, cause: unknown, notify = true): void {
  const mapped = cause instanceof ApiError ? cause : new ApiError('操作失败，请稍后重试', 0, 'CLIENT_UNHANDLED_ERROR');
  clientLogger.error(operation, cause, {
    operation,
    errorCode: mapped.code,
    requestId: mapped.requestId,
    cause,
  });
  if (notify) notifyGlobalError(mapped.message);
}
window.addEventListener('error', (event) => reportGlobalFailure('window.error', event.error));
window.addEventListener('unhandledrejection', (event) => {
  event.preventDefault();
  // API and page actions already present their own actionable errors. A late rejection from
  // WebView/plugin cleanup must not turn a completed operation into a false failure notice.
  reportGlobalFailure('window.unhandledrejection', event.reason, false);
});

createRoot(document.getElementById('root')!).render(<React.StrictMode><ErrorBoundary><HashRouter><UserApplication /><GlobalErrorNotice /></HashRouter></ErrorBoundary></React.StrictMode>);
