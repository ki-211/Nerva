import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { api } from './api';
import type { ChangeSet, Document, KnowledgeEvent } from './types';
import './styles.css';

type View = 'capture' | 'library' | 'growth';

function App() {
  const [view, setView] = useState<View>('capture');
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [draft, setDraft] = useState<ChangeSet | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [events, setEvents] = useState<KnowledgeEvent[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const refresh = async () => {
    const [docs, log] = await Promise.all([api.documents(), api.events()]);
    setDocuments(docs); setEvents(log);
  };
  useEffect(() => { refresh().catch(() => undefined); }, []);

  const generate = async () => {
    if (content.trim().length < 2) return;
    setBusy(true); setError('');
    try {
      const result = await api.createIngestion(content, title);
      setDraft(result); setSelected(result.items.map((item) => item.id));
    } catch (e) { setError(e instanceof Error ? e.message : '生成失败'); }
    finally { setBusy(false); }
  };

  const apply = async () => {
    if (!draft) return;
    setBusy(true); setError('');
    try {
      await api.applyChangeSet(draft.id, selected);
      await refresh(); setDraft(null); setContent(''); setTitle(''); setView('growth');
    } catch (e) { setError(e instanceof Error ? e.message : '提交失败'); }
    finally { setBusy(false); }
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
      <div className="side-note"><i /> 本地开发模式<br/><span>SQLite · AI 演示适配器</span></div>
    </aside>

    <main>
      <header><div><span className="eyebrow">NERVA · KNOWLEDGE GROWTH</span><h1>{view === 'capture' ? '让新输入，真正长进旧知识里' : view === 'library' ? '知识库' : '知识成长日志'}</h1></div><div className="status">● 系统就绪</div></header>

      {view === 'capture' && <section className="capture-layout">
        <div className="panel editor-panel">
          <div className="panel-title"><span>01</span><div><b>输入一条新资料</b><small>当前先实现文字，图片与 PDF 接口随后接入</small></div></div>
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="标题（可选）" />
          <textarea value={content} onChange={(e) => setContent(e.target.value)} placeholder="粘贴资料、笔记或灵感……" />
          <div className="editor-foot"><span>{content.length} 字</span><button disabled={busy || content.trim().length < 2} onClick={generate}>{busy ? '分析中…' : '生成变更草案 →'}</button></div>
        </div>

        <div className="panel process-panel">
          <div className="panel-title"><span>02</span><div><b>知识整合流程</b><small>每一步都保留来源与版本</small></div></div>
          {['提取原始知识', '召回相关旧文档', '规划块级变更', '等待你的确认'].map((item, index) => <div className="step" key={item}><i>{index + 1}</i><div><b>{item}</b><small>{draft && index < 3 ? '已完成' : index === 3 && draft ? '草案已就绪' : '等待输入'}</small></div><strong className={draft ? 'done' : ''}>{draft ? '✓' : '—'}</strong></div>)}
        </div>

        {draft && <div className="panel draft-panel">
          <div className="draft-head"><div><span className="tag">AI 变更草案</span><h2>{draft.summary}</h2></div><span className="safe">尚未修改知识库</span></div>
          {draft.items.map((item) => <label className="change" key={item.id}>
            <input type="checkbox" checked={selected.includes(item.id)} onChange={(e) => setSelected(e.target.checked ? [...selected, item.id] : selected.filter((id) => id !== item.id))}/>
            <div className="change-body"><div><span className={`operation ${item.operation.toLowerCase()}`}>{item.operation === 'CREATE_DOCUMENT' ? '新增文档' : '自动合并'}</span><b>{item.target_title}</b><small>置信度 {Math.round(item.confidence * 100)}%</small></div><p>{item.reason}</p><pre>{item.after}</pre><details><summary>查看依据</summary><blockquote>{item.evidence}</blockquote></details></div>
          </label>)}
          <div className="draft-actions"><button className="secondary" onClick={() => setDraft(null)}>放弃草案</button><button disabled={busy || selected.length === 0} onClick={apply}>接受 {selected.length} 项变更</button></div>
        </div>}
        {error && <div className="error">{error}。请确认 API 已在 8000 端口启动。</div>}
      </section>}

      {view === 'library' && <section className="cards">
        {documents.length === 0 ? <Empty text="还没有正式知识，先接受一份变更草案。"/> : documents.map((doc) => <article className="doc-card" key={doc.id}><div><span>v{doc.version}</span><time>{new Date(doc.updated_at).toLocaleString('zh-CN')}</time></div><h2>{doc.title}</h2><pre>{doc.markdown}</pre></article>)}
      </section>}

      {view === 'growth' && <section className="timeline">
        {events.length === 0 ? <Empty text="当你接受第一份变更后，知识的成长过程会出现在这里。"/> : events.map((event) => <article key={event.id}><div className="date">{new Date(event.created_at).toLocaleDateString('zh-CN')}</div><div className="event-card"><span className="event-dot"/><small>知识已更新</small><h2>{event.title}</h2><p>{event.summary}</p><dl><dt>影响文档</dt><dd>{event.affected_documents.join('、') || '无'}</dd><dt>AI 修改</dt><dd>接受 {event.accepted_count} 项 · 拒绝 {event.rejected_count} 项</dd></dl></div></article>)}
      </section>}
    </main>
  </div>;
}

function Empty({ text }: { text: string }) { return <div className="empty"><span>✦</span><h2>知识正在等待生长</h2><p>{text}</p></div>; }

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);

