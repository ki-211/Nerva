import { useEffect, useState } from 'react';
import { ApiError, api } from '../../lib/api';
import type { Memory, MemoryKind, MemoryStatus } from '../../lib/types';
import './memories.css';

const KIND_LABELS: Record<MemoryKind, string> = {
  style: '写作风格',
  topic_split: '主题拆分',
  domain: '领域背景',
  naming: '命名偏好',
  merge_preference: '合并策略',
};

type Props = {
  onAuthError: () => void;
};

export function MemoriesPage({ onAuthError }: Props) {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<string | null>(null);
  const [editContent, setEditContent] = useState('');
  const [creating, setCreating] = useState(false);
  const [newKind, setNewKind] = useState<MemoryKind>('style');
  const [newContent, setNewContent] = useState('');
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState('');

  const handleError = (cause: unknown, fallback: string) => {
    if (cause instanceof ApiError && cause.status === 401) {
      onAuthError();
      return;
    }
    setError(cause instanceof Error ? cause.message : fallback);
  };

  useEffect(() => {
    api.memories()
      .then(setMemories)
      .catch((cause) => handleError(cause, '偏好设置加载失败'))
      .finally(() => setLoading(false));
  }, [onAuthError]);

  const handleCreate = async () => {
    if (!newContent.trim()) return;
    setPending('create');
    setError('');
    try {
      const created = await api.createMemory({
        kind: newKind,
        content: newContent.trim(),
      });
      setMemories((prev) => [created, ...prev]);
      setNewContent('');
      setCreating(false);
    } catch (cause) {
      handleError(cause, '偏好创建失败');
    } finally {
      setPending(null);
    }
  };

  const handleSave = async (id: string) => {
    if (!editContent.trim()) return;
    setPending(id);
    setError('');
    try {
      const updated = await api.updateMemory(id, { content: editContent.trim() });
      setMemories((prev) => prev.map((m) => (m.id === id ? updated : m)));
      setEditing(null);
    } catch (cause) {
      handleError(cause, '偏好保存失败');
    } finally {
      setPending(null);
    }
  };

  const handleStatusToggle = async (id: string, currentStatus: MemoryStatus) => {
    const newStatus = currentStatus === 'active' ? 'suppressed' : 'active';
    setPending(id);
    setError('');
    try {
      const updated = await api.updateMemory(id, { status: newStatus });
      setMemories((prev) => prev.map((m) => (m.id === id ? updated : m)));
    } catch (cause) {
      handleError(cause, '偏好状态更新失败');
    } finally {
      setPending(null);
    }
  };

  const handleDelete = async (id: string) => {
    if (!window.confirm('确定删除这条记忆吗？')) return;
    setPending(id);
    setError('');
    try {
      await api.deleteMemory(id);
      setMemories((prev) => prev.filter((m) => m.id !== id));
    } catch (cause) {
      handleError(cause, '偏好删除失败');
    } finally {
      setPending(null);
    }
  };

  const startEdit = (memory: Memory) => {
    setEditing(memory.id);
    setEditContent(memory.content);
  };

  const activeCount = memories.filter((m) => m.status === 'active').length;
  const candidateCount = memories.filter((m) => m.status === 'candidate').length;

  if (loading) {
    return <div className="memories-page loading">加载偏好设置…</div>;
  }

  return (
    <div className="memories-page">
      <header>
        <h1>个性化偏好</h1>
        <p>
          Nerva 会在提取和整理知识时遵循你的偏好。
          <strong>{activeCount}</strong> 条生效中
          {candidateCount > 0 && <span className="hint">，{candidateCount} 条待确认</span>}
        </p>
      </header>

      {error && <div className="memory-error" role="alert">{error}</div>}

      {candidateCount > 0 && (
        <div className="candidate-bar">
          <span className="icon">💡</span>
          <div>
            <b>AI 观察到 {candidateCount} 条新偏好</b>
            <small>根据你在重新分析时提出的要求生成，可激活或删除</small>
          </div>
        </div>
      )}

      <section className="new-memory">
        {!creating ? (
          <button onClick={() => setCreating(true)}>＋ 添加偏好</button>
        ) : (
          <div className="memory-form">
            <select value={newKind} onChange={(e) => setNewKind(e.target.value as MemoryKind)}>
              {(Object.keys(KIND_LABELS) as MemoryKind[]).map((k) => (
                <option key={k} value={k}>
                  {KIND_LABELS[k]}
                </option>
              ))}
            </select>
            <textarea
              placeholder="描述你的偏好，例如：使用简洁的技术文档风格，避免口语化"
              value={newContent}
              onChange={(e) => setNewContent(e.target.value)}
              autoFocus
            />
            <div className="actions">
              <button onClick={handleCreate} disabled={!newContent.trim() || pending === 'create'}>
                {pending === 'create' ? '保存中…' : '保存'}
              </button>
              <button onClick={() => setCreating(false)} className="cancel">
                取消
              </button>
            </div>
          </div>
        )}
      </section>

      <section className="memory-list">
        {memories.length === 0 && (
          <div className="empty">
            还没有偏好设置。点击上方「添加偏好」开始个性化你的知识库。
          </div>
        )}
        {memories.map((memory) => (
          <article
            key={memory.id}
            className={`memory-card ${memory.status}`}
            data-kind={memory.kind}
          >
            <header>
              <span className="kind">{KIND_LABELS[memory.kind]}</span>
              <span className="status-badge">{memory.status === 'active' ? '生效中' : memory.status === 'candidate' ? '待确认' : '已停用'}</span>
            </header>
            {editing === memory.id ? (
              <div className="memory-form">
                <textarea
                  value={editContent}
                  onChange={(e) => setEditContent(e.target.value)}
                  autoFocus
                />
                <div className="actions">
                  <button onClick={() => handleSave(memory.id)} disabled={!editContent.trim() || pending === memory.id}>
                    {pending === memory.id ? '保存中…' : '保存'}
                  </button>
                  <button onClick={() => setEditing(null)} className="cancel">
                    取消
                  </button>
                </div>
              </div>
            ) : (
              <>
                <p className="content">{memory.content}</p>
                <footer>
                  <span className="meta">
                    {memory.use_count > 0 ? `已应用 ${memory.use_count} 次` : '尚未使用'}
                  </span>
                  <div className="memory-actions">
                    <button disabled={pending === memory.id} onClick={() => startEdit(memory)}>编辑</button>
                    <button disabled={pending === memory.id} onClick={() => handleStatusToggle(memory.id, memory.status)}>
                      {memory.status === 'active' ? '停用' : '激活'}
                    </button>
                    <button disabled={pending === memory.id} onClick={() => handleDelete(memory.id)} className="delete">
                      删除
                    </button>
                  </div>
                </footer>
              </>
            )}
          </article>
        ))}
      </section>
    </div>
  );
}
