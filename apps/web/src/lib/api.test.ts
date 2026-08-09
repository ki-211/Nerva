import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError } from './api';

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('API error parsing', () => {
  it('parses the new error envelope and request id', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: { code: 'RATE_LIMITED', message: '操作过于频繁', retryable: true, request_id: 'req-new' },
    }), { status: 429, headers: { 'Content-Type': 'application/json', 'X-Request-ID': 'req-header' } })));
    await expect(api.me()).rejects.toMatchObject({
      status: 429, code: 'RATE_LIMITED', requestId: 'req-new', action: 'retry',
    });
  });

  it('temporarily supports the legacy detail shape', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: { code: 'DOCUMENT_VERSION_CONFLICT', message: '版本冲突', current_version: 3 },
    }), { status: 409, headers: { 'Content-Type': 'application/json' } })));
    await expect(api.me()).rejects.toMatchObject({
      status: 409, code: 'DOCUMENT_VERSION_CONFLICT', currentVersion: 3, action: 'refresh',
    });
  });

  it('maps non-json failures to a safe message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html>proxy error</html>', { status: 503 })));
    await expect(api.me()).rejects.toSatisfy((error: ApiError) =>
      error.code === 'HTTP_503' && error.message.includes('服务暂时不可用') && !error.message.includes('proxy error'));
  });

  it('maps a non-json success response to a safe protocol error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html>unexpected</html>', {
      status: 200, headers: { 'X-Request-ID': 'req-invalid-json' },
    })));
    await expect(api.me()).rejects.toMatchObject({
      code: 'API_INVALID_RESPONSE', requestId: 'req-invalid-json', action: 'retry',
    });
  });

  it('maps connection failure to a retryable desktop-safe error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('connection refused')));
    await expect(api.me()).rejects.toMatchObject({ code: 'API_UNAVAILABLE', retryable: true, category: 'network' });
  });

  it('maps a request timeout without exposing the browser exception', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn().mockImplementation((_url, init: RequestInit) => new Promise((_resolve, reject) => {
      init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
    })));
    const pending = api.me();
    const assertion = expect(pending).rejects.toMatchObject({ code: 'API_TIMEOUT', action: 'retry' });
    await vi.advanceTimersByTimeAsync(15_001);
    await assertion;
    vi.useRealTimers();
  });

  it('signals centralized session expiry for protected requests', async () => {
    const expired = vi.fn();
    window.addEventListener('nerva:session-expired', expired, { once: true });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: { code: 'AUTH_REQUIRED', message: '登录已失效', request_id: 'req-auth' },
    }), { status: 401, headers: { 'Content-Type': 'application/json' } })));
    await expect(api.me()).rejects.toMatchObject({ status: 401, action: 'login' });
    expect(expired).toHaveBeenCalledOnce();
  });

  it('detects an SSE connection that closes without a terminal event', async () => {
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('event: delta\ndata: {"text":"partial"}\n\n'));
        controller.close();
      },
    });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(stream, {
      status: 200, headers: { 'Content-Type': 'text/event-stream' },
    })));
    const handlers = { onStart: vi.fn(), onDelta: vi.fn(), onMemoryCandidates: vi.fn(), onDone: vi.fn(), onError: vi.fn() };
    await expect(api.sendChatMessage('session-1', 'hello', handlers)).rejects.toMatchObject({
      code: 'CHAT_STREAM_INTERRUPTED', retryable: true,
    });
    expect(handlers.onDelta).toHaveBeenCalledWith('partial');
  });
});
