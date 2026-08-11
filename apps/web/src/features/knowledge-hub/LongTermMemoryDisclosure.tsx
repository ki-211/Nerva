import { useEffect, useState } from 'react';
import { api } from '../../lib/api';
import type { LongTermMemory, LongTermMemoryMutation } from '../../lib/types';
import './memoryDisclosure.css';

const LABELS = { person: '人物', project: '项目', decision: '决定', fact: '事实' } as const;

type Props = {
  memoryRefs: string[];
  context?: LongTermMemory[];
  candidates?: LongTermMemory[];
  mutations?: LongTermMemoryMutation[];
};

export function LongTermMemoryDisclosure({ memoryRefs, context = [], candidates = [], mutations = [] }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [used, setUsed] = useState<LongTermMemory[]>(context);
  const [suggestions, setSuggestions] = useState<LongTermMemory[]>(candidates);
  const [undoable, setUndoable] = useState<LongTermMemoryMutation[]>(mutations);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState('');

  useEffect(() => { if (context.length) setUsed(context); }, [context]);
  useEffect(() => { if (candidates.length) setSuggestions(candidates); }, [candidates]);
  useEffect(() => { if (mutations.length) setUndoable(mutations); }, [mutations]);

  const toggle = async () => {
    const next = !expanded;
    setExpanded(next);
    if (next && memoryRefs.length && used.length === 0) {
      try {
        const all = await api.longTermMemories();
        setUsed(all.filter((memory) => memoryRefs.includes(memory.id)));
      } catch (cause) { setError(cause instanceof Error ? cause.message : '记忆详情加载失败'); }
    }
  };

  const decide = async (memory: LongTermMemory, status: 'active' | 'suppressed') => {
    setBusy(memory.id); setError('');
    try {
      await api.updateLongTermMemory(memory.id, { status });
      setSuggestions((current) => current.filter((item) => item.id !== memory.id));
    } catch (cause) { setError(cause instanceof Error ? cause.message : '记忆状态更新失败'); }
    finally { setBusy(null); }
  };

  const forget = async (memory: LongTermMemory) => {
    if (!window.confirm(`让 Nerva 忘记“${memory.subject}”吗？`)) return;
    setBusy(memory.id); setError('');
    try {
      const mutation = await api.deleteLongTermMemory(memory.id);
      setUsed((current) => current.filter((item) => item.id !== memory.id));
      setUndoable((current) => [mutation, ...current]);
    } catch (cause) { setError(cause instanceof Error ? cause.message : '忘记操作失败'); }
    finally { setBusy(null); }
  };

  const correct = async (memory: LongTermMemory) => {
    const content = window.prompt('纠正这条长期记忆：', memory.content)?.trim();
    if (!content || content === memory.content) return;
    setBusy(memory.id); setError('');
    try {
      const updated = await api.updateLongTermMemory(memory.id, { content });
      setUsed((current) => current.map((item) => item.id === memory.id ? updated : item));
    } catch (cause) { setError(cause instanceof Error ? cause.message : '记忆纠正失败'); }
    finally { setBusy(null); }
  };

  const undo = async (mutation: LongTermMemoryMutation) => {
    setBusy(mutation.id); setError('');
    try {
      const restored = await api.undoLongTermMemoryMutation(mutation.id);
      if (restored.memory) setUsed((current) => [restored.memory!, ...current.filter((item) => item.id !== restored.memory!.id)]);
      setUndoable((current) => current.filter((item) => item.id !== mutation.id));
    } catch (cause) { setError(cause instanceof Error ? cause.message : '撤销失败'); }
    finally { setBusy(null); }
  };

  const hasUsed = memoryRefs.length > 0 || context.length > 0;
  if (!hasUsed && !suggestions.length && !undoable.length) return null;
  return <div className="memory-disclosure">
    {hasUsed && <button type="button" className="memory-disclosure-toggle" onClick={toggle}>✦ 使用了 {memoryRefs.length || context.length} 条长期记忆 <span>{expanded ? '收起' : '查看'}</span></button>}
    {expanded && <div className="memory-disclosure-panel">
      {used.map((memory) => <div key={memory.id} className="memory-disclosure-item"><div><small>{LABELS[memory.kind]}</small><b>{memory.subject}</b><p>{memory.content}</p></div><span><button disabled={busy === memory.id} onClick={() => correct(memory)}>纠正</button><button disabled={busy === memory.id} onClick={() => forget(memory)}>忘记</button></span></div>)}
      {memoryRefs.length > used.length && <p className="memory-disclosure-missing">其中 {memoryRefs.length - used.length} 条记忆已被遗忘或停用。</p>}
    </div>}
    {!!suggestions.length && <div className="memory-suggestions"><b>发现待确认的长期记忆</b>{suggestions.map((memory) => <div key={memory.id}><span><small>{LABELS[memory.kind]}</small>{memory.subject}：{memory.content}</span><span><button disabled={busy === memory.id} onClick={() => decide(memory, 'active')}>确认记住</button><button disabled={busy === memory.id} onClick={() => decide(memory, 'suppressed')}>忽略</button></span></div>)}</div>}
    {!!undoable.length && <div className="memory-undo">记忆已更新，十分钟内可以撤销。<button disabled={busy === undoable[0].id} onClick={() => undo(undoable[0])}>撤销</button></div>}
    {error && <p className="memory-disclosure-error">{error}</p>}
  </div>;
}
