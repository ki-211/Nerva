import { useCallback, useEffect, useState } from 'react';
import { ApiError, api } from '../../lib/api';
import { exportDiagnosticLogs } from '../../lib/clientLogger';
import { markOnboardingComplete } from '../../lib/onboarding';
import type { ChangeItem, ChangeSet, User } from '../../lib/types';
import { EmailCodeForm } from '../auth/EmailCodeForm';
import '../auth/auth.css';
import './onboarding.css';

export type OnboardingStep = 'welcome' | 'connect' | 'login' | 'capture';

type Props = {
  initialStep: OnboardingStep;
  initialUser: User | null;
  onAuthenticated: (user: User) => void;
  /** Leaves the wizard for the real app, optionally handing over a change set to review. */
  onFinish: (pendingChangeSetId: string | null) => void;
};

const STEP_ORDER: OnboardingStep[] = ['welcome', 'connect', 'login', 'capture'];
const STEP_LABELS: Record<OnboardingStep, string> = {
  welcome: '欢迎', connect: '连接服务', login: '登录', capture: '首次录入',
};

const OPERATION_LABELS: Record<ChangeItem['operation'], string> = {
  CREATE_DOCUMENT: '新建文档', ADD_BLOCK: '添加知识块', UPDATE_BLOCK: '更新知识块',
  MOVE_BLOCK: '移动知识块', ADD_RELATION: '添加关联', MARK_DUPLICATE: '标记重复',
  REPORT_CONFLICT: '报告冲突', UPDATE_DOCUMENT: '人工编辑文档',
};

const HEALTH_DIAGNOSIS: Record<string, string> = {
  API_TIMEOUT: '服务响应超时。请检查网络连接或代理设置，然后重试。',
  API_UNAVAILABLE: '连不上 Nerva 服务。请确认这台电脑能正常上网，然后重试。',
  DATABASE_MIGRATION_PENDING: '服务正在升级，通常一两分钟就好。请稍后重试。',
  SERVICE_NOT_READY: '服务尚未就绪，请稍后重试。',
};

const SAMPLE_TITLE = '周会记录：检索与索引调整';
const SAMPLE_CONTENT = [
  '本周周会确认了三件事。',
  '第一，检索默认走混合模式，关键词检索只作为召回不足时的兜底方案。',
  '第二，索引重建任务从每小时改为每天凌晨两点执行，失败自动重试三次，仍失败则告警。',
  '第三，导出功能这个迭代只支持 Markdown，PDF 排到下个迭代，原因是排版规则还没定。',
].join('');

function StepIndicator({ current }: { current: OnboardingStep }) {
  const index = STEP_ORDER.indexOf(current);
  return <ol className="onboarding-steps">
    {STEP_ORDER.map((step, position) => <li
      key={step}
      className={position < index ? 'done' : position === index ? 'current' : ''}
      aria-current={position === index ? 'step' : undefined}
    >
      <span className="onboarding-step-dot">{position < index ? '✓' : position + 1}</span>
      {STEP_LABELS[step]}
    </li>)}
  </ol>;
}

type HealthState =
  | { phase: 'checking' }
  | { phase: 'ready'; version: string }
  | { phase: 'failed'; message: string; requestId?: string };

function ConnectStep({ onReady }: { onReady: () => void }) {
  const [state, setState] = useState<HealthState>({ phase: 'checking' });
  const [attempt, setAttempt] = useState(0);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setState({ phase: 'checking' });
    api.health().then((health) => {
      if (!cancelled) setState({ phase: 'ready', version: health.version });
    }).catch((cause: unknown) => {
      if (cancelled) return;
      const error = cause instanceof ApiError ? cause : null;
      setState({
        phase: 'failed',
        message: (error && HEALTH_DIAGNOSIS[error.code])
          || (cause instanceof Error ? cause.message : '无法确认服务状态，请稍后重试。'),
        requestId: error?.requestId,
      });
    });
    return () => { cancelled = true; };
  }, [attempt]);

  // Let the success line stay on screen briefly instead of flashing past.
  useEffect(() => {
    if (state.phase !== 'ready') return;
    const timer = window.setTimeout(onReady, 600);
    return () => window.clearTimeout(timer);
  }, [state.phase, onReady]);

  const exportLogs = async () => {
    setExporting(true);
    try {
      await exportDiagnosticLogs();
    } finally {
      setExporting(false);
    }
  };

  return <>
    <h1>正在连接 Nerva 服务</h1>
    {state.phase === 'checking' && <p role="status">正在检查服务状态…</p>}
    {state.phase === 'ready' && <p className="onboarding-ok" role="status">✓ 服务已连接（服务端版本 {state.version}）</p>}
    {state.phase === 'failed' && <>
      <div className="auth-error">{state.message}</div>
      {state.requestId && <p className="onboarding-hint">错误编号：{state.requestId}（联系支持时请提供）</p>}
      <div className="onboarding-actions">
        <button className="primary" onClick={() => setAttempt(attempt + 1)}>重试</button>
        <button disabled={exporting} onClick={exportLogs}>{exporting ? '导出中…' : '导出诊断日志'}</button>
      </div>
    </>}
  </>;
}

function CaptureStep({ onDone }: { onDone: (pendingChangeSetId: string | null) => void }) {
  const [content, setContent] = useState(SAMPLE_CONTENT);
  const [draft, setDraft] = useState<ChangeSet | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const generate = async () => {
    if (content.trim().length < 2) return;
    setBusy(true); setError('');
    try {
      setDraft(await api.createIngestion(content, SAMPLE_TITLE));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '生成失败，请重试');
    } finally { setBusy(false); }
  };

  if (draft) {
    const breakdown = draft.items.reduce<Record<string, number>>((totals, item) => {
      const label = OPERATION_LABELS[item.operation];
      return { ...totals, [label]: (totals[label] || 0) + 1 };
    }, {});
    return <>
      <h1>这就是 Nerva 的工作方式</h1>
      <p>刚才那段文字，AI 已经拆成了 <b>{draft.items.length}</b> 个知识单元，并规划好了写入方案。</p>
      <div className="onboarding-summary">
        <p>{draft.summary}</p>
        <ul>
          {Object.entries(breakdown).map(([label, count]) => <li key={label}>{label} · {count} 处</li>)}
        </ul>
      </div>
      <p className="onboarding-hint">每一条变更都要你确认后才会真正写进知识库 —— Nerva 不会背着你改东西。</p>
      <div className="onboarding-actions">
        <button className="primary" onClick={() => onDone(draft.id)}>去审查并应用</button>
        <button onClick={() => onDone(null)}>以后再说</button>
      </div>
    </>;
  }

  return <>
    <h1>试一次真正的录入</h1>
    <p>下面是一段示例文字，你可以直接改成自己的内容。提交后 AI 会提取知识单元，并规划该新建文档还是长进已有文档里。</p>
    <label className="onboarding-field">示例内容
      <textarea rows={8} value={content} onChange={(event) => setContent(event.target.value)} />
    </label>
    {error && <div className="auth-error">{error}</div>}
    <div className="onboarding-actions">
      <button className="primary" disabled={busy || content.trim().length < 2} onClick={generate}>
        {busy ? 'AI 正在整合…' : '交给 AI 整合'}
      </button>
      {/* Always available: an AI or network failure must never trap the user in the wizard. */}
      <button disabled={busy} onClick={() => onDone(null)}>跳过</button>
    </div>
  </>;
}

export function OnboardingWizard({ initialStep, initialUser, onAuthenticated, onFinish }: Props) {
  const [step, setStep] = useState<OnboardingStep>(initialStep);
  const [user, setUser] = useState<User | null>(initialUser);

  const finish = (pendingChangeSetId: string | null) => {
    if (user) markOnboardingComplete(user.id);
    onFinish(pendingChangeSetId);
  };

  const authenticated = (loggedIn: User) => {
    setUser(loggedIn);
    onAuthenticated(loggedIn);
    setStep('capture');
  };

  const connected = useCallback(() => setStep((current) => (current === 'connect' ? 'login' : current)), []);

  return <main className="auth-page onboarding-page">
    <section className="auth-card onboarding-card">
      <div className="auth-brand"><span className="brand-mark">N</span><div><b>Nerva</b><small>让知识随着每次输入持续成长</small></div></div>
      <StepIndicator current={step} />
      {step === 'welcome' && <>
        <span className="eyebrow">PERSONAL KNOWLEDGE OS</span>
        <h1>欢迎使用 Nerva</h1>
        <p>把随手记下的文字丢进来，Nerva 会用 AI 把它们拆成知识单元，再长进你已有的文档里，而不是堆成一堆越来越乱的笔记。</p>
        <p className="onboarding-hint">接下来三步：确认服务连接 → 登录 → 完成一次真实录入。大约一分钟。</p>
        <div className="onboarding-actions">
          <button className="primary" onClick={() => setStep('connect')}>开始</button>
        </div>
      </>}
      {step === 'connect' && <ConnectStep onReady={connected} />}
      {step === 'login' && <>
        <h1>登录你的知识空间</h1>
        <p>无需注册和密码。首次验证邮箱后会自动创建你的独立知识空间。</p>
        <EmailCodeForm onAuthenticated={authenticated} submitLabel="登录并继续" />
        <div className="auth-switch">验证码 5 分钟有效 · 首次登录自动创建账号</div>
      </>}
      {step === 'capture' && <CaptureStep onDone={finish} />}
    </section>
  </main>;
}
