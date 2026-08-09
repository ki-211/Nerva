import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ApiError, api } from '../../lib/api';
import type { ChatMessage, ChatSession, ChatStreamHandlers, Memory } from '../../lib/types';
import './chat.css';

type Props = {
  sessionId: string | null;
  onOpenSession: (id: string) => void;
  onOpenDocument: (id: string, visibility: 'private' | 'public') => void;
  onOpenCapture: () => void;
  onAuthError: () => void;
};

const GROUNDING_LABELS = {
  knowledge: '来自知识库',
  knowledge_plus_general: '知识库 + 通用补充',
  general: '通用知识补充',
  insufficient: '知识不足',
};

function draftMessage(id: string, sessionId: string, role: 'user' | 'assistant', content: string, includePublic = true): ChatMessage {
  return {
    id, session_id: sessionId, role,
    status: role === 'user' ? 'completed' : 'generating', content,
    model: null, grounding: null, citations: [], error_code: null,
    created_at: new Date().toISOString(), completed_at: role === 'user' ? new Date().toISOString() : null,
    include_public: includePublic,
  };
}

export function ChatPage({ sessionId, onOpenSession, onOpenDocument, onOpenCapture, onAuthError }: Props) {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(true);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState('');
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [includePublic, setIncludePublic] = useState(true);
  const abortRef = useRef<AbortController | null>(null);
  const skipMessageLoadRef = useRef<string | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  const fail = (cause: unknown, fallback: string) => {
    if (cause instanceof ApiError && cause.status === 401) {
      onAuthError();
      return;
    }
    setError(cause instanceof Error ? cause.message : fallback);
  };

  const refreshSessions = async () => {
    const list = await api.chatSessions();
    setSessions(list);
    return list;
  };

  useEffect(() => {
    refreshSessions()
      .then((list) => {
        if (!sessionId && list.length) onOpenSession(list[0].id);
      })
      .catch((cause) => fail(cause, '对话列表加载失败'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!sessionId) {
      setMessages([]);
      return;
    }
    if (skipMessageLoadRef.current === sessionId) {
      skipMessageLoadRef.current = null;
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError('');
    api.chatMessages(sessionId)
      .then((loaded) => {
        if (!cancelled) setMessages(loaded);
      })
      .catch((cause) => {
        if (!cancelled) fail(cause, '对话消息加载失败');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [sessionId]);

  useEffect(() => () => abortRef.current?.abort(), []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: streaming ? 'auto' : 'smooth' });
  }, [messages, streaming]);

  const createSession = async () => {
    setError('');
    try {
      const created = await api.createChatSession();
      skipMessageLoadRef.current = created.id;
      setSessions((current) => [created, ...current]);
      setMessages([]);
      setDrawerOpen(false);
      onOpenSession(created.id);
      return created;
    } catch (cause) {
      fail(cause, '新建对话失败');
      return null;
    }
  };

  const renameSession = async (session: ChatSession) => {
    const title = window.prompt('重命名对话', session.title)?.trim();
    if (!title || title === session.title) return;
    try {
      const updated = await api.updateChatSession(session.id, title);
      setSessions((current) => current.map((item) => item.id === session.id ? updated : item));
    } catch (cause) {
      fail(cause, '重命名失败');
    }
  };

  const deleteSession = async (session: ChatSession) => {
    if (!window.confirm(`删除对话“${session.title}”及全部消息吗？`)) return;
    try {
      await api.deleteChatSession(session.id);
      const next = sessions.filter((item) => item.id !== session.id);
      setSessions(next);
      if (session.id === sessionId) {
        setMessages([]);
        if (next.length) onOpenSession(next[0].id);
        else onOpenSession('');
      }
    } catch (cause) {
      fail(cause, '删除对话失败');
    }
  };

  const streamHandlers = (
    assistantKey: { current: string },
    optimistic?: { userKey: string; sessionId: string; content: string },
  ): ChatStreamHandlers => ({
    onStart: ({ assistant_message_id, user_message_id }) => {
      const previousAssistant = assistantKey.current;
      assistantKey.current = assistant_message_id;
      setMessages((current) => {
        let next = current.map((message) => {
          if (message.id === previousAssistant) return { ...message, id: assistant_message_id };
          if (optimistic && message.id === optimistic.userKey) return { ...message, id: user_message_id };
          return message;
        });
        if (optimistic && !next.some((message) => message.id === user_message_id)) {
          next = [...next, { ...draftMessage(user_message_id, optimistic.sessionId, 'user', optimistic.content, includePublic) }];
        }
        if (!next.some((message) => message.id === assistant_message_id)) {
          const targetSession = optimistic?.sessionId || sessionId;
          if (targetSession) {
            next = [...next, draftMessage(assistant_message_id, targetSession, 'assistant', '', includePublic)];
          }
        }
        return next;
      });
    },
    onDelta: (text) => setMessages((current) => current.map((message) =>
      message.id === assistantKey.current ? { ...message, content: message.content + text } : message
    )),
    onMemoryCandidates: (memories) => setMessages((current) => current.map((message) =>
      message.id === assistantKey.current ? { ...message, memory_candidates: memories } : message
    )),
    onDone: (message) => {
      setMessages((current) => current.map((item) =>
        item.id === assistantKey.current ? { ...message, memory_candidates: item.memory_candidates } : item
      ));
      refreshSessions().catch(() => undefined);
    },
    onError: (streamError) => {
      setError(streamError.message);
      setMessages((current) => current.map((message) =>
        message.id === assistantKey.current
          ? { ...message, status: 'failed', error_code: streamError.code }
          : message
      ));
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
    const userTemp = `tmp-user-${stamp}`;
    const assistantTemp = `tmp-assistant-${stamp}`;
    const assistantKey = { current: assistantTemp };
    setMessages((current) => [
      ...current,
      draftMessage(userTemp, activeSessionId!, 'user', content, includePublic),
      draftMessage(assistantTemp, activeSessionId!, 'assistant', '', includePublic),
    ]);
    setInput('');
    setError('');
    setStreaming(true);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await api.sendChatMessage(
        activeSessionId, content,
        streamHandlers(assistantKey, { userKey: userTemp, sessionId: activeSessionId, content }),
        controller.signal,
        includePublic,
      );
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === 'AbortError') {
        setMessages((current) => current.map((message) =>
          message.id === assistantKey.current ? { ...message, status: 'cancelled', error_code: 'CHAT_CANCELLED' } : message
        ));
      } else {
        fail(cause, '发送消息失败');
        setMessages((current) => current.map((message) =>
          message.id === assistantKey.current ? { ...message, status: 'failed', error_code: 'CHAT_REQUEST_FAILED' } : message
        ));
      }
    } finally {
      abortRef.current = null;
      setStreaming(false);
    }
  };

  const retry = async (message: ChatMessage) => {
    if (streaming) return;
    const assistantKey = { current: message.id };
    setMessages((current) => current.map((item) =>
      item.id === message.id ? { ...item, status: 'generating', content: '', error_code: null } : item
    ));
    setStreaming(true);
    setError('');
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await api.retryChatMessage(message.id, streamHandlers(assistantKey), controller.signal);
    } catch (cause) {
      if (!(cause instanceof DOMException && cause.name === 'AbortError')) fail(cause, '重试失败');
    } finally {
      abortRef.current = null;
      setStreaming(false);
    }
  };

  const decideMemory = async (messageId: string, memory: Memory, status: 'active' | 'suppressed') => {
    try {
      await api.updateMemory(memory.id, { status });
      setMessages((current) => current.map((message) => message.id === messageId ? {
        ...message,
        memory_candidates: message.memory_candidates?.filter((item) => item.id !== memory.id),
      } : message));
    } catch (cause) {
      fail(cause, '记忆状态更新失败');
    }
  };

  const currentSession = sessions.find((item) => item.id === sessionId);

  return (
    <div className="chat-page">
      <aside className={`chat-sessions ${drawerOpen ? 'open' : ''}`}>
        <div className="chat-session-head">
          <b>历史对话</b>
          <button onClick={createSession} disabled={streaming}>＋ 新对话</button>
        </div>
        <div className="chat-session-list">
          {sessions.map((session) => (
            <div key={session.id} className={`chat-session-item ${session.id === sessionId ? 'active' : ''}`}>
              <button disabled={streaming} className="session-open" onClick={() => { onOpenSession(session.id); setDrawerOpen(false); }}>
                <span>{session.title}</span>
                <small>{new Date(session.updated_at).toLocaleDateString()}</small>
              </button>
              <button disabled={streaming} title="重命名" onClick={() => renameSession(session)}>✎</button>
              <button disabled={streaming} title="删除" onClick={() => deleteSession(session)}>×</button>
            </div>
          ))}
          {!sessions.length && <p className="chat-session-empty">还没有历史对话</p>}
        </div>
      </aside>

      <section className="chat-conversation">
        <header className="chat-header">
          <button className="session-toggle" onClick={() => setDrawerOpen((value) => !value)}>☰</button>
          <div>
            <small>NERVA · KNOWLEDGE CHAT</small>
            <h1>{currentSession?.title || '与知识库对话'}</h1>
          </div>
          <span className="read-only">只读模式</span>
        </header>

        <div className="chat-messages">
          {loading && <div className="chat-empty">正在加载对话…</div>}
          {!loading && !messages.length && (
            <div className="chat-empty chat-welcome">
              <span>N</span>
              <h2>问问你的知识库</h2>
              <p>我会优先引用已审批的正式文档；知识不足时会明确标注通用补充。</p>
              <div className="chat-suggestions">
                <button onClick={() => setInput('总结我的知识库里最重要的主题')}>总结重要主题</button>
                <button onClick={() => setInput('最近新增了哪些知识？')}>查看最近知识</button>
              </div>
            </div>
          )}
          {messages.map((message) => (
            <article key={message.id} className={`chat-message ${message.role}`}>
              <div className="message-avatar">{message.role === 'user' ? '我' : 'N'}</div>
              <div className="message-body">
                {message.role === 'assistant' ? (
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content || (message.status === 'generating' ? '正在思考…' : '')}</ReactMarkdown>
                ) : <p>{message.content}</p>}
                {message.role === 'assistant' && message.status === 'generating' && <i className="stream-cursor" />}
                {message.grounding && <span className={`grounding ${message.grounding}`}>{GROUNDING_LABELS[message.grounding]}</span>}
                {!!message.citations.length && (
                  <div className="chat-sources">
                    {message.citations.map((source) => (
                      <button key={source.ref} onClick={() => onOpenDocument(source.document_id, source.visibility)}>
                        <b>[{source.ref}] {source.title}</b>
                        <small>{source.excerpt}</small>
                      </button>
                    ))}
                  </div>
                )}
                {!!message.memory_candidates?.length && (
                  <div className="chat-memory-candidates">
                    <b>是否记住这些长期偏好？</b>
                    {message.memory_candidates.map((memory) => (
                      <div key={memory.id}>
                        <span>{memory.content}</span>
                        <button onClick={() => decideMemory(message.id, memory, 'active')}>记住</button>
                        <button onClick={() => decideMemory(message.id, memory, 'suppressed')}>忽略</button>
                      </div>
                    ))}
                  </div>
                )}
                {message.role === 'assistant' && ['failed', 'cancelled'].includes(message.status) && (
                  <button className="retry-message" onClick={() => retry(message)}>重新生成</button>
                )}
                {message.role === 'assistant' && message.status === 'completed' && (
                  <button className="capture-link" onClick={onOpenCapture}>需要保存事实？转到知识录入 →</button>
                )}
              </div>
            </article>
          ))}
          <div ref={bottomRef} />
        </div>

        {error && <div className="chat-error" role="alert">{error}</div>}
        <div className="chat-composer">
          <label className="chat-public-toggle"><input type="checkbox" checked={includePublic} onChange={(event) => setIncludePublic(event.target.checked)} disabled={streaming} /> 包含大众知识库</label>
          <textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                send();
              }
            }}
            maxLength={4000}
            disabled={loading && sessionId !== null}
            placeholder="询问知识库，或说“请记住：以后……”"
          />
          {streaming ? (
            <button className="stop" onClick={() => abortRef.current?.abort()}>停止</button>
          ) : (
            <button onClick={send} disabled={!input.trim()}>发送</button>
          )}
          <small>{input.length}/4000 · Enter 发送，Shift + Enter 换行</small>
        </div>
      </section>
    </div>
  );
}
