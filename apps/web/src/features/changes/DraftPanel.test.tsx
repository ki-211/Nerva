import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { ChangeSet } from '../../lib/types';
import { DraftPanel } from './DraftPanel';

const appliedDraft: ChangeSet = {
  id: 'chg_applied',
  source_id: 'src_research',
  origin: 'ai_ingestion',
  status: 'applied',
  summary: '已审批的研究结果',
  supersedes_change_set_id: null,
  analysis_instruction: null,
  created_at: '2026-08-09T00:00:00Z',
  source: { title: 'PostgreSQL', content: '研究内容' },
  items: [{
    id: 'item_1', operation: 'CREATE_DOCUMENT', target_document_id: 'doc_1',
    target_title: 'PostgreSQL', before_title: null, reason: '新增知识', before: null,
    after: '# PostgreSQL', evidence: '研究回答', confidence: 1, accepted: true,
  }],
};

describe('DraftPanel terminal state', () => {
  it('renders an applied change set as read-only and cannot apply it again', () => {
    const onApply = vi.fn();
    const onDiscard = vi.fn();
    render(<DraftPanel
      draft={appliedDraft}
      draftProcessing={null}
      selected={['item_1']}
      busy={false}
      reprocessOpen={false}
      reprocessInstruction=""
      onToggle={vi.fn()}
      onReprocessOpen={vi.fn()}
      onReprocessClose={vi.fn()}
      onReprocessInstructionChange={vi.fn()}
      onReprocess={vi.fn()}
      onDiscard={onDiscard}
      onApply={onApply}
    />);

    expect(screen.getByText('已全部入库')).toBeInTheDocument();
    expect(screen.queryByText(/接受 1 项变更/)).not.toBeInTheDocument();
    expect(screen.getByRole('checkbox')).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: '关闭入库结果' }));
    expect(onDiscard).toHaveBeenCalledOnce();
    expect(onApply).not.toHaveBeenCalled();
  });
});
