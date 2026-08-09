import { describe, expect, it } from 'vitest';
import { actionForError, ApiError, categoryForStatus, fallbackMessage } from './errors';

describe('shared client errors', () => {
  it.each([
    [401, 'auth'], [403, 'permission'], [409, 'conflict'], [422, 'validation'],
    [429, 'rate-limit'], [503, 'server'], [0, 'network'],
  ])('maps status %s to %s', (status, category) => {
    expect(categoryForStatus(status as number)).toBe(category);
  });

  it('keeps the request id visible without exposing technical details', () => {
    const error = new ApiError('操作失败，请稍后重试', 500, 'INTERNAL_ERROR', undefined, true, undefined, false, 'req-123');
    expect(error.message).toContain('req-123');
    expect(error.message).not.toContain('Traceback');
  });

  it('provides desktop actions and messages', () => {
    expect(actionForError(401, false)).toBe('login');
    expect(actionForError(409, false)).toBe('refresh');
    expect(actionForError(422, false, true)).toBe('reupload');
    expect(fallbackMessage(0)).toContain('检查网络');
  });
});
