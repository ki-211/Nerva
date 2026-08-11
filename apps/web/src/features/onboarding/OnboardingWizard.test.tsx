import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api } from '../../lib/api';
import type { ChangeSet, User } from '../../lib/types';
import { OnboardingWizard } from './OnboardingWizard';

const user: User = { id: 'user-1', email: 'user@example.com', display_name: '测试用户', role: 'user' };

const draft: ChangeSet = {
  id: 'chg-1', source_id: 'src-1', origin: 'ai_ingestion', status: 'proposed',
  summary: '新建 1 篇文档，并向既有文档追加 2 处知识块。',
  supersedes_change_set_id: null, analysis_instruction: null,
  created_at: '2026-08-11T00:00:00Z', source: null,
  items: [
    { id: 'item-1', operation: 'CREATE_DOCUMENT', target_document_id: null, target_title: '检索策略', before_title: null, reason: '尚无相关文档', before: null, after: '混合检索为默认', evidence: '检索默认走混合模式', confidence: .9, accepted: null },
    { id: 'item-2', operation: 'ADD_BLOCK', target_document_id: 'doc-1', target_title: '运维计划', before_title: null, reason: '补充索引重建安排', before: null, after: '每天凌晨两点重建索引', evidence: '索引重建任务改为每天凌晨两点', confidence: .8, accepted: null },
    { id: 'item-3', operation: 'ADD_BLOCK', target_document_id: 'doc-2', target_title: '导出功能', before_title: null, reason: '补充迭代范围', before: null, after: '本迭代只支持 Markdown', evidence: '导出功能这个迭代只支持 Markdown', confidence: .8, accepted: null },
  ],
};

function networkFailure(code: string) {
  return new ApiError('服务暂时不可用', 0, code, undefined, true, undefined, false, undefined, 'network', 'retry');
}

beforeEach(() => window.localStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe('OnboardingWizard', () => {
  it('opens on the welcome step for a fresh install and moves on to the connection check', async () => {
    const health = vi.spyOn(api, 'health').mockResolvedValue({ status: 'ok', version: '0.1.0' });

    render(<OnboardingWizard initialStep="welcome" initialUser={null} onAuthenticated={vi.fn()} onFinish={vi.fn()} />);

    expect(screen.getByRole('heading', { name: '欢迎使用 Nerva' })).toBeInTheDocument();
    expect(health).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: '开始' }));

    expect(await screen.findByText(/服务已连接（服务端版本 0.1.0）/)).toBeInTheDocument();
    expect(health).toHaveBeenCalledTimes(1);
  });

  it('diagnoses a failed connection, then advances to login after a successful retry', async () => {
    const health = vi.spyOn(api, 'health')
      .mockRejectedValueOnce(networkFailure('DATABASE_MIGRATION_PENDING'))
      .mockResolvedValue({ status: 'ok', version: '0.2.0' });

    render(<OnboardingWizard initialStep="connect" initialUser={null} onAuthenticated={vi.fn()} onFinish={vi.fn()} />);

    expect(await screen.findByText('服务正在升级，通常一两分钟就好。请稍后重试。')).toBeInTheDocument();
    expect(screen.getByText(/错误编号：/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '导出诊断日志' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '重试' }));

    expect(await screen.findByRole('heading', { name: '登录你的知识空间' }, { timeout: 3_000 })).toBeInTheDocument();
    expect(health).toHaveBeenCalledTimes(2);
  });

  it('runs a real ingestion from the pre-filled sample and reports what the AI planned', async () => {
    const createIngestion = vi.spyOn(api, 'createIngestion').mockResolvedValue(draft);

    render(<OnboardingWizard initialStep="capture" initialUser={user} onAuthenticated={vi.fn()} onFinish={vi.fn()} />);

    const editor = screen.getByRole('textbox', { name: /示例内容/ }) as HTMLTextAreaElement;
    expect(editor.value).toContain('索引重建任务');

    fireEvent.click(screen.getByRole('button', { name: '交给 AI 整合' }));

    expect(await screen.findByRole('heading', { name: '这就是 Nerva 的工作方式' })).toBeInTheDocument();
    expect(screen.getByText(/已经拆成了/).textContent).toContain('3 个知识单元');
    expect(screen.getByText(draft.summary)).toBeInTheDocument();
    expect(screen.getByText('新建文档 · 1 处')).toBeInTheDocument();
    expect(screen.getByText('添加知识块 · 2 处')).toBeInTheDocument();
    expect(createIngestion).toHaveBeenCalledWith(expect.stringContaining('索引重建任务'), '周会记录：检索与索引调整');
  });

  it('records completion and hands the draft over when the user chooses to review it', async () => {
    vi.spyOn(api, 'createIngestion').mockResolvedValue(draft);
    const onFinish = vi.fn();

    render(<OnboardingWizard initialStep="capture" initialUser={user} onAuthenticated={vi.fn()} onFinish={onFinish} />);
    fireEvent.click(screen.getByRole('button', { name: '交给 AI 整合' }));
    fireEvent.click(await screen.findByRole('button', { name: '去审查并应用' }));

    expect(onFinish).toHaveBeenCalledWith('chg-1');
    expect(JSON.parse(window.localStorage.getItem('nerva.onboarding') || '{}')).toEqual({ users: ['user-1'] });
  });

  it('still lets the user leave when the ingestion fails', async () => {
    vi.spyOn(api, 'createIngestion').mockRejectedValue(networkFailure('API_TIMEOUT'));
    const onFinish = vi.fn();

    render(<OnboardingWizard initialStep="capture" initialUser={user} onAuthenticated={vi.fn()} onFinish={onFinish} />);
    fireEvent.click(screen.getByRole('button', { name: '交给 AI 整合' }));

    expect(await screen.findByText(/服务暂时不可用/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: '跳过' })).toBeEnabled());

    fireEvent.click(screen.getByRole('button', { name: '跳过' }));

    expect(onFinish).toHaveBeenCalledWith(null);
    expect(window.localStorage.getItem('nerva.onboarding')).toContain('user-1');
  });
});
