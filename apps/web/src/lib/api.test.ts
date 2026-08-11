import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError, configureApiTransport } from './api';
import { configureDesktopRuntime } from './desktopRuntime';

afterEach(() => {
  configureApiTransport((input, init) => globalThis.fetch(input, init));
  configureDesktopRuntime({});
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('API error parsing', () => {
  it('uses the configured transport with desktop identity and cookie credentials', async () => {
    const transport = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      id: 'user-1', email: 'user@example.com', role: 'user', created_at: '2026-01-01T00:00:00Z',
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    configureApiTransport(transport);

    await api.me();

    const [, init] = transport.mock.calls[0] as [string, RequestInit];
    expect(init.credentials).toBe('include');
    expect(new Headers(init.headers).get('X-Nerva-Client')).toBeTruthy();
    expect(new Headers(init.headers).get('X-Nerva-Version')).toBe('0.1.0');
  });

  it('accepts an empty 204 response after deleting a chat session', async () => {
    const transport = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    configureApiTransport(transport);

    await expect(api.deleteChatSession('session-1')).resolves.toBeUndefined();

    expect(transport).toHaveBeenCalledOnce();
    const [url, init] = transport.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/v1/chat/sessions/session-1');
    expect(init.method).toBe('DELETE');
  });

  it('sends image uploads as multipart without overriding the boundary', async () => {
    const transport = vi.fn().mockResolvedValue(new Response(JSON.stringify({ source_id: 'source-1', status: 'processing' }), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    }));
    const progress = vi.fn();
    configureApiTransport(transport);

    await api.uploadImages([new File(['image'], 'capture.png', { type: 'image/png' })], 'Capture', 'Note', progress);

    const [, init] = transport.mock.calls[0] as [string, RequestInit];
    expect(init.body).toBeInstanceOf(FormData);
    expect(new Headers(init.headers).has('Content-Type')).toBe(false);
    expect(progress.mock.calls.map(([value]) => value)).toEqual([5, 100]);
  });

  it('saves downloads through the injected desktop runtime', async () => {
    const saveBlob = vi.fn().mockResolvedValue(undefined);
    configureDesktopRuntime({ saveBlob });
    configureApiTransport(vi.fn().mockResolvedValue(new Response('# Knowledge', {
      status: 200,
      headers: { 'Content-Type': 'text/markdown', 'Content-Disposition': 'attachment; filename="knowledge.md"' },
    })));

    await api.exportMarkdown('document', 'doc-1');

    expect(saveBlob).toHaveBeenCalledOnce();
    expect(saveBlob.mock.calls[0][0]).toMatchObject({ size: 11, type: 'text/markdown' });
    expect(saveBlob.mock.calls[0][1]).toBe('knowledge.md');
  });

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

  it('times out even when the desktop transport ignores AbortSignal', async () => {
    vi.useFakeTimers();
    const transport = vi.fn().mockImplementation(() => new Promise(() => undefined));
    configureApiTransport(transport);
    const pending = api.me();
    const assertion = expect(pending).rejects.toMatchObject({ code: 'API_TIMEOUT', action: 'retry' });
    await vi.advanceTimersByTimeAsync(15_001);
    await assertion;
    const [, init] = transport.mock.calls[0] as [string, RequestInit];
    expect(init.signal?.aborted).toBe(true);
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

  it('parses research start, sources, and done events', async () => {
    const message = {
      id: 'assistant-1', session_id: 'research-1', role: 'assistant', status: 'completed',
      content: 'A sourced answer', requested_mode: 'web', basis: 'web', model: 'qwen',
      citations: [{
        ordinal: 1, title: 'Primary source', url: 'https://example.com/source',
        domain: 'example.com', accessed_at: '2026-08-09T00:00:00Z',
      }],
      error_code: null, ingestion_source_id: null,
      created_at: '2026-08-09T00:00:00Z', completed_at: '2026-08-09T00:00:01Z',
    };
    const payload = [
      'event: start\ndata: {"session_id":"research-1","user_message_id":"user-1","assistant_message_id":"assistant-1","requested_mode":"web"}\n\n',
      'event: delta\ndata: {"text":"A sourced answer"}\n\n',
      `event: sources\ndata: ${JSON.stringify({ citations: message.citations, basis: 'web' })}\n\n`,
      `event: done\ndata: ${JSON.stringify({ message })}\n\n`,
    ].join('');
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(payload));
        controller.close();
      },
    });
    const transport = vi.fn().mockResolvedValue(new Response(stream, {
      status: 200, headers: { 'Content-Type': 'text/event-stream' },
    }));
    configureApiTransport(transport);
    const handlers = {
      onStart: vi.fn(), onDelta: vi.fn(), onSources: vi.fn(), onDone: vi.fn(), onError: vi.fn(),
    };

    await api.sendResearchMessage('research-1', 'question', 'web', handlers);

    expect(handlers.onStart).toHaveBeenCalledWith(expect.objectContaining({ requested_mode: 'web' }));
    expect(handlers.onDelta).toHaveBeenCalledWith('A sourced answer');
    expect(handlers.onSources).toHaveBeenCalledWith(message.citations, 'web');
    expect(handlers.onDone).toHaveBeenCalledWith(message);
    expect(handlers.onError).not.toHaveBeenCalled();
    const [url, init] = transport.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/v1/research/sessions/research-1/messages');
    expect(JSON.parse(String(init.body))).toEqual({ content: 'question', mode: 'web' });
  });

  it('rejects a research stream that closes without done or error', async () => {
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('event: delta\ndata: {"text":"partial"}\n\n'));
        controller.close();
      },
    });
    configureApiTransport(vi.fn().mockResolvedValue(new Response(stream, {
      status: 200, headers: { 'Content-Type': 'text/event-stream' },
    })));
    const handlers = {
      onStart: vi.fn(), onDelta: vi.fn(), onSources: vi.fn(), onDone: vi.fn(), onError: vi.fn(),
    };

    await expect(api.sendResearchMessage('research-1', 'question', 'smart', handlers)).rejects.toMatchObject({
      code: 'RESEARCH_STREAM_INTERRUPTED', retryable: true,
    });
    expect(handlers.onDelta).toHaveBeenCalledWith('partial');
  });
});
