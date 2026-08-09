import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ApiError, api } from '../../lib/api';
import { openExternalUrl } from '../../lib/desktopRuntime';
import type {
  ChangeSet, Document, KnowledgeEvent, ResearchBasis, ResearchMessage,
  ResearchMode, ResearchSession, ResearchStreamHandlers, SourceProcessing,
} from '../../lib/types';
import { DraftPanel } from '../changes/DraftPanel';
import './research.css';

type Props = {
  sessionId: string | null;
  onOpenSession: (id: string) => void;
  onRefresh: (docs: Document[], events: KnowledgeEvent[]) => void;
};

const MODE_LABELS: Record<ResearchMode, string> = {
  smart: '智能', web: '联网检索', ai: '仅 AI',
};

const INGESTION_STAGE_LABELS: Record<SourceProcessing['stage'], string> = {
  queued: '正在创建入库任务',
  ocr: '正在识别内容',
  extracting: '正在提取知识要点',
  coverage_repair: '正在补全知识要点',
  retrieving: '正在检索知识库并查重',
  planning: '正在生成合并与冲突建议',
  complete: '草案生成完成',
  failed: '草案生成失败',
};

function optimisticMessage(
  id: string, sessionId: string, role: 'user' | 'assistant', content: string,
  mode: ResearchMode | null,
): ResearchMessage {
  const now = new Date().toISOString();
  return {
    id, session_id: sessionId, role,
    status: role === 'user' ? 'completed' : 'generating', content,
    requested_mode: mode, basis: null, model: null, citations: [], error_code: null,
    ingestion_source_id: null, created_at: now, completed_at: role === 'user' ? now : null,
  };
}

export function ResearchPage({ sessionId, onOpenSession, onRefresh }: Props) {
  const [sessions, setSessions] = useState<ResearchSession[]>([]);
  const [messages, setMessages] = useState<ResearchMessage[]>([]);
  const [input, setInput] = useState('');
  const [mode, setMode] = useState<ResearchMode>('smart');
  const [loading, setLoading] = useState(true);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState('');
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [ingestingId, setIngestingId] = useState<string | null>(null);
  const [success, setSuccess] = useState('');
  const abortRef = useRef<AbortController | null>(null);
  const skipMessageLoadRef = useRef<string | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const draftRef = useRef<HTMLDivElement | null>(null);

  const [draft, setDraft] = useState<ChangeSet | null>(null);
  const [draftProcessing, setDraftProcessing] = useState<SourceProcessing | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [draftBusy, setDraftBusy] = useState(false);
  const [reprocessOpen, setReprocessOpen] = useState(false);
  const [reprocessInstruction, setReprocessInstruction] = useState('');
  const [failedSourceId, setFailedSourceId] = useState<string | null>(null);

  const fail = (cause: unknown, fallback: string) => {
    setError(cause instanceof Error ? cause.message : fallback);
  };

  const refreshSessions = async () => {
    const list = await api.researchSessions();
    setSessions(list);
    return list;
  };

  useEffect(() => {
    refreshSessions()
      .then((list) => { if (!sessionId && list.length) onOpenSession(list[0].id); })
      .catch((cause) => fail(cause, '研究列表加载失败'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!sessionId) { setMessages([]); return; }
    if (skipMessageLoadRef.current === sessionId) {
      skipMessageLoadRef.current = null;
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError('');
    api.researchMessages(sessionId)
      .then((loaded) => { if (!cancelled) setMessages(loaded); })
      .catch((cause) => { if (!cancelled) fail(cause, '研究消息加载失败'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [sessionId]);

  useEffect(() => () => abortRef.current?.abort(), []);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: streaming ? 'auto' : 'smooth' }); }, [messages, streaming]);
  useEffect(() => {
    if (!draft) return;
    const timer = window.setTimeout(() => {
      draftRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
    }, 0);
    return () => window.clearTimeout(timer);
  }, [draft?.id]);

  const createSession = async () => {
    try {
      const created = await api.createResearchSession();
      skipMessageLoadRef.current = created.id;
      setSessions((current) => [created, ...current]);
      setMessages([]);
      setDrawerOpen(false);
      onOpenSession(created.id);
      return created;
    } catch (cause) {
      fail(cause, '新建研究失败');
      return null;
    }
  };

  const renameSession = async (session: ResearchSession) => {
    const title = window.prompt('重命名研究', session.title)?.trim();
    if (!title || title === session.title) return;
    try {
      const updated = await api.updateResearchSession(session.id, title);
      setSessions((current) => current.map((item) => item.id === session.id ? updated : item));
    } catch (cause) { fail(cause, '重命名失败'); }
  };

  const deleteSession = async (session: ResearchSession) => {
    if (!window.confirm(`删除研究“${session.title}”及全部消息吗？已入库的知识不会删除。`)) return;
    try {
      await api.deleteResearchSession(session.id);
      const next = sessions.filter((item) => item.id !== session.id);
      setSessions(next);
      if (session.id === sessionId) {
        setMessages([]);
        onOpenSession(next[0]?.id || '');
      }
    } catch (cause) { fail(cause, '删除研究失败'); }
  };

  const handlers = (
    assistantKey: { current: string },
    optimistic?: { userKey: string; sessionId: string; content: string; mode: ResearchMode },
  ): ResearchStreamHandlers => ({
    onStart: ({ assistant_message_id, user_message_id, requested_mode }) => {
      const previousAssistant = assistantKey.current;
      assistantKey.current = assistant_message_id;
      setMessages((current) => {
        const next = current.map((message) => {
          if (message.id === previousAssistant) return { ...message, id: assistant_message_id, requested_mode };
          if (optimistic && message.id === optimistic.userKey) return { ...message, id: user_message_id };
          return message;
        });
        return next;
      });
    },
    onDelta: (text) => setMessages((current) => current.map((message) =>
      message.id === assistantKey.current ? { ...message, content: message.content + text } : message
    )),
    onSources: (citations, basis) => setMessages((current) => current.map((message) =>
      message.id === assistantKey.current ? { ...message, citations, basis } : message
    )),
    onDone: (message) => {
      setMessages((current) => current.map((item) => item.id === assistantKey.current ? message : item));
      refreshSessions().catch(() => undefined);
    },
    onError: (streamError) => {
      setError(streamError.message);
      setMessages((current) => current.map((message) => message.id === assistantKey.current
        ? { ...message, status: 'failed', error_code: streamError.code } : message));
    },
  });

  const send = async () => {
    const content = input.trim();
    if (!content || streaming || (sessionId !== null && loading)) return;
    let activeSessionId = sessionId;
    if (!activeSessionId) {
      const created = await createSession();
      if (!created) return;
      activeSessionId = created.id;
    }
    const stamp = Date.now();
    const userKey = `tmp-research-user-${stamp}`;
    const assistantKey = { current: `tmp-research-assistant-${stamp}` };
    setMessages((current) => [
      ...current,
      optimisticMessage(userKey, activeSessionId!, 'user', content, null),
      optimisticMessage(assistantKey.current, activeSessionId!, 'assistant', '', mode),
    ]);
    setInput(''); setError(''); setSuccess(''); setStreaming(true);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await api.sendResearchMessage(
        activeSessionId, content, mode,
        handlers(assistantKey, { userKey, sessionId: activeSessionId, content, mode }),
        controller.signal,
      );
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === 'AbortError') {
        setMessages((current) => current.map((message) => message.id === assistantKey.current
          ? { ...message, status: 'cancelled', error_code: 'RESEARCH_CANCELLED' } : message));
      } else {
        fail(cause, '发送研究问题失败');
      }
    } finally { abortRef.current = null; setStreaming(false); }
  };

  const retry = async (message: ResearchMessage, override?: ResearchMode) => {
    if (streaming) return;
    const assistantKey = { current: message.id };
    setMessages((current) => current.map((item) => item.id === message.id
      ? { ...item, status: 'generating', content: '', citations: [], basis: null, error_code: null,
        requested_mode: override || item.requested_mode }
      : item));
    setStreaming(true); setError('');
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await api.retryResearchMessage(message.id, override, handlers(assistantKey), controller.signal);
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === 'AbortError') {
        setMessages((current) => current.map((item) => item.id === assistantKey.current
          ? { ...item, status: 'cancelled', error_code: 'RESEARCH_CANCELLED' } : item));
      } else fail(cause, '重试失败');
    } finally { abortRef.current = null; setStreaming(false); }
  };

  const waitForSource = async (initial: SourceProcessing): Promise<ChangeSet> => {
    let current = initial;
    const deadline = Date.now() + 120_000;
    while (current.status === 'received' || current.status === 'processing') {
      setDraftProcessing(current);
      if (Date.now() >= deadline) {
        throw new ApiError(
          '草案生成时间较长，请稍后再次点击“查看/恢复入库草案”', 408,
          'SOURCE_PROCESSING_TIMEOUT', current.source_id,
        );
      }
      await new Promise((resolve) => window.setTimeout(resolve, 1200));
      current = await api.sourceProcessing(current.source_id);
    }
    setDraftProcessing(current);
    if (current.status === 'failed') {
      throw new ApiError(
        current.error?.message || '入库草案生成失败', 400, current.error?.code,
        current.source_id, current.error?.retryable, undefined,
        current.error?.requires_reupload, current.source_id,
      );
    }
    if (!current.change_set_id) throw new ApiError('处理完成但没有生成草案', 500, 'CHANGE_SET_MISSING');
    return api.changeSet(current.change_set_id);
  };

  const createDraft = async (message: ResearchMessage) => {
    if (message.status !== 'completed' || ingestingId) return;
    setIngestingId(message.id); setError(''); setSuccess(''); setFailedSourceId(null);
    setDraft(null); setDraftProcessing(null); setSelected([]);
    setReprocessOpen(false); setReprocessInstruction('');
    try {
      const initial = await api.createResearchIngestion(message.id);
      setMessages((current) => current.map((item) => item.id === message.id
        ? { ...item, ingestion_source_id: initial.source_id } : item));
      const generated = await waitForSource(initial);
      setDraft(generated);
      setSelected(generated.status === 'proposed'
        ? generated.items.map((item) => item.id)
        : generated.items.filter((item) => item.accepted).map((item) => item.id));
    } catch (cause) {
      if (cause instanceof ApiError && cause.sourceId && cause.retryable) setFailedSourceId(cause.sourceId);
      fail(cause, '生成入库草案失败');
    } finally { setIngestingId(null); }
  };

  const retrySource = async () => {
    if (!failedSourceId) return;
    setDraftBusy(true); setError('');
    try {
      const result = await api.retrySource(failedSourceId);
      const generated = 'items' in result ? result : await waitForSource(result);
      setDraft(generated); setSelected(generated.items.map((item) => item.id)); setFailedSourceId(null);
    } catch (cause) { fail(cause, '重试入库草案失败'); }
    finally { setDraftBusy(false); }
  };

  const reprocess = async () => {
    if (!draft?.source_id || draftBusy) return;
    setDraftBusy(true); setError('');
    try {
      const generated = await waitForSource(await api.reprocessSource(draft.source_id, reprocessInstruction));
      setDraft(generated); setSelected(generated.items.map((item) => item.id));
      setReprocessInstruction(''); setReprocessOpen(false);
    } catch (cause) { fail(cause, '重新分析失败，原草案仍然可用'); }
    finally { setDraftBusy(false); }
  };

  const apply = async () => {
    if (!draft) return;
    setDraftBusy(true); setError('');
    try {
      await api.applyChangeSet(draft.id, selected);
      const [docs, events] = await Promise.all([api.documents(), api.events()]);
      onRefresh(docs, events);
      setDraft(null); setDraftProcessing(null); setSuccess('已按你的选择写入知识库。');
    } catch (cause) { fail(cause, '应用草案失败'); }
    finally { setDraftBusy(false); }
  };

  const openSource = async (url: string) => {
    try {
      const parsed = new URL(url);
      if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('不支持的来源地址');
      await openExternalUrl(parsed.toString());
    } catch (cause) { fail(cause, '无法打开来源'); }
  };

  const basisLabel = (basis: ResearchBasis | null) => basis === 'web' ? '联网综合' : '仅 AI · 未联网验证';

  return <section className="research-page">
    <header className="research-header">
      <div><span className="eyebrow">NERVA · KNOWLEDGE ACQUISITION</span><h1>向 AI 提问，把研究结果变成可审阅的知识</h1></div>
      <button className="research-drawer-button" onClick={() => setDrawerOpen(true)}>研究会话</button>
    </header>
    <div className="research-layout">
      <aside className={`research-sessions ${drawerOpen ? 'open' : ''}`}>
        <div className="research-sessions-head"><b>研究会话</b><button onClick={createSession}>＋ 新研究</button></div>
        {sessions.map((session) => <div className={`research-session ${session.id === sessionId ? 'active' : ''}`} key={session.id}>
          <button className="research-session-open" onClick={() => { onOpenSession(session.id); setDrawerOpen(false); }}>{session.title}</button>
          <button title="重命名" onClick={() => renameSession(session)}>✎</button>
          <button title="删除" onClick={() => deleteSession(session)}>×</button>
        </div>)}
        {!sessions.length && <p className="research-empty">新建研究后开始提问。</p>}
        <button className="research-drawer-close" onClick={() => setDrawerOpen(false)}>关闭</button>
      </aside>

      <div className="research-workspace">
        <div className="research-messages">
          {loading && <p className="research-empty">正在加载研究记录…</p>}
          {!loading && !messages.length && <div className="research-welcome"><h2>你想获取什么知识？</h2><p>智能模式会按问题需要决定是否联网；联网模式必须返回可验证来源。</p></div>}
          {messages.map((message) => <article className={`research-message ${message.role}`} key={message.id}>
            <div className="research-message-meta">
              <b>{message.role === 'user' ? '你' : 'Nerva 研究助手'}</b>
              {message.role === 'assistant' && message.requested_mode && <span>{MODE_LABELS[message.requested_mode]}</span>}
              {message.role === 'assistant' && message.status === 'completed' && <em className={message.basis === 'web' ? 'web' : 'ai'}>{basisLabel(message.basis)}</em>}
            </div>
            {message.role === 'assistant'
              ? <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: ({ children }) => <span>{children}</span>, img: () => null }}>{message.content || (message.status === 'generating' ? '正在研究…' : '')}</ReactMarkdown>
              : <p>{message.content}</p>}
            {message.citations.length > 0 && <div className="research-sources"><b>参考来源</b>{message.citations.map((source) =>
              <button key={source.url} onClick={() => openSource(source.url)}><span>{source.ordinal}</span><div><strong>{source.title}</strong><small>{source.domain}</small></div></button>
            )}</div>}
            {message.role === 'assistant' && ['failed', 'cancelled'].includes(message.status) && <div className="research-actions">
              <button disabled={streaming} onClick={() => retry(message)}>重试</button>
              {['RESEARCH_WEB_SOURCE_REQUIRED', 'RESEARCH_WEB_UNAVAILABLE'].includes(message.error_code || '') && <button disabled={streaming} onClick={() => retry(message, 'ai')}>改用仅 AI 重试</button>}
            </div>}
            {message.role === 'assistant' && message.status === 'completed' && <div className="research-actions">
              <button disabled={Boolean(ingestingId)} onClick={() => createDraft(message)}>
                {ingestingId === message.id ? '正在生成草案…' : message.ingestion_source_id ? '查看入库结果' : '生成入库草案'}
              </button>
            </div>}
          </article>)}
          <div ref={bottomRef} />
        </div>

        <div className="research-composer">
          <div className="research-modes">{(['smart', 'web', 'ai'] as ResearchMode[]).map((item) =>
            <button key={item} className={mode === item ? 'active' : ''} disabled={streaming} onClick={() => setMode(item)}>{MODE_LABELS[item]}</button>
          )}</div>
          <textarea value={input} maxLength={4000} disabled={streaming} onChange={(event) => setInput(event.target.value)} placeholder="输入你想研究的问题，支持连续追问…" onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void send(); }
          }} />
          {streaming ? <button className="research-send stop" onClick={() => abortRef.current?.abort()}>停止</button>
            : <button className="research-send" disabled={!input.trim()} onClick={send}>开始获取</button>}
        </div>
      </div>
    </div>

    {ingestingId && <div className="research-ingestion-progress" role="status" aria-live="polite">
      <strong>{draftProcessing ? INGESTION_STAGE_LABELS[draftProcessing.stage] : '正在提交当前回答'}</strong>
      <small>正在为这条回答生成独立草案，不会直接修改已有知识；AI 提取和查重通常需要 30–90 秒。</small>
    </div>}
    {draft && <div className="research-draft" ref={draftRef}><DraftPanel
      draft={draft} draftProcessing={draftProcessing} selected={selected} busy={draftBusy}
      reprocessOpen={reprocessOpen} reprocessInstruction={reprocessInstruction}
      onToggle={(id, checked) => setSelected((current) => checked ? [...current, id] : current.filter((item) => item !== id))}
      onReprocessOpen={() => setReprocessOpen(true)} onReprocessClose={() => setReprocessOpen(false)}
      onReprocessInstructionChange={setReprocessInstruction} onReprocess={reprocess}
      onDiscard={() => { setDraft(null); setDraftProcessing(null); }} onApply={apply}
    /></div>}
    {error && <div className="research-notice error">{error}{failedSourceId && <button disabled={draftBusy} onClick={retrySource}>重试入库处理</button>}</div>}
    {success && <div className="research-notice success">{success}</div>}
  </section>;
}
