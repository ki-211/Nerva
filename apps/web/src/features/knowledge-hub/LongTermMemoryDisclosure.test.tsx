import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../../lib/api';
import type { LongTermMemory } from '../../lib/types';
import { LongTermMemoryDisclosure } from './LongTermMemoryDisclosure';

const memory: LongTermMemory = {
  id: 'ltm-1', kind: 'project', subject: 'Nerva 项目', content: '用户负责产品设计',
  status: 'candidate', confidence: .9, origin: 'ai_inferred', reason: '用户明确陈述',
  source_channel: 'chat', source_session_id: 'chat-1', source_message_id: 'msg-1',
  conflict_memory_id: null, embedding_status: 'ready', use_count: 0, last_used_at: null,
  created_at: '2026-08-11T00:00:00Z', updated_at: '2026-08-11T00:00:00Z',
};

afterEach(() => vi.restoreAllMocks());

describe('LongTermMemoryDisclosure', () => {
  it('reacts to streamed context and candidate props', async () => {
    vi.spyOn(api, 'updateLongTermMemory').mockResolvedValue({ ...memory, status: 'active' });
    const view = render(<LongTermMemoryDisclosure memoryRefs={[]} />);
    view.rerender(<LongTermMemoryDisclosure memoryRefs={['ltm-1']} context={[{ ...memory, status: 'active' }]} candidates={[memory]} />);

    expect(await screen.findByText('发现待确认的长期记忆')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /使用了 1 条长期记忆/ }));
    expect((await screen.findAllByText('用户负责产品设计')).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole('button', { name: '确认记住' }));
    await waitFor(() => expect(api.updateLongTermMemory).toHaveBeenCalledWith('ltm-1', { status: 'active' }));
  });
});
