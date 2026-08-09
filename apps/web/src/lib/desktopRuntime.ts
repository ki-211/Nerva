export type DesktopLogLevel = 'debug' | 'info' | 'warn' | 'error';

type DesktopRuntime = {
  saveBlob: (blob: Blob, filename: string) => Promise<void>;
  openPrintView: (query: string) => Promise<void>;
  openExternalUrl: (url: string) => Promise<void>;
  writeLog: (level: DesktopLogLevel, line: string) => void;
};

const browserRuntime: DesktopRuntime = {
  async saveBlob(blob, filename) {
    const picker = (window as typeof window & {
      showSaveFilePicker?: (options: unknown) => Promise<{
        createWritable: () => Promise<{ write: (data: Blob) => Promise<void>; close: () => Promise<void> }>;
      }>;
    }).showSaveFilePicker;
    if (picker) {
      const extension = filename.includes('.') ? `.${filename.split('.').pop()}` : '';
      const handle = await picker({
        suggestedName: filename,
        types: [{ description: 'Nerva 文件', accept: { [blob.type || 'application/octet-stream']: extension ? [extension] : [] } }],
      });
      const writable = await handle.createWritable();
      await writable.write(blob);
      await writable.close();
      return;
    }
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
  },
  async openPrintView(query) {
    window.open(`/export/print?${query}`, '_blank', 'noopener,noreferrer');
  },
  async openExternalUrl(url) {
    window.open(url, '_blank', 'noopener,noreferrer');
  },
  writeLog() {
    // Browser development keeps its existing console and Sentry targets.
  },
};

let runtime = browserRuntime;

export function configureDesktopRuntime(overrides: Partial<DesktopRuntime>): void {
  runtime = { ...browserRuntime, ...overrides };
}

export function saveBlob(blob: Blob, filename: string): Promise<void> {
  return runtime.saveBlob(blob, filename);
}

export function openPrintView(query: string): Promise<void> {
  return runtime.openPrintView(query);
}

export function openExternalUrl(url: string): Promise<void> {
  const parsed = new URL(url);
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    return Promise.reject(new Error('仅允许打开 HTTP 或 HTTPS 来源'));
  }
  return runtime.openExternalUrl(parsed.toString());
}

export function writeDesktopLog(level: DesktopLogLevel, line: string): void {
  runtime.writeLog(level, line);
}
