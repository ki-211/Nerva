import { useEffect, useMemo, useState } from 'react';
import { api } from '../../lib/api';
import { adminApi } from '../../lib/adminApi';
import type { Document, User } from '../../lib/types';
import { MarkdownView } from './knowledgeViews';
import '../../styles/knowledge.css';

type Props = {
  user: User;
  documentId: string | null;
  onOpen: (id: string) => void;
  onCountChange?: (count: number) => void;
};

export function PublicLibraryPage({ user, documentId, onOpen, onCountChange }: Props) {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [query, setQuery] = useState('');
  const [editing, setEditing] = useState(false);
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState('');
  const [markdown, setMarkdown] = useState('');
  const [reason, setReason] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const selected = documents.find((item) => item.id === documentId) || null;
  const filtered = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    return normalized
      ? documents.filter((item) => `${item.title}\n${item.markdown}`.toLocaleLowerCase().includes(normalized))
      : documents;
  }, [documents, query]);

  const fail = (cause: unknown, fallback: string) => {
    setError(cause instanceof Error ? cause.message : fallback);
  };
  const refresh = async () => {
    const next = await api.publicDocuments();
    setDocuments(next);
    onCountChange?.(next.length);
    if (!documentId && next.length) onOpen(next[0].id);
  };

  useEffect(() => { refresh().catch((cause) => fail(cause, '大众知识库加载失败')); }, []);
  useEffect(() => {
    setEditing(false); setCreating(false); setError('');
  }, [documentId]);

  const beginEdit = () => {
    if (!selected) return;
    setTitle(selected.title); setMarkdown(selected.markdown); setReason('');
    setEditing(true); setCreating(false);
  };
  const beginCreate = () => {
    setTitle(''); setMarkdown('# 新文档\n\n'); setReason('');
    setCreating(true); setEditing(true);
  };
  const save = async () => {
    if (!title.trim() || !markdown.trim()) return;
    setBusy(true); setError('');
    try {
      const saved = creating
        ? await adminApi.createPublicDocument(title.trim(), markdown.trim())
        : await adminApi.updatePublicDocument(selected!.id, {
            title: title.trim(), markdown: markdown.trim(), base_version: selected!.version,
            ...(reason.trim() ? { reason: reason.trim() } : {}),
          });
      await refresh(); setEditing(false); setCreating(false); onOpen(saved.id);
    } catch (cause) { fail(cause, '保存公共文档失败'); }
    finally { setBusy(false); }
  };
  const unpublish = async () => {
    if (!selected || !window.confirm(`下架《${selected.title}》吗？历史版本会保留。`)) return;
    setBusy(true);
    try { await adminApi.unpublishPublicDocument(selected.id); await refresh(); onOpen(''); }
    catch (cause) { fail(cause, '下架公共文档失败'); }
    finally { setBusy(false); }
  };

  return <section className="library-layout public-library-page">
    <aside className="document-list">
      <div className="library-export-bar"><b>大众知识库</b>{user.role === 'admin' && <button onClick={beginCreate}>新建</button>}</div>
      <label className="library-search"><span>⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索公共文档" /></label>
      <div className="document-count">{filtered.length} 篇公开文档</div>
      <div className="document-items">{filtered.map((item) => <button key={item.id} className={item.id === selected?.id ? 'active' : ''} onClick={() => onOpen(item.id)}>
        <b>{item.title}</b><small><span>v{item.version}</span>{user.role === 'admin' && <span>{item.index_status === 'ready' ? '索引完成' : item.index_status === 'failed' ? '索引失败·关键词可用' : '索引处理中'}</span>}{new Date(item.updated_at).toLocaleDateString('zh-CN')}</small>
      </button>)}</div>
    </aside>
    {editing ? <article className="document-reader"><div className="reader-main">
      <div className="reader-toolbar-row"><div><span className="reader-label">{creating ? '创建公共文档' : '编辑公共文档'}</span><h2>{creating ? '新建文档' : selected?.title}</h2></div><div className="reader-actions"><button className="secondary" onClick={() => setEditing(false)}>取消</button><button disabled={busy || !title.trim() || !markdown.trim()} onClick={save}>{busy ? '保存中…' : '保存'}</button></div></div>
      {error && <div className="inline-error">{error}</div>}
      <input className="title-editor" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="标题" />
      <div className="editor-split"><textarea value={markdown} onChange={(event) => setMarkdown(event.target.value)} /><div className="live-preview"><span>实时预览</span><MarkdownView markdown={markdown} /></div></div>
      {!creating && <label className="edit-reason">变更说明（选填）<input value={reason} onChange={(event) => setReason(event.target.value)} /></label>}
    </div></article> : selected ? <article className="document-reader"><div className="reader-main">
      <div className="reader-toolbar-row"><div><span className="reader-label">大众知识库 · v{selected.version}</span><h1>{selected.title}</h1><p>更新于 {new Date(selected.updated_at).toLocaleString('zh-CN')}</p></div>{user.role === 'admin' && <div className="reader-actions"><button className="secondary" disabled={busy} onClick={unpublish}>下架</button><button onClick={beginEdit}>编辑文档</button></div>}</div>
      {error && <div className="inline-error">{error}</div>}<MarkdownView markdown={selected.markdown} />
    </div></article> : <div className="reader-placeholder"><span>◈</span><h2>大众知识库</h2><p>管理员发布的共享技术文档会显示在这里。</p>{error && <div className="inline-error">{error}</div>}</div>}
  </section>;
}
