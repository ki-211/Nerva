import React, { FormEvent, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { ApiError, api } from './api';
import type { ChangeSet, Document, KnowledgeEvent, User } from './types';
import './styles.css';

type View = 'capture' | 'library' | 'growth';

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
  const [view, setView] = useState<View>('capture');
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [draft, setDraft] = useState<ChangeSet | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [events, setEvents] = useState<KnowledgeEvent[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const handleError = (e: unknown, fallback: string) => {
    if (e instanceof ApiError && e.status === 401) {
      onSignedOut(); navigate('/login', { replace: true, state: { from: location.pathname } }); return;
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
    setBusy(true); setError('');
    try {
      const result = await api.createIngestion(content, title);
      setDraft(result); setSelected(result.items.map((item) => item.id));
    } catch (e) { handleError(e, '生成失败'); }
    finally { setBusy(false); }
  };
  const apply = async () => {
    if (!draft) return;
    setBusy(true); setError('');
    try {
      await api.applyChangeSet(draft.id, selected);
      await refresh(); setDraft(null); setContent(''); setTitle(''); setView('growth');
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
      <button className="new" onClick={() => setView('capture')}>＋ 快速记录</button>
      <nav>
        <button className={view === 'capture' ? 'active' : ''} onClick={() => setView('capture')}>✦ 知识录入</button>
        <button className={view === 'library' ? 'active' : ''} onClick={() => setView('library')}>▤ 知识库 <em>{documents.length}</em></button>
        <button className={view === 'growth' ? 'active' : ''} onClick={() => setView('growth')}>↗ 成长日志 <em>{events.length}</em></button>
      </nav>
      <div className="account"><span>{user.display_name.slice(0, 2).toUpperCase()}</span><div><b>{user.display_name}</b><small>{user.email}</small></div><button disabled={busy} onClick={signOut}>退出</button></div>
      <div className="side-note"><i /> 本地开发模式<br/><span>PostgreSQL · AI 演示适配器</span></div>
    </aside>

    <main>
      <header><div><span className="eyebrow">NERVA · KNOWLEDGE GROWTH</span><h1>{view === 'capture' ? '让新输入，真正长进旧知识里' : view === 'library' ? '知识库' : '知识成长日志'}</h1></div><div className="status">● 系统就绪</div></header>
      {view === 'capture' && <section className="capture-layout">
        <div className="panel editor-panel"><div className="panel-title"><span>01</span><div><b>输入一条新资料</b><small>当前先实现文字，图片与 PDF 接口随后接入</small></div></div><input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="标题（可选）"/><textarea value={content} onChange={(e) => setContent(e.target.value)} placeholder="粘贴资料、笔记或灵感……"/><div className="editor-foot"><span>{content.length} 字</span><button disabled={busy || content.trim().length < 2} onClick={generate}>{busy ? '分析中…' : '生成变更草案 →'}</button></div></div>
        <div className="panel process-panel"><div className="panel-title"><span>02</span><div><b>知识整合流程</b><small>每一步都保留来源与版本</small></div></div>{['提取原始知识','召回相关旧文档','规划块级变更','等待你的确认'].map((item,index)=><div className="step" key={item}><i>{index+1}</i><div><b>{item}</b><small>{draft&&index<3?'已完成':index===3&&draft?'草案已就绪':'等待输入'}</small></div><strong className={draft?'done':''}>{draft?'✓':'—'}</strong></div>)}</div>
        {draft && <div className="panel draft-panel"><div className="draft-head"><div><span className="tag">AI 变更草案</span><h2>{draft.summary}</h2></div><span className="safe">尚未修改知识库</span></div>{draft.items.map((item)=><label className="change" key={item.id}><input type="checkbox" checked={selected.includes(item.id)} onChange={(e)=>setSelected(e.target.checked?[...selected,item.id]:selected.filter((id)=>id!==item.id))}/><div className="change-body"><div><span className={`operation ${item.operation.toLowerCase()}`}>{item.operation==='CREATE_DOCUMENT'?'新增文档':'自动合并'}</span><b>{item.target_title}</b><small>置信度 {Math.round(item.confidence*100)}%</small></div><p>{item.reason}</p><pre>{item.after}</pre><details><summary>查看依据</summary><blockquote>{item.evidence}</blockquote></details></div></label>)}<div className="draft-actions"><button className="secondary" onClick={()=>setDraft(null)}>放弃草案</button><button disabled={busy||selected.length===0} onClick={apply}>接受 {selected.length} 项变更</button></div></div>}
        {error && <div className="error">{error}</div>}
      </section>}
      {view === 'library' && <section className="cards">{documents.length===0?<Empty text="还没有正式知识，先接受一份变更草案。"/>:documents.map((doc)=><article className="doc-card" key={doc.id}><div><span>v{doc.version}</span><time>{new Date(doc.updated_at).toLocaleString('zh-CN')}</time></div><h2>{doc.title}</h2><pre>{doc.markdown}</pre></article>)}</section>}
      {view === 'growth' && <section className="timeline">{events.length===0?<Empty text="当你接受第一份变更后，知识的成长过程会出现在这里。"/>:events.map((event)=><article key={event.id}><div className="date">{new Date(event.created_at).toLocaleDateString('zh-CN')}</div><div className="event-card"><span className="event-dot"/><small>知识已更新</small><h2>{event.title}</h2><p>{event.summary}</p><dl><dt>影响文档</dt><dd>{event.affected_documents.join('、')||'无'}</dd><dt>AI 修改</dt><dd>接受 {event.accepted_count} 项 · 拒绝 {event.rejected_count} 项</dd></dl></div></article>)}</section>}
    </main>
  </div>;
}

function Empty({ text }: { text: string }) { return <div className="empty"><span>✦</span><h2>知识正在等待生长</h2><p>{text}</p></div>; }

createRoot(document.getElementById('root')!).render(<React.StrictMode><BrowserRouter><Root /></BrowserRouter></React.StrictMode>);
