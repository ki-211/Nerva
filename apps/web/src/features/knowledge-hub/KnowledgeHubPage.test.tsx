import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../../lib/api';
import type { Document, KnowledgeEvent, LongTermMemory, Memory } from '../../lib/types';
import { KnowledgeHubPage } from './KnowledgeHubPage';

const memories: Memory[] = [
  {
    id: 'mem-active', kind: 'style', content: '使用简洁回答', scope: 'global', scope_ref: null,
    status: 'active', confidence: 1, origin: 'user_explicit', use_count: 4,
    last_used_at: null, created_at: '2026-08-09T00:00:00Z', updated_at: '2026-08-09T00:00:00Z',
  },
  {
    id: 'mem-candidate', kind: 'naming', content: '标题使用名词短语', scope: 'global', scope_ref: null,
    status: 'candidate', confidence: .8, origin: 'ai_inferred', use_count: 0,
    last_used_at: null, created_at: '2026-08-10T00:00:00Z', updated_at: '2026-08-10T00:00:00Z',
  },
];

const documents: Document[] = [
  { id: 'doc-ready', title: 'Ready', markdown: '# Ready', version: 1, visibility: 'private', index_status: 'ready', created_at: '2026-08-09T00:00:00Z', updated_at: '2026-08-09T00:00:00Z' },
  { id: 'doc-failed', title: 'Failed', markdown: '# Failed', version: 1, visibility: 'private', index_status: 'failed', created_at: '2026-08-09T00:00:00Z', updated_at: '2026-08-09T00:00:00Z' },
];

const events: KnowledgeEvent[] = [{
  id: 'evt-1', change_set_id: 'chg-1', created_at: new Date().toISOString(),
  title: '知识更新', summary: '接受两项变更', affected_documents: ['doc-ready'],
  accepted_count: 2, rejected_count: 0, origin: 'ai_ingestion',
}];

const longTermMemories: LongTermMemory[] = [
  {
    id: 'ltm-project', kind: 'project', subject: 'Nerva 项目', content: '用户负责 Nerva 产品设计',
    status: 'active', confidence: 1, origin: 'manual', reason: null, source_channel: 'manual',
    source_session_id: null, source_message_id: null, conflict_memory_id: null,
    embedding_status: 'ready', use_count: 3, last_used_at: null,
    created_at: '2026-08-09T00:00:00Z', updated_at: '2026-08-09T00:00:00Z',
  },
  {
    id: 'ltm-person', kind: 'person', subject: '用户角色', content: '用户是产品经理',
    status: 'candidate', confidence: .9, origin: 'ai_inferred', reason: '用户明确陈述职业',
    source_channel: 'chat', source_session_id: 'chat-1', source_message_id: 'msg-1',
    conflict_memory_id: null, embedding_status: 'ready', use_count: 0, last_used_at: null,
    created_at: '2026-08-10T00:00:00Z', updated_at: '2026-08-10T00:00:00Z',
  },
];

function prepareApi() {
  vi.spyOn(api, 'knowledgeHubSettings').mockResolvedValue({
    personalization_enabled: true, auto_learning_enabled: true, long_term_memory_enabled: true,
  });
  vi.spyOn(api, 'memories').mockResolvedValue(memories);
  vi.spyOn(api, 'longTermMemories').mockResolvedValue([]);
  vi.spyOn(api, 'longTermMemoryEvents').mockResolvedValue([]);
}

afterEach(() => vi.restoreAllMocks());

describe('KnowledgeHubPage', () => {
  it('loads real overview, trend, index and preference data', async () => {
    prepareApi();
    render(<KnowledgeHubPage documents={documents} events={events} onOpenLibrary={vi.fn()} />);

    expect(await screen.findByRole('heading', { name: '知识中枢' })).toBeInTheDocument();
    expect(screen.getByText('使用简洁回答')).toBeInTheDocument();
    expect(screen.getByText('发现 1 条待确认偏好')).toBeInTheDocument();
    expect(screen.getByRole('img')).toHaveAccessibleName(/最近 30 天有 1 次知识变更，共接受 2 项变更/);
    expect(screen.getByLabelText('就绪 1')).toBeInTheDocument();
    expect(screen.getByLabelText('失败 1')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '7 天' }));
    expect(screen.getByRole('img')).toHaveAccessibleName(/最近 7 天有 1 次知识变更/);
  });

  it('persists independent switches and rolls back failed updates', async () => {
    prepareApi();
    const update = vi.spyOn(api, 'updateKnowledgeHubSettings')
      .mockResolvedValueOnce({ personalization_enabled: false, auto_learning_enabled: true, long_term_memory_enabled: true })
      .mockRejectedValueOnce(new Error('设置暂时无法保存'));
    render(<KnowledgeHubPage documents={[]} events={[]} onOpenLibrary={vi.fn()} />);

    const personalization = await screen.findByRole('switch', { name: '个性化协作' });
    fireEvent.click(personalization);
    await waitFor(() => expect(personalization).toHaveAttribute('aria-checked', 'false'));
    expect(update).toHaveBeenNthCalledWith(1, { personalization_enabled: false });

    const learning = screen.getByRole('switch', { name: '自动学习' });
    fireEvent.click(learning);
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('设置暂时无法保存'));
    expect(learning).toHaveAttribute('aria-checked', 'true');
    expect(update).toHaveBeenNthCalledWith(2, { auto_learning_enabled: false });
  });

  it('confirms candidate preferences, opens the library and exports a knowledge package', async () => {
    prepareApi();
    const confirmed = { ...memories[1], status: 'active' as const };
    vi.spyOn(api, 'updateMemory').mockResolvedValue(confirmed);
    const exportPackage = vi.spyOn(api, 'exportKnowledgePackage').mockResolvedValue();
    const openLibrary = vi.fn();
    render(<KnowledgeHubPage documents={documents} events={[]} onOpenLibrary={openLibrary} />);

    fireEvent.click(await screen.findByRole('button', { name: '确认启用' }));
    await waitFor(() => expect(api.updateMemory).toHaveBeenCalledWith('mem-candidate', { status: 'active' }));
    expect(await screen.findByText('偏好已确认并开始生效')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /前往知识库/ }));
    expect(openLibrary).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: '导出全部知识' }));
    await waitFor(() => expect(exportPackage).toHaveBeenCalledWith('library'));
  });

  it('manages long-term memories independently from collaboration preferences', async () => {
    prepareApi();
    vi.mocked(api.longTermMemories).mockResolvedValue(longTermMemories);
    vi.spyOn(api, 'updateLongTermMemory').mockResolvedValue({ ...longTermMemories[1], status: 'active' });
    render(<KnowledgeHubPage documents={[]} events={[]} onOpenLibrary={vi.fn()} onOpenMemorySource={vi.fn()} />);

    expect(await screen.findByText('Nerva 项目')).toBeInTheDocument();
    expect(screen.getByText('发现 1 条待确认长期记忆')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '确认记住' }));
    await waitFor(() => expect(api.updateLongTermMemory).toHaveBeenCalledWith('ltm-person', { status: 'active' }));
    expect(await screen.findByText('长期记忆已确认并开始召回')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '项目' }));
    expect(screen.getByText('用户负责 Nerva 产品设计')).toBeInTheDocument();
    expect(screen.queryByText('用户是产品经理')).not.toBeInTheDocument();
  });
});
