import React, { useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ApiError, api } from './api';
import type { ChangeItem, ChangeSet, Document, DocumentVersion, KnowledgeEvent } from './types';


function headingId(children: React.ReactNode) {
  return String(children).toLowerCase().trim().replace(/[^\p{L}\p{N}]+/gu, '-').replace(/^-|-$/g, '');
}


export function MarkdownView({ markdown }: { markdown: string }) {
  const heading = (Tag: 'h1' | 'h2' | 'h3') => ({ children }: { children?: React.ReactNode }) =>
    <Tag id={headingId(children)}>{children}</Tag>;
  return <div className="markdown-body">
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        h1: heading('h1'), h2: heading('h2'), h3: heading('h3'),
        a: ({ children, ...props }) => <a {...props} target="_blank" rel="noreferrer">{children}</a>,
      }}
    >{markdown}</ReactMarkdown>
  </div>;
}


type LibraryProps = {
  documents: Document[];
  selectedDocumentId: string | null;
  onSelect: (id: string) => void;
  onSaved: (document: Document) => Promise<void>;
  onDirtyChange: (dirty: boolean) => void;
};


function ExportMenu({
  label, disabled, busy, onPdf, onMarkdown, onAi,
}: {
  label: string; disabled: boolean; busy: boolean;
  onPdf: () => void; onMarkdown: () => void; onAi: () => void;
}) {
  return <details className={`export-menu ${disabled ? 'disabled' : ''}`}>
    <summary onClick={(event) => { if (disabled) event.preventDefault(); }}>{busy ? '正在导出…' : label}</summary>
    <div className="export-options">
      <button disabled={disabled || busy} onClick={onPdf}><b>PDF</b><span>打开打印排版页</span></button>
      <button disabled={disabled || busy} onClick={onMarkdown}><b>Markdown</b><span>保留可编辑原文</span></button>
      <button disabled={disabled || busy} onClick={onAi}><b>AI 知识包</b><span>结构化数据与来源链</span></button>
      {disabled && <small>请先保存或取消当前编辑</small>}
    </div>
  </details>;
}


export function LibraryView({ documents, selectedDocumentId, onSelect, onSaved, onDirtyChange }: LibraryProps) {
  const [query, setQuery] = useState('');
  const [versions, setVersions] = useState<DocumentVersion[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [shownVersion, setShownVersion] = useState<number | null>(null);
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState('');
  const [editMarkdown, setEditMarkdown] = useState('');
  const [editReason, setEditReason] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [exporting, setExporting] = useState('');
  const [exportError, setExportError] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const document = documents.find((item) => item.id === selectedDocumentId) || null;
  const filtered = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    if (!normalized) return documents;
    return documents.filter((item) => `${item.title}\n${item.markdown}`.toLocaleLowerCase().includes(normalized));
  }, [documents, query]);
  const historical = shownVersion == null ? null : versions.find((item) => item.version === shownVersion) || null;
  const displayed = historical || document;
  const dirty = Boolean(document && editing && (
    editTitle !== document.title || editMarkdown !== document.markdown || editReason.trim()
  ));

  useEffect(() => { onDirtyChange(dirty); }, [dirty, onDirtyChange]);
  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', beforeUnload);
    return () => window.removeEventListener('beforeunload', beforeUnload);
  }, [dirty]);
  useEffect(() => {
    setShownVersion(null); setEditing(false); setError('');
    if (!document) { setVersions([]); return; }
    setHistoryLoading(true);
    api.documentVersions(document.id).then(setVersions).catch((reason) => {
      setError(reason instanceof Error ? reason.message : '版本历史加载失败');
    }).finally(() => setHistoryLoading(false));
  }, [document?.id, document?.version]);

  const beginEdit = () => {
    if (!document) return;
    setShownVersion(null); setEditing(true); setEditTitle(document.title);
    setEditMarkdown(document.markdown); setEditReason(''); setError('');
  };
  const cancelEdit = () => {
    if (dirty && !window.confirm('放弃尚未保存的修改吗？')) return;
    setEditing(false); setError(''); onDirtyChange(false);
  };
  const save = async () => {
    if (!document || !editTitle.trim() || !editMarkdown.trim()) return;
    setSaving(true); setError('');
    try {
      const updated = await api.updateDocument(document.id, {
        title: editTitle.trim(), markdown: editMarkdown.trim(), base_version: document.version,
        ...(editReason.trim() ? { reason: editReason.trim() } : {}),
      });
      setEditing(false); setShownVersion(null); onDirtyChange(false);
      await onSaved(updated);
      setVersions(await api.documentVersions(updated.id));
    } catch (reason) {
      if (reason instanceof ApiError && reason.code === 'DOCUMENT_VERSION_CONFLICT') {
        setError(`保存冲突：服务器已是 v${reason.currentVersion ?? '最新'}。你的草稿仍在，请复制后重新载入。`);
      } else {
        setError(reason instanceof Error ? reason.message : '保存失败');
      }
    } finally { setSaving(false); }
  };
  const insertMarkup = (prefix: string, suffix = '', placeholder = '文字') => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    const start = textarea.selectionStart; const end = textarea.selectionEnd;
    const selected = editMarkdown.slice(start, end) || placeholder;
    const next = editMarkdown.slice(0, start) + prefix + selected + suffix + editMarkdown.slice(end);
    setEditMarkdown(next);
    requestAnimationFrame(() => {
      textarea.focus(); textarea.setSelectionRange(start + prefix.length, start + prefix.length + selected.length);
    });
  };
  const outline = useMemo(() => {
    if (!displayed) return [];
    return displayed.markdown.split('\n').flatMap((line) => {
      const match = /^(#{1,3})\s+(.+)$/.exec(line.trim());
      return match ? [{ level: match[1].length, text: match[2], id: headingId(match[2]) }] : [];
    });
  }, [displayed]);

  const openPrint = (scope: 'library' | 'document', id?: string, selectedVersion?: number) => {
    const params = new URLSearchParams({ scope });
    if (id) params.set('document_id', id);
    if (selectedVersion != null) params.set('version', String(selectedVersion));
    window.open(`/export/print?${params}`, '_blank', 'noopener,noreferrer');
  };
  const runExport = async (name: string, task: () => Promise<void>) => {
    setExporting(name); setExportError('');
    try { await task(); }
    catch (reason) { setExportError(reason instanceof Error ? reason.message : '导出失败'); }
    finally { setExporting(''); }
  };

  return <section className="library-layout">
    <aside className="document-list">
      <div className="library-export-bar"><b>正式知识</b><ExportMenu
        label="导出全部" disabled={editing} busy={exporting === 'library'}
        onPdf={() => openPrint('library')}
        onMarkdown={() => runExport('library', () => api.exportMarkdown('library'))}
        onAi={() => runExport('library', () => api.exportKnowledgePackage('library'))}
      /></div>
      {exportError && <div className="export-error">{exportError}</div>}
      <label className="library-search"><span>⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索标题或正文"/></label>
      <div className="document-count">{filtered.length} 篇知识文档</div>
      <div className="document-items">{filtered.map((item) => <button key={item.id} className={item.id === document?.id ? 'active' : ''} onClick={() => onSelect(item.id)}>
        <b>{item.title}</b><small><span>v{item.version}</span>{new Date(item.updated_at).toLocaleDateString('zh-CN')}</small>
      </button>)}</div>
      {filtered.length === 0 && <p className="no-results">没有匹配的文档</p>}
    </aside>

    {!displayed ? <div className="reader-placeholder"><span>▤</span><h2>{documents.length ? '选择一篇文档开始阅读' : '还没有正式知识'}</h2><p>{documents.length ? '这里展示的是人与 AI 共用的正式知识。' : '先接受一份变更草案，再回来导出知识库。'}</p></div> : <article className="document-reader">
      <div className="reader-main">
        {editing && document ? <>
          <div className="reader-toolbar-row"><div><span className="reader-label">编辑最新版本</span><h2>修改文档</h2></div><div className="reader-actions"><ExportMenu label="导出" disabled busy={Boolean(exporting)} onPdf={() => {}} onMarkdown={() => {}} onAi={() => {}}/><button className="secondary" onClick={cancelEdit}>取消</button><button disabled={saving || !dirty || !editTitle.trim() || !editMarkdown.trim()} onClick={save}>{saving ? '保存中…' : '保存为新版本'}</button></div></div>
          {error && <div className="inline-error">{error}</div>}
          <input className="title-editor" value={editTitle} maxLength={160} onChange={(event) => setEditTitle(event.target.value)} aria-label="文档标题"/>
          <div className="format-toolbar" aria-label="Markdown 格式工具栏">
            <button onClick={() => insertMarkup('## ', '', '小节标题')}>H2</button><button onClick={() => insertMarkup('**', '**')}>粗体</button>
            <button onClick={() => insertMarkup('- ', '', '列表项')}>列表</button><button onClick={() => insertMarkup('> ', '', '引用')}>引用</button>
            <button onClick={() => insertMarkup('`', '`', '代码')}>代码</button><button onClick={() => insertMarkup('[', '](https://)', '链接文字')}>链接</button>
          </div>
          <div className="editor-split"><textarea ref={textareaRef} value={editMarkdown} onChange={(event) => setEditMarkdown(event.target.value)} aria-label="Markdown 正文"/><div className="live-preview"><span>实时预览</span><MarkdownView markdown={editMarkdown}/></div></div>
          <label className="edit-reason">变更说明（选填）<input value={editReason} maxLength={300} onChange={(event) => setEditReason(event.target.value)} placeholder="例如：补充产品定义并修正标题"/></label>
        </> : <>
          <div className="reader-toolbar-row"><div><span className="reader-label">{historical ? `历史版本 v${historical.version}` : `当前版本 v${document?.version}`}</span><h1>{displayed.title}</h1><p>{historical ? historical.reason : `更新于 ${new Date(document!.updated_at).toLocaleString('zh-CN')}`}</p></div><div className="reader-actions"><ExportMenu
            label="导出当前文档" disabled={false} busy={exporting === 'document'}
            onPdf={() => openPrint('document', document!.id, displayed.version)}
            onMarkdown={() => runExport('document', () => api.exportMarkdown('document', document!.id, displayed.version))}
            onAi={() => runExport('document', () => api.exportKnowledgePackage('document', document!.id))}
          />{historical && <button className="secondary" onClick={() => setShownVersion(null)}>返回最新版</button>}{!historical && <button onClick={beginEdit}>编辑文档</button>}</div></div>
          {error && <div className="inline-error">{error}</div>}
          <MarkdownView markdown={displayed.markdown}/>
        </>}
      </div>
      <aside className="reader-sidebar">
        {outline.length > 0 && <div className="outline"><b>本页目录</b>{outline.map((item, index) => <a key={`${item.id}-${index}`} className={`level-${item.level}`} href={`#${item.id}`}>{item.text}</a>)}</div>}
        <div className="version-list"><b>版本历史</b>{historyLoading ? <small>加载中…</small> : versions.map((item) => <button key={item.version} className={(shownVersion ?? document?.version) === item.version ? 'active' : ''} onClick={() => { setEditing(false); setShownVersion(item.version === document?.version ? null : item.version); }}>
          <span>v{item.version}</span><div><b>{item.reason}</b><small>{new Date(item.created_at).toLocaleString('zh-CN')}</small></div>
        </button>)}</div>
      </aside>
    </article>}
  </section>;
}


type DiffLine = { type: 'same' | 'add' | 'remove'; text: string };


function lineDiff(before: string, after: string): DiffLine[] {
  const oldLines = before.split('\n'); const newLines = after.split('\n');
  if (oldLines.length * newLines.length > 40_000) {
    let prefix = 0; let suffix = 0;
    while (oldLines[prefix] === newLines[prefix] && prefix < oldLines.length && prefix < newLines.length) prefix += 1;
    while (oldLines[oldLines.length - 1 - suffix] === newLines[newLines.length - 1 - suffix] && suffix < oldLines.length - prefix && suffix < newLines.length - prefix) suffix += 1;
    return [
      ...oldLines.slice(0, prefix).map((text) => ({ type: 'same' as const, text })),
      ...oldLines.slice(prefix, oldLines.length - suffix).map((text) => ({ type: 'remove' as const, text })),
      ...newLines.slice(prefix, newLines.length - suffix).map((text) => ({ type: 'add' as const, text })),
      ...oldLines.slice(oldLines.length - suffix).map((text) => ({ type: 'same' as const, text })),
    ];
  }
  const table = Array.from({ length: oldLines.length + 1 }, () => Array<number>(newLines.length + 1).fill(0));
  for (let i = oldLines.length - 1; i >= 0; i -= 1) for (let j = newLines.length - 1; j >= 0; j -= 1) {
    table[i][j] = oldLines[i] === newLines[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
  }
  const result: DiffLine[] = []; let i = 0; let j = 0;
  while (i < oldLines.length || j < newLines.length) {
    if (i < oldLines.length && j < newLines.length && oldLines[i] === newLines[j]) { result.push({ type: 'same', text: oldLines[i] }); i += 1; j += 1; }
    else if (j < newLines.length && (i === oldLines.length || table[i][j + 1] >= table[i + 1][j])) { result.push({ type: 'add', text: newLines[j] }); j += 1; }
    else { result.push({ type: 'remove', text: oldLines[i] }); i += 1; }
  }
  return result;
}


const operationName: Record<ChangeItem['operation'], string> = {
  CREATE_DOCUMENT: '新建文档', ADD_BLOCK: '添加知识块', UPDATE_BLOCK: '更新知识块',
  MOVE_BLOCK: '移动知识块', ADD_RELATION: '添加关联', MARK_DUPLICATE: '标记重复',
  REPORT_CONFLICT: '报告冲突', UPDATE_DOCUMENT: '人工编辑文档',
};


function ChangeDetail({ item, onOpenDocument }: { item: ChangeItem; onOpenDocument: (id: string) => void }) {
  const isNoMutation = item.operation === 'MARK_DUPLICATE' || item.operation === 'REPORT_CONFLICT';
  return <section className="change-detail">
    <div className="change-detail-head"><span className={`decision ${item.accepted ? 'accepted' : 'rejected'}`}>{item.accepted ? '已接受' : '已拒绝'}</span><span className="operation-name">{operationName[item.operation]}</span><span className="confidence">置信度 {Math.round(item.confidence * 100)}%</span></div>
    <h3>{item.target_document_id ? <button className="document-link" onClick={() => onOpenDocument(item.target_document_id!)}>{item.target_title} ↗</button> : item.target_title}</h3>
    {item.before_title && item.before_title !== item.target_title && <p className="title-change"><del>{item.before_title}</del><span>→</span><ins>{item.target_title}</ins></p>}
    <p className="change-reason">{item.reason}</p>
    {item.operation === 'UPDATE_DOCUMENT' && item.before != null ? <div className="diff-view">{lineDiff(item.before, item.after).map((line, index) => <div key={index} className={line.type}><span>{line.type === 'add' ? '+' : line.type === 'remove' ? '−' : ' '}</span><code>{line.text || ' '}</code></div>)}</div>
      : isNoMutation ? <div className="no-mutation">此项用于记录判断，没有修改正式文档正文。</div>
      : <div className="added-content"><span>{item.operation === 'CREATE_DOCUMENT' ? '新增文档内容' : '新增内容'}</span><MarkdownView markdown={item.after}/></div>}
    <details className="evidence"><summary>查看判断依据</summary><blockquote>{item.evidence}</blockquote></details>
  </section>;
}


type GrowthProps = {
  events: KnowledgeEvent[];
  selectedEventId: string | null;
  onOpen: (id: string) => void;
  onClose: () => void;
  onOpenDocument: (id: string) => void;
};


export function GrowthView({ events, selectedEventId, onOpen, onClose, onOpenDocument }: GrowthProps) {
  const [detail, setDetail] = useState<ChangeSet | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const event = events.find((item) => item.id === selectedEventId) || null;
  useEffect(() => {
    if (!event) { setDetail(null); setError(''); return; }
    setLoading(true); setError('');
    api.changeSet(event.change_set_id).then(setDetail).catch((reason) => {
      setError(reason instanceof Error ? reason.message : '详情加载失败');
    }).finally(() => setLoading(false));
  }, [event?.change_set_id]);
  useEffect(() => {
    if (!selectedEventId) return;
    const closeOnEscape = (keyboard: KeyboardEvent) => { if (keyboard.key === 'Escape') onClose(); };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [selectedEventId, onClose]);

  return <>
    <section className="timeline">{events.length === 0 ? <EmptyState text="当你接受第一份变更后，知识的成长过程会出现在这里。"/> : events.map((item) => <article key={item.id}>
      <div className="date">{new Date(item.created_at).toLocaleDateString('zh-CN')}</div>
      <button className="event-card" onClick={() => onOpen(item.id)}><span className="event-dot"/><small>{item.origin === 'manual_edit' ? '人工编辑' : 'AI 整理'}</small><h2>{item.title}</h2><p>{item.summary}</p><dl><dt>影响文档</dt><dd>{item.affected_documents.join('、') || '无'}</dd><dt>{item.origin === 'manual_edit' ? '人工修改' : 'AI 修改'}</dt><dd>接受 {item.accepted_count} 项 · 拒绝 {item.rejected_count} 项</dd></dl><span className="open-detail">查看详细变更 →</span></button>
    </article>)}</section>
    {selectedEventId && <div className="drawer-layer" role="presentation" onMouseDown={(mouse) => { if (mouse.currentTarget === mouse.target) onClose(); }}>
      <aside className="change-drawer" role="dialog" aria-modal="true" aria-label="成长日志详情">
        <div className="drawer-head"><div><span className="reader-label">{event?.origin === 'manual_edit' ? '人工编辑记录' : 'AI 知识整理记录'}</span><h2>{event?.title || '变更详情'}</h2>{event && <time>{new Date(event.created_at).toLocaleString('zh-CN')}</time>}</div><button className="drawer-close" onClick={onClose} aria-label="关闭">×</button></div>
        {loading && <div className="drawer-state">正在加载完整变更…</div>}
        {error && <div className="inline-error">{error}</div>}
        {detail && !loading && <div className="drawer-content"><div className="event-summary"><b>{detail.summary}</b><span>接受 {detail.items.filter((item) => item.accepted).length} 项 · 拒绝 {detail.items.filter((item) => item.accepted === false).length} 项</span></div>{detail.items.map((item) => <ChangeDetail key={item.id} item={item} onOpenDocument={onOpenDocument}/>)}
          {detail.source && <details className="source-detail"><summary>查看促成本次变更的原始输入</summary>{detail.source.title && <h3>{detail.source.title}</h3>}<pre>{detail.source.content}</pre></details>}
        </div>}
      </aside>
    </div>}
  </>;
}


export function EmptyState({ text }: { text: string }) {
  return <div className="empty"><span>✦</span><h2>知识正在等待生长</h2><p>{text}</p></div>;
}
