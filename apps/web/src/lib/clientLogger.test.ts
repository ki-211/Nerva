import { describe, expect, it } from 'vitest';
import { redact } from './clientLogger';

describe('client log redaction', () => {
  it('removes content, credentials, tokens and email addresses recursively', () => {
    const safe = redact({
      requestId: 'req-1', markdown: 'private body', password: 'secret',
      nested: { authorization: 'Bearer abc.def', note: 'contact user@example.com' },
      request: { data: 'raw body', query_string: 'q=private' },
    }) as Record<string, any>;
    expect(safe.requestId).toBe('req-1');
    expect(safe.markdown).toBe('[REDACTED]');
    expect(safe.password).toBe('[REDACTED]');
    expect(safe.nested.authorization).toBe('[REDACTED]');
    expect(safe.nested.note).toBe('contact [REDACTED_EMAIL]');
    expect(safe.request.data).toBe('[REDACTED]');
    expect(safe.request.query_string).toBe('[REDACTED]');
  });
});
