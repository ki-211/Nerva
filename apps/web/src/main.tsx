import React, { FormEvent, useCallback, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { ApiError, api } from './api';
import { ImageCapture } from './imageCapture';
import { PrintExportPage } from './exportViews';
import type { ChangeSet, Document, KnowledgeEvent, SourceProcessing, User } from './types';
import { GrowthView, LibraryView } from './knowledgeViews';
import './styles.css';
import './knowledgeViews.css';

function Root() {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    api.me().then(setUser).catch(() => setUser(null)).finally(() => setReady(true));
  }, []);

  if (!ready) return <div className="auth-loading">正在恢复 Nerva 会话…</div>;

  return <Routes>
    <Route path="/login" element={user ? <Navigate to="/" replace /> : <AuthPage onAuthenticated={setUser} />} />
    <Route path="/register" element={<Navigate to="/login" replace />} />
    <Route path="/export/print" element={user ? <PrintExportPage /> : <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />} />
    <Route path="/*" element={user ? <KnowledgeApp user={user} onSignedOut={() => setUser(null)} /> : <Navigate to="/login" replace state={{ from: location.pathname }} />} />
  </Routes>;
}

function AuthPage({ onAuthenticated }: { onAuthenticated: (user: User) => void }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState('');
  const [verificationCode, setVerificationCode] = useState('');
  const [countdown, setCountdown] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (countdown <= 0) return;
    const timer = window.setTimeout(() => setCountdown(countdown - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [countdown]);

  const sendCode = async () => {
    if (!email || countdown > 0) return;
    setBusy(true); setError('');
    try {
      await api.sendVerificationCode(email);
      setCountdown(60);
    } catch (e) { setError(e instanceof Error ? e.message : '验证码发送失败'); }
    finally { setBusy(false); }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true); setError('');
    try {
      const user = await api.codeLogin(email, verificationCode);
      onAuthenticated(user);
      const from = (location.state as { from?: string } | null)?.from || '/';
      navigate(from, { replace: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : '认证失败');
    } finally { setBusy(false); }
  };

  return <main className="auth-page">
    <section className="auth-card">
      <div className="auth-brand"><span className="brand-mark">N</span><div><b>Nerva</b><small>让知识随着每次输入持续成长</small></div></div>
      <span className="eyebrow">PERSONAL KNOWLEDGE OS</span>
      <h1>邮箱验证码登录</h1>
      <p>无需注册和密码。首次验证邮箱后会自动创建你的独立知识空间。</p>
      <form onSubmit={submit}>
        <label>邮箱<input required type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" autoComplete="email" /></label>
        <label>邮箱验证码<div className="code-row"><input required inputMode="numeric" pattern="\d{6}" maxLength={6} value={verificationCode} onChange={(e) => setVerificationCode(e.target.value.replace(/\D/g, ''))} placeholder="6 位验证码" autoComplete="one-time-code"/><button type="button" disabled={busy || !email || countdown > 0} onClick={sendCode}>{countdown > 0 ? `${countdown} 秒` : '发送验证码'}</button></div></label>
        {error && <div className="auth-error">{error}</div>}
        <button disabled={busy || verificationCode.length !== 6}>{busy ? '请稍候…' : '登录 Nerva'}</button>
      </form>
      <div className="auth-switch">验证码 5 分钟有效 · 首次登录自动创建账号</div>
    </section>
  </main>;
}

function KnowledgeApp({ user, onSignedOut }: { user: User; onSignedOut: () => void }) {
  const navigate = useNavigate();
  const location = useLocation();
  const view = location.pathname.startsWith('/library') ? 'library' : location.pathname.startsWith('/growth') ? 'growth' : 'capture';
  const selectedDocumentId = view === 'library' ? decodeURIComponent(location.pathname.split('/')[2] || '') || null : null;
  const selectedEventId = view === 'growth' ? decodeURIComponent(location.pathname.split('/')[2] || '') || null : null;
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [captureMode, setCaptureMode] = useState<'text' | 'image'>('text');
  const [draft, setDraft] = useState<ChangeSet | null>(null);
  const [draftProcessing, setDraftProcessing] = useState<SourceProcessing | null>(null);
  const [reprocessOpen, setReprocessOpen] = useState(false);
  const [reprocessInstruction, setReprocessInstruction] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [events, setEvents] = useState<KnowledgeEvent[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [failedSourceId, setFailedSourceId] = useState<string | null>(null);
  const [libraryDirty, setLibraryDirty] = useState(false);

  const go = useCallback((path: string) => {
    if (libraryDirty && !window.confirm('当前文档还有未保存的修改，确定离开吗？')) return;
    setLibraryDirty(false); navigate(path);
  }, [libraryDirty, navigate]);

  const handleError = (e: unknown, fallback: string) => {
    if (e instanceof ApiError && e.status === 401) {
      onSignedOut(); navigate('/login', { replace: true, state: { from: location.pathname } }); return;
    }
    if (e instanceof ApiError && e.sourceId && e.retryable) {
      setFailedSourceId(e.sourceId);
    }
    setError(e instanceof Error ? e.message : fallback);
  };
  const refresh = async () => {
    const [docs, log] = await Promise.all([api.documents(), api.events()]);
    setDocuments(docs); setEvents(log);
  };
  useEffect(() => { refresh().catch((e) => handleError(e, '加载失败')); }, []);

  const generate = async () => {
    if (content.trim().length < 2) return;
    setBusy(true); setError(''); setFailedSourceId(null);
    try {
      const result = await api.createIngestion(content, title);
      setDraft(result); setDraftProcessing(null); setSelected(result.items.map((item) => item.id));
    } catch (e) { handleError(e, '生成失败'); }
    finally { setBusy(false); }
  };
  const waitForSource = async (initial: SourceProcessing) => {
    let current = initial;
    while (current.status === 'received' || current.status === 'processing') {
      setDraftProcessing(current);
      await new Promise((resolve) => window.setTimeout(resolve, 1500));
      current = await api.sourceProcessing(current.source_id);
    }
    setDraftProcessing(current);
    if (current.status === 'failed') {
      throw new ApiError(
        current.error?.message || '重新分析失败', 400, current.error?.code,
        current.source_id, current.error?.retryable,
        undefined, current.error?.requires_reupload,
      );
    }
    if (!current.change_set_id) throw new ApiError('处理完成但没有生成草案', 500);
    return api.changeSet(current.change_set_id);
  };
  const retry = async () => {
    if (!failedSourceId) return;
    setBusy(true); setError('');
    try {
      const result = await api.retrySource(failedSourceId);
      const completed = 'items' in result ? result : await waitForSource(result);
      setDraft(completed); setSelected(completed.items.map((item) => item.id));
      setFailedSourceId(null);
    } catch (e) { handleError(e, '重试失败'); }
    finally { setBusy(false); }
  };
  const reprocess = async () => {
    if (!draft?.source_id || busy) return;
    const previousProcessing = draftProcessing;
    setBusy(true); setError(''); setFailedSourceId(null);
    try {
      const initial = await api.reprocessSource(draft.source_id, reprocessInstruction);
      const replacement = await waitForSource(initial);
      setDraft(replacement);
      setSelected(replacement.items.map((item) => item.id));
      setReprocessInstruction(''); setReprocessOpen(false);
    } catch (e) {
      setDraftProcessing(previousProcessing);
      handleError(e, '重新分析失败，原草案仍然可用');
    }
    finally { setBusy(false); }
  };
  const apply = async () => {
    if (!draft) return;
    setBusy(true); setError('');
    try {
      await api.applyChangeSet(draft.id, selected);
      await refresh(); setDraft(null); setDraftProcessing(null); setContent(''); setTitle(''); navigate('/growth');
    } catch (e) { handleError(e, '提交失败'); }
    finally { setBusy(false); }
  };
  const signOut = async () => {
    setBusy(true);
    try { await api.logout(); } catch { /* A local logout still clears client auth. */ }
    finally { onSignedOut(); navigate('/login', { replace: true }); }
  };

  return <div className="app-shell">
    <aside>
      <div className="brand"><span className="brand-mark">N</span><div><b>Nerva</b><small>个人知识操作系统</small></div></div>
      <button className="new" onClick={() => go('/')}>＋ 快速记录</button>
      <nav>
        <button className={view === 'capture' ? 'active' : ''} onClick={() => go('/')}>✦ 知识录入</button>
        <button className={view === 'library' ? 'active' : ''} onClick={() => go('/library')}>▤ 知识库 <em>{documents.length}</em></button>
        <button className={view === 'growth' ? 'active' : ''} onClick={() => go('/growth')}>↗ 成长日志 <em>{events.length}</em></button>
      </nav>
      <div className="account"><span>{user.display_name.slice(0, 2).toUpperCase()}</span><div><b>{user.display_name}</b><small>{user.email}</small></div><button disabled={busy} onClick={signOut}>退出</button></div>
      <div className="side-note"><i /> 百炼 AI 已连接<br/><span>PostgreSQL · 两阶段知识整合</span></div>
    </aside>

    <main>
      <header><div><span className="eyebrow">NERVA · KNOWLEDGE GROWTH</span><h1>{view === 'capture' ? '让新输入，真正长进旧知识里' : view === 'library' ? '知识库' : '知识成长日志'}</h1></div><div className="status">● 系统就绪</div></header>
      {view === 'capture' && <section className="capture-layout">
        <div className="capture-mode-tabs"><button className={captureMode === 'text' ? 'active' : ''} onClick={() => setCaptureMode('text')}>文字输入</button><button className={captureMode === 'image' ? 'active' : ''} onClick={() => setCaptureMode('image')}>图片输入</button></div>
        {captureMode === 'text' ? <>
          <div className="panel editor-panel"><div className="panel-title"><span>01</span><div><b>输入一条新资料</b><small>文字将直接进入知识提取与整合</small></div></div><input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="标题（可选）"/><textarea value={content} onChange={(e) => setContent(e.target.value)} placeholder="粘贴资料、笔记或灵感……"/><div className="editor-foot"><span>{content.length} 字</span><button disabled={busy || content.trim().length < 2} onClick={generate}>{busy ? '分析中…' : '生成变更草案 →'}</button></div></div>
          <div className="panel process-panel"><div className="panel-title"><span>02</span><div><b>知识整合流程</b><small>每一步都保留来源与版本</small></div></div>{['提取原始知识','召回相关旧文档','规划块级变更','等待你的确认'].map((item,index)=><div className="step" key={item}><i>{index+1}</i><div><b>{item}</b><small>{draft&&index<3?'已完成':index===3&&draft?'草案已就绪':'等待输入'}</small></div><strong className={draft?'done':''}>{draft?'✓':'—'}</strong></div>)}</div>
        </> : <ImageCapture title={title} note={content} onTitleChange={setTitle} onNoteChange={setContent} onDraft={(result, processing) => { setDraft(result); setDraftProcessing(processing); setSelected(result.items.map((item) => item.id)); setError(''); }} onError={(cause) => handleError(cause, '图片处理失败')} />}
        {draft && <div className="panel draft-panel">
          <div className="draft-head"><div><span className="tag">AI 变更草案</span><h2>{draft.summary}</h2></div><span className="safe">尚未修改知识库</span></div>
          {draftProcessing && draftProcessing.total_inputs > 0 && <div className="coverage-summary">
            <b>已覆盖 {draftProcessing.covered_inputs} / {draftProcessing.total_inputs} 张图片</b>
            <span>知识提取 {draftProcessing.extraction_attempts} 次</span>
            <div>{draftProcessing.input_coverage.map((item) => <em key={item.input_index}>图片 {item.input_index} · {item.knowledge_unit_count} 个知识单元</em>)}</div>
          </div>}
          {draft.supersedes_change_set_id && <div className="superseded-note">已根据你的建议生成新草案，旧草案已保留为“已取代”。</div>}
          {draft.items.map((item)=><label className="change" key={item.id}><input type="checkbox" checked={selected.includes(item.id)} onChange={(e)=>setSelected(e.target.checked?[...selected,item.id]:selected.filter((id)=>id!==item.id))}/><div className="change-body"><div><span className={`operation ${item.operation.toLowerCase()}`}>{item.operation==='CREATE_DOCUMENT'?'新增文档':'自动合并'}</span><b>{item.target_title}</b><small>置信度 {Math.round(item.confidence*100)}%</small></div><p>{item.reason}</p><pre>{item.after}</pre><details><summary>查看依据</summary><blockquote>{item.evidence}</blockquote></details></div></label>)}
          {reprocessOpen && <div className="reprocess-box"><label>给 AI 的组织建议（不会作为事实来源）<textarea maxLength={2000} value={reprocessInstruction} onChange={(event) => setReprocessInstruction(event.target.value)} placeholder="例如：数据库内容单独成文档，重点整理事务隔离级别" /></label><small>{reprocessInstruction.length} / 2000</small><div><button className="secondary" disabled={busy} onClick={() => setReprocessOpen(false)}>取消</button><button disabled={busy} onClick={reprocess}>{busy ? '重新分析中…' : '开始重新分析'}</button></div></div>}
          <div className="draft-actions"><button className="secondary" disabled={busy} onClick={()=>setReprocessOpen(true)}>重新分析</button><button className="secondary" onClick={()=>{setDraft(null);setDraftProcessing(null);}}>放弃草案</button><button disabled={busy||selected.length===0} onClick={apply}>接受 {selected.length} 项变更</button></div>
        </div>}
        {error && <div className="error">{error}{failedSourceId && <button disabled={busy} onClick={retry}>{busy ? '重试中…' : '重试这条来源'}</button>}</div>}
      </section>}
      {view === 'library' && <LibraryView
        documents={documents}
        selectedDocumentId={selectedDocumentId}
        onSelect={(id) => go(`/library/${encodeURIComponent(id)}`)}
        onDirtyChange={setLibraryDirty}
        onSaved={async (updated) => {
          setDocuments((current) => current.map((item) => item.id === updated.id ? updated : item));
          setEvents(await api.events());
        }}
      />}
      {view === 'growth' && <GrowthView
        events={events}
        selectedEventId={selectedEventId}
        onOpen={(id) => navigate(`/growth/${encodeURIComponent(id)}`)}
        onClose={() => navigate('/growth')}
        onOpenDocument={(id) => navigate(`/library/${encodeURIComponent(id)}`)}
      />}
    </main>
  </div>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><BrowserRouter><Root /></BrowserRouter></React.StrictMode>);
