import { useEffect, useMemo, useState } from 'react';
import { api } from '../../lib/api';
import type {
  Document, KnowledgeEvent, KnowledgeHubSettings, LongTermMemory, LongTermMemoryEvent, LongTermMemoryKind,
  LongTermMemoryMutation, LongTermMemoryStatus, Memory, MemoryKind, MemoryStatus,
} from '../../lib/types';
import './knowledgeHub.css';

const KIND_LABELS: Record<MemoryKind, string> = {
  style: '写作风格',
  topic_split: '主题拆分',
  domain: '领域背景',
  naming: '命名偏好',
  merge_preference: '合并策略',
};

const STATUS_LABELS: Record<MemoryStatus, string> = {
  active: '生效中',
  candidate: '待确认',
  suppressed: '已停用',
};

const LONG_TERM_KIND_LABELS: Record<LongTermMemoryKind, string> = {
  person: '人物', project: '项目', decision: '决定', fact: '重要事实',
};
const LONG_TERM_STATUS_LABELS: Record<LongTermMemoryStatus, string> = {
  active: '已记住', candidate: '待确认', suppressed: '已忽略',
};

type Props = {
  documents: Document[];
  events: KnowledgeEvent[];
  onOpenLibrary: () => void;
  onOpenMemorySource?: (channel: 'chat' | 'research', sessionId: string) => void;
};

type TrendRange = 7 | 30 | 90;
type SettingKey = keyof KnowledgeHubSettings;

function dateKey(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function dateLabel(date: Date): string {
  return `${date.getMonth() + 1}/${date.getDate()}`;
}

function buildTrend(events: KnowledgeEvent[], memoryEvents: LongTermMemoryEvent[], days: TrendRange) {
  const totals = new Map<string, { eventCount: number; acceptedCount: number; memoryCount: number }>();
  events.forEach((event) => {
    const parsed = new Date(event.created_at);
    if (Number.isNaN(parsed.getTime())) return;
    const key = dateKey(parsed);
    const current = totals.get(key) || { eventCount: 0, acceptedCount: 0, memoryCount: 0 };
    current.eventCount += 1;
    current.acceptedCount += event.accepted_count;
    totals.set(key, current);
  });
  memoryEvents.forEach((event) => {
    const parsed = new Date(event.created_at);
    if (Number.isNaN(parsed.getTime())) return;
    const key = dateKey(parsed);
    const current = totals.get(key) || { eventCount: 0, acceptedCount: 0, memoryCount: 0 };
    current.memoryCount += 1;
    totals.set(key, current);
  });
  const today = new Date();
  today.setHours(12, 0, 0, 0);
  return Array.from({ length: days }, (_, index) => {
    const date = new Date(today);
    date.setDate(today.getDate() - (days - index - 1));
    return { date, ...(totals.get(dateKey(date)) || { eventCount: 0, acceptedCount: 0, memoryCount: 0 }) };
  });
}

function TrendChart({ events, memoryEvents, range }: { events: KnowledgeEvent[]; memoryEvents: LongTermMemoryEvent[]; range: TrendRange }) {
  const data = useMemo(() => buildTrend(events, memoryEvents, range), [events, memoryEvents, range]);
  const width = 800;
  const height = 210;
  const left = 44;
  const right = 18;
  const top = 18;
  const bottom = 34;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const maximum = Math.max(1, ...data.flatMap((item) => [item.eventCount, item.acceptedCount, item.memoryCount]));
  const x = (index: number) => left + (data.length === 1 ? 0 : (index / (data.length - 1)) * plotWidth);
  const y = (value: number) => top + plotHeight - (value / maximum) * plotHeight;
  const points = (key: 'eventCount' | 'acceptedCount' | 'memoryCount') => data
    .map((item, index) => `${x(index).toFixed(1)},${y(item[key]).toFixed(1)}`).join(' ');
  const totalEvents = data.reduce((sum, item) => sum + item.eventCount, 0);
  const totalAccepted = data.reduce((sum, item) => sum + item.acceptedCount, 0);
  const totalMemoryEvents = data.reduce((sum, item) => sum + item.memoryCount, 0);
  const labelIndexes = Array.from(new Set([0, Math.floor((data.length - 1) / 2), data.length - 1]));

  return <div className="hub-chart-wrap">
    <svg
      className="hub-chart"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`最近 ${range} 天有 ${totalEvents} 次知识变更，共接受 ${totalAccepted} 项变更，发生 ${totalMemoryEvents} 次记忆演进`}
    >
      {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
        const value = Math.round(maximum * (1 - ratio));
        const rowY = top + plotHeight * ratio;
        return <g key={ratio}>
          <line x1={left} x2={width - right} y1={rowY} y2={rowY} className="chart-grid" />
          <text x={left - 10} y={rowY + 4} textAnchor="end" className="chart-axis-label">{value}</text>
        </g>;
      })}
      <polygon
        points={`${left},${top + plotHeight} ${points('acceptedCount')} ${width - right},${top + plotHeight}`}
        className="chart-area"
      />
      <polyline points={points('acceptedCount')} className="chart-line accepted" />
      <polyline points={points('eventCount')} className="chart-line events" />
      <polyline points={points('memoryCount')} className="chart-line memories" />
      {labelIndexes.map((index) => <text
        key={index}
        x={x(index)}
        y={height - 8}
        textAnchor={index === 0 ? 'start' : index === data.length - 1 ? 'end' : 'middle'}
        className="chart-axis-label"
      >{dateLabel(data[index].date)}</text>)}
    </svg>
    {totalEvents === 0 && totalAccepted === 0 && totalMemoryEvents === 0 && <div className="hub-chart-empty">
      <b>这段时间还没有知识变更</b>
      <span>录入并确认知识后，这里会展示知识库的成长轨迹。</span>
    </div>}
  </div>;
}

function ToggleRow({
  icon, title, description, checked, disabled, onChange,
}: {
  icon: string;
  title: string;
  description: string;
  checked: boolean;
  disabled: boolean;
  onChange: () => void;
}) {
  return <div className="hub-toggle-row">
    <span className="hub-row-icon" aria-hidden="true">{icon}</span>
    <div>
      <b>{title}</b>
      <p>{description}</p>
    </div>
    <button
      type="button"
      className={`hub-switch ${checked ? 'on' : ''}`}
      role="switch"
      aria-checked={checked}
      aria-label={title}
      disabled={disabled}
      onClick={onChange}
    ><span /></button>
  </div>;
}

export function KnowledgeHubPage({ documents, events, onOpenLibrary, onOpenMemorySource }: Props) {
  const [settings, setSettings] = useState<KnowledgeHubSettings | null>(null);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [longTermMemories, setLongTermMemories] = useState<LongTermMemory[]>([]);
  const [memoryEvents, setMemoryEvents] = useState<LongTermMemoryEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [savingSetting, setSavingSetting] = useState<SettingKey | null>(null);
  const [range, setRange] = useState<TrendRange>(30);
  const [editing, setEditing] = useState<string | null>(null);
  const [editContent, setEditContent] = useState('');
  const [creating, setCreating] = useState(false);
  const [newKind, setNewKind] = useState<MemoryKind>('style');
  const [newContent, setNewContent] = useState('');
  const [pending, setPending] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [longTermFilter, setLongTermFilter] = useState<LongTermMemoryKind | 'all'>('all');
  const [longTermQuery, setLongTermQuery] = useState('');
  const [creatingLongTerm, setCreatingLongTerm] = useState(false);
  const [newLongTermKind, setNewLongTermKind] = useState<LongTermMemoryKind>('fact');
  const [newLongTermSubject, setNewLongTermSubject] = useState('');
  const [newLongTermContent, setNewLongTermContent] = useState('');
  const [editingLongTerm, setEditingLongTerm] = useState<string | null>(null);
  const [editLongTermSubject, setEditLongTermSubject] = useState('');
  const [editLongTermContent, setEditLongTermContent] = useState('');
  const [undoMutation, setUndoMutation] = useState<LongTermMemoryMutation | null>(null);
  const [extractingHistory, setExtractingHistory] = useState(false);

  const showError = (cause: unknown, fallback: string) => {
    setError(cause instanceof Error ? cause.message : fallback);
    setNotice('');
  };

  useEffect(() => {
    Promise.all([api.knowledgeHubSettings(), api.memories(), api.longTermMemories(), api.longTermMemoryEvents()])
      .then(([hubSettings, loadedMemories, loadedLongTermMemories, loadedMemoryEvents]) => {
        setSettings(hubSettings);
        setMemories(loadedMemories);
        setLongTermMemories(loadedLongTermMemories);
        setMemoryEvents(loadedMemoryEvents);
      })
      .catch((cause) => showError(cause, '知识中枢加载失败'))
      .finally(() => setLoading(false));
  }, []);

  const updateSetting = async (key: SettingKey) => {
    if (!settings || savingSetting) return;
    const previous = settings;
    const next = { ...settings, [key]: !settings[key] };
    setSettings(next);
    setSavingSetting(key);
    setError('');
    setNotice('');
    try {
      setSettings(await api.updateKnowledgeHubSettings({ [key]: next[key] }));
    } catch (cause) {
      setSettings(previous);
      showError(cause, '设置保存失败，已恢复原状态');
    } finally {
      setSavingSetting(null);
    }
  };

  const handleCreate = async () => {
    if (!newContent.trim()) return;
    setPending('create'); setError(''); setNotice('');
    try {
      const created = await api.createMemory({ kind: newKind, content: newContent.trim() });
      setMemories((current) => [created, ...current]);
      setNewContent(''); setCreating(false); setNotice('偏好已添加并开始生效');
    } catch (cause) { showError(cause, '偏好创建失败'); }
    finally { setPending(null); }
  };

  const handleSave = async (id: string) => {
    if (!editContent.trim()) return;
    setPending(id); setError(''); setNotice('');
    try {
      const updated = await api.updateMemory(id, { content: editContent.trim() });
      setMemories((current) => current.map((item) => item.id === id ? updated : item));
      setEditing(null); setNotice('偏好已保存');
    } catch (cause) { showError(cause, '偏好保存失败'); }
    finally { setPending(null); }
  };

  const handleStatusToggle = async (memory: Memory) => {
    const status: MemoryStatus = memory.status === 'active' ? 'suppressed' : 'active';
    setPending(memory.id); setError(''); setNotice('');
    try {
      const updated = await api.updateMemory(memory.id, { status });
      setMemories((current) => current.map((item) => item.id === memory.id ? updated : item));
      setNotice(memory.status === 'candidate' ? '偏好已确认并开始生效' : status === 'active' ? '偏好已启用' : '偏好已停用');
    } catch (cause) { showError(cause, '偏好状态更新失败'); }
    finally { setPending(null); }
  };

  const handleDelete = async (memory: Memory) => {
    if (!window.confirm(`确定删除“${memory.content}”吗？此操作无法撤销。`)) return;
    setPending(memory.id); setError(''); setNotice('');
    try {
      await api.deleteMemory(memory.id);
      setMemories((current) => current.filter((item) => item.id !== memory.id));
      setNotice('偏好已删除');
    } catch (cause) { showError(cause, '偏好删除失败'); }
    finally { setPending(null); }
  };

  const handleExport = async () => {
    setExporting(true); setError(''); setNotice('');
    try {
      await api.exportKnowledgePackage('library');
      setNotice('知识包已导出');
    } catch (cause) { showError(cause, '知识包导出失败'); }
    finally { setExporting(false); }
  };

  const createLongTermMemory = async () => {
    if (!newLongTermSubject.trim() || !newLongTermContent.trim()) return;
    setPending('long-term-create'); setError(''); setNotice('');
    try {
      const created = await api.createLongTermMemory({
        kind: newLongTermKind, subject: newLongTermSubject.trim(), content: newLongTermContent.trim(),
      });
      setLongTermMemories((current) => [created, ...current]);
      setNewLongTermSubject(''); setNewLongTermContent(''); setCreatingLongTerm(false);
      setNotice('长期记忆已添加并开始生效');
    } catch (cause) { showError(cause, '长期记忆创建失败'); }
    finally { setPending(null); }
  };

  const saveLongTermMemory = async (memory: LongTermMemory) => {
    if (!editLongTermSubject.trim() || !editLongTermContent.trim()) return;
    setPending(memory.id); setError(''); setNotice('');
    try {
      const updated = await api.updateLongTermMemory(memory.id, {
        subject: editLongTermSubject.trim(), content: editLongTermContent.trim(),
      });
      setLongTermMemories((current) => current.map((item) => item.id === memory.id ? updated : item));
      setEditingLongTerm(null); setNotice('长期记忆已纠正');
    } catch (cause) { showError(cause, '长期记忆保存失败'); }
    finally { setPending(null); }
  };

  const updateLongTermStatus = async (memory: LongTermMemory, status: LongTermMemoryStatus) => {
    setPending(memory.id); setError(''); setNotice('');
    try {
      const updated = await api.updateLongTermMemory(memory.id, { status });
      setLongTermMemories((current) => current.map((item) => item.id === memory.id ? updated : item));
      setNotice(status === 'active' ? '长期记忆已确认并开始召回' : '长期记忆已忽略');
    } catch (cause) { showError(cause, '长期记忆状态更新失败'); }
    finally { setPending(null); }
  };

  const forgetLongTermMemory = async (memory: LongTermMemory) => {
    if (!window.confirm(`确定让 Nerva 忘记“${memory.subject}”吗？十分钟内可以撤销。`)) return;
    setPending(memory.id); setError(''); setNotice('');
    try {
      const mutation = await api.deleteLongTermMemory(memory.id);
      setLongTermMemories((current) => current.filter((item) => item.id !== memory.id));
      setUndoMutation(mutation); setNotice('已忘记这条记忆，十分钟内可以撤销');
    } catch (cause) { showError(cause, '忘记操作失败'); }
    finally { setPending(null); }
  };

  const undoLongTermChange = async () => {
    if (!undoMutation) return;
    setPending('undo-long-term');
    try {
      const mutation = await api.undoLongTermMemoryMutation(undoMutation.id);
      if (mutation.memory) {
        setLongTermMemories((current) => [mutation.memory!, ...current.filter((item) => item.id !== mutation.memory!.id)]);
      }
      setUndoMutation(null); setNotice('长期记忆变更已撤销');
    } catch (cause) { showError(cause, '撤销失败'); }
    finally { setPending(null); }
  };

  const extractHistory = async () => {
    if (!window.confirm('将分析最多 50 轮已有对话，并产生额外模型调用。继续吗？')) return;
    setExtractingHistory(true); setError(''); setNotice('');
    try {
      const created = await api.extractLongTermMemoryHistory('all');
      setLongTermMemories((current) => [...created, ...current.filter((item) => !created.some((next) => next.id === item.id))]);
      setNotice(created.length ? `从历史对话中发现 ${created.length} 条记忆` : '历史对话中没有发现新的稳定记忆');
    } catch (cause) { showError(cause, '历史记忆提取失败'); }
    finally { setExtractingHistory(false); }
  };

  const startEdit = (memory: Memory) => {
    setEditing(memory.id);
    setEditContent(memory.content);
  };

  const activeCount = memories.filter((item) => item.status === 'active').length;
  const candidateCount = memories.filter((item) => item.status === 'candidate').length;
  const totalUses = memories.reduce((sum, item) => sum + item.use_count, 0);
  const activeLongTermCount = longTermMemories.filter((item) => item.status === 'active').length;
  const candidateLongTermCount = longTermMemories.filter((item) => item.status === 'candidate').length;
  const longTermUses = longTermMemories.reduce((sum, item) => sum + item.use_count, 0);
  const visibleLongTermMemories = longTermMemories.filter((memory) => {
    const kindMatches = longTermFilter === 'all' || memory.kind === longTermFilter;
    const query = longTermQuery.trim().toLocaleLowerCase();
    return kindMatches && (!query || `${memory.subject} ${memory.content}`.toLocaleLowerCase().includes(query));
  });
  const indexCounts = documents.reduce((counts, document) => {
    counts[document.index_status] += 1;
    return counts;
  }, { ready: 0, pending: 0, failed: 0 });
  const readyPercent = documents.length ? Math.round((indexCounts.ready / documents.length) * 100) : 0;

  if (loading) return <div className="knowledge-hub-loading">正在载入知识中枢…</div>;
  if (!settings) return <section className="knowledge-hub-page hub-load-failure" role="alert">
    <h1>知识中枢暂时不可用</h1>
    <p>{error || '请检查连接后刷新页面重试。'}</p>
  </section>;

  return <div className="knowledge-hub-page">
    <header className="hub-hero">
      <div className="hub-orbit" aria-hidden="true"><span>✦</span><i /><i /></div>
      <div>
        <span className="hub-eyebrow">NERVA KNOWLEDGE HUB</span>
        <h1>知识中枢</h1>
        <p>管理 Nerva 如何理解、记忆并组织你的知识。</p>
      </div>
    </header>

    {(error || notice) && <div className={`hub-message ${error ? 'error' : 'success'}`} role={error ? 'alert' : 'status'}>
      <span>{error ? '!' : '✓'}</span>{error || notice}
      <button type="button" aria-label="关闭提示" onClick={() => { setError(''); setNotice(''); }}>×</button>
    </div>}

    <section className="hub-card hub-controls" aria-labelledby="hub-controls-title">
      <h2 id="hub-controls-title" className="visually-hidden">运行设置</h2>
      <ToggleRow
        icon="✦"
        title="个性化协作"
        description="让已启用的协作偏好参与知识整理、合并规划和知识库对话"
        checked={settings.personalization_enabled}
        disabled={savingSetting !== null}
        onChange={() => updateSetting('personalization_enabled')}
      />
      <ToggleRow
        icon="↻"
        title="跨会话记忆"
        description="在新的知识库和研究对话中召回与你当前问题相关的长期记忆"
        checked={settings.long_term_memory_enabled}
        disabled={savingSetting !== null}
        onChange={() => updateSetting('long_term_memory_enabled')}
      />
      <ToggleRow
        icon="◎"
        title="自动学习"
        description="从新对话中提炼待确认的长期记忆和协作偏好；明确要求记住时立即生效"
        checked={settings.auto_learning_enabled}
        disabled={savingSetting !== null}
        onChange={() => updateSetting('auto_learning_enabled')}
      />
    </section>

    <section className="hub-overview" aria-labelledby="hub-overview-title">
      <div className="hub-section-heading">
        <div><span>OVERVIEW</span><h2 id="hub-overview-title">中枢概览</h2></div>
      </div>
      <div className="hub-metrics">
        <article><span className="metric-icon">✦</span><div><strong>{activeLongTermCount}</strong><span>长期记忆</span></div></article>
        <article><span className="metric-icon pending">◇</span><div><strong>{candidateLongTermCount}</strong><span>待确认记忆</span></div></article>
        <article><span className="metric-icon">✓</span><div><strong>{activeCount}</strong><span>生效偏好</span></div></article>
        <article><span className="metric-icon uses">↗</span><div><strong>{longTermUses + totalUses}</strong><span>累计召回与应用</span></div></article>
        <article><span className="metric-icon index">⌕</span><div><strong>{indexCounts.ready}<small>/{documents.length}</small></strong><span>索引就绪</span></div></article>
      </div>
    </section>

    <section className="hub-section" aria-labelledby="hub-trend-title">
      <div className="hub-section-heading trend-heading">
        <div><span>EVOLUTION</span><h2 id="hub-trend-title">演进动态</h2></div>
        <div className="hub-range" aria-label="趋势时间范围">
          {([7, 30, 90] as TrendRange[]).map((days) => <button
            key={days} type="button" className={range === days ? 'active' : ''}
            aria-pressed={range === days} onClick={() => setRange(days)}
          >{days === 7 ? '7 天' : days === 30 ? '30 天' : '90 天'}</button>)}
        </div>
      </div>
      <div className="hub-card hub-trend-card">
        <div className="hub-chart-legend"><span><i className="accepted" />已接受变更</span><span><i className="events" />知识变更次数</span><span><i className="memories" />记忆演进</span></div>
        <TrendChart events={events} memoryEvents={memoryEvents} range={range} />
      </div>
    </section>

    <section className="hub-system-grid" aria-label="知识库状态与备份">
      <article className="hub-card hub-system-card">
        <div className="system-card-title"><span className="hub-row-icon">⌕</span><div><h2>索引健康</h2><p>知识检索所需的文档索引状态</p></div></div>
        <div className="index-progress"><i style={{ width: `${readyPercent}%` }} /></div>
        <div className="index-breakdown">
          <span aria-label={`就绪 ${indexCounts.ready}`}><i className="ready" />就绪 <b>{indexCounts.ready}</b></span>
          <span aria-label={`处理中 ${indexCounts.pending}`}><i className="pending" />处理中 <b>{indexCounts.pending}</b></span>
          <span aria-label={`失败 ${indexCounts.failed}`}><i className="failed" />失败 <b>{indexCounts.failed}</b></span>
        </div>
        <button type="button" className="hub-secondary-button" onClick={onOpenLibrary}>前往知识库 <span>→</span></button>
      </article>
      <article className="hub-card hub-system-card">
        <div className="system-card-title"><span className="hub-row-icon">⇩</span><div><h2>知识备份</h2><p>导出带完整谱系的 AI 知识包</p></div></div>
        <p className="backup-copy">知识包包含当前文档、版本和来源信息，可用于迁移或长期留存。</p>
        <button type="button" className="hub-primary-button" disabled={exporting} onClick={handleExport}>
          {exporting ? '正在导出…' : '导出全部知识'}
        </button>
      </article>
    </section>

    <section className="hub-section hub-long-term" aria-labelledby="hub-long-term-title">
      <div className="hub-section-heading preferences-heading">
        <div><span>LONG-TERM MEMORY</span><h2 id="hub-long-term-title">长期记忆</h2><p>管理 Nerva 能够跨会话召回的人物、项目、决定和重要事实。</p></div>
        <div className="long-term-heading-actions">
          <button type="button" className="hub-secondary-button history-button" disabled={extractingHistory} onClick={extractHistory}>{extractingHistory ? '正在分析…' : '从历史提取'}</button>
          {!creatingLongTerm && <button type="button" className="hub-add-button" onClick={() => setCreatingLongTerm(true)}>＋ 添加记忆</button>}
        </div>
      </div>

      {undoMutation && <div className="hub-message success" role="status"><span>↶</span><span>刚才的记忆变更可以在 {new Date(undoMutation.expires_at).toLocaleTimeString()} 前撤销</span><button type="button" disabled={pending === 'undo-long-term'} onClick={undoLongTermChange}>撤销</button></div>}
      {candidateLongTermCount > 0 && <div className="hub-candidate-banner">
        <span>◇</span><div><b>发现 {candidateLongTermCount} 条待确认长期记忆</b><p>日常对话中发现的信息不会自动生效，请确认准确后再让 Nerva 召回。</p></div>
      </div>}

      <div className="long-term-toolbar">
        <div className="long-term-filters">
          {(['all', 'person', 'project', 'decision', 'fact'] as const).map((kind) => <button key={kind} type="button" className={longTermFilter === kind ? 'active' : ''} onClick={() => setLongTermFilter(kind)}>{kind === 'all' ? '全部' : LONG_TERM_KIND_LABELS[kind]}</button>)}
        </div>
        <input aria-label="搜索长期记忆" value={longTermQuery} onChange={(event) => setLongTermQuery(event.target.value)} placeholder="搜索主题或内容" />
      </div>

      {creatingLongTerm && <div className="hub-card memory-form hub-create-form long-term-form">
        <label>记忆类型<select value={newLongTermKind} onChange={(event) => setNewLongTermKind(event.target.value as LongTermMemoryKind)}>{(Object.keys(LONG_TERM_KIND_LABELS) as LongTermMemoryKind[]).map((kind) => <option key={kind} value={kind}>{LONG_TERM_KIND_LABELS[kind]}</option>)}</select></label>
        <label>主题<input value={newLongTermSubject} onChange={(event) => setNewLongTermSubject(event.target.value)} placeholder="例如：Nerva 项目负责人" autoFocus /></label>
        <label>记忆内容<textarea value={newLongTermContent} onChange={(event) => setNewLongTermContent(event.target.value)} placeholder="写成未来仍能独立理解的完整事实" /></label>
        <div className="actions"><button type="button" onClick={createLongTermMemory} disabled={!newLongTermSubject.trim() || !newLongTermContent.trim() || pending === 'long-term-create'}>{pending === 'long-term-create' ? '保存中…' : '保存记忆'}</button><button type="button" className="cancel" onClick={() => setCreatingLongTerm(false)}>取消</button></div>
      </div>}

      <div className="hub-memory-list">
        {visibleLongTermMemories.length === 0 && !creatingLongTerm && <div className="hub-card hub-memory-empty"><span>✦</span><b>{longTermMemories.length ? '没有符合筛选条件的记忆' : '还没有长期记忆'}</b><p>你可以手动添加，或在对话中说“请记住……”。</p></div>}
        {visibleLongTermMemories.map((memory) => <article key={memory.id} className={`hub-card hub-memory-card long-term-card ${memory.status}`}>
          <div className="memory-card-head"><div><span className="memory-kind">{LONG_TERM_KIND_LABELS[memory.kind]}</span><span className={`memory-status ${memory.status}`}>{LONG_TERM_STATUS_LABELS[memory.status]}</span></div><span className="memory-origin">{memory.source_channel === 'manual' ? '手动添加' : memory.source_channel === 'history' ? '历史对话' : memory.source_channel === 'research' ? '研究对话' : '知识库对话'}</span></div>
          {editingLongTerm === memory.id ? <div className="memory-form">
            <label>主题<input value={editLongTermSubject} onChange={(event) => setEditLongTermSubject(event.target.value)} /></label>
            <label>内容<textarea value={editLongTermContent} onChange={(event) => setEditLongTermContent(event.target.value)} /></label>
            <div className="actions"><button type="button" disabled={pending === memory.id} onClick={() => saveLongTermMemory(memory)}>保存纠正</button><button type="button" className="cancel" onClick={() => setEditingLongTerm(null)}>取消</button></div>
          </div> : <>
            <h3>{memory.subject}</h3><p className="memory-content">{memory.content}</p>
            {memory.reason && memory.status === 'candidate' && <p className="memory-reason">提取依据：{memory.reason}</p>}
            <footer><span>{memory.use_count > 0 ? `已召回 ${memory.use_count} 次` : '尚未召回'}</span><div>
              {onOpenMemorySource && memory.source_session_id && ['chat', 'research'].includes(memory.source_channel) && <button type="button" onClick={() => onOpenMemorySource(memory.source_channel as 'chat' | 'research', memory.source_session_id!)}>查看来源</button>}
              <button type="button" onClick={() => { setEditingLongTerm(memory.id); setEditLongTermSubject(memory.subject); setEditLongTermContent(memory.content); }}>纠正</button>
              {memory.status === 'candidate' && <button type="button" className="confirm" disabled={pending === memory.id} onClick={() => updateLongTermStatus(memory, 'active')}>确认记住</button>}
              {memory.status === 'candidate' && <button type="button" disabled={pending === memory.id} onClick={() => updateLongTermStatus(memory, 'suppressed')}>忽略</button>}
              <button type="button" className="delete" disabled={pending === memory.id} onClick={() => forgetLongTermMemory(memory)}>忘记</button>
            </div></footer>
          </>}
        </article>)}
      </div>
    </section>

    <section className="hub-section hub-preferences" aria-labelledby="hub-preferences-title">
      <div className="hub-section-heading preferences-heading">
        <div><span>COLLABORATION</span><h2 id="hub-preferences-title">协作偏好</h2><p>定义 Nerva 整理知识和与你协作时遵循的方式。</p></div>
        {!creating && <button type="button" className="hub-add-button" onClick={() => setCreating(true)}>＋ 添加偏好</button>}
      </div>

      {candidateCount > 0 && <div className="hub-candidate-banner">
        <span>◇</span><div><b>发现 {candidateCount} 条待确认偏好</b><p>这些偏好来自你明确提出的协作要求，确认后才会参与工作。</p></div>
      </div>}

      {creating && <div className="hub-card memory-form hub-create-form">
        <label>偏好类型<select value={newKind} onChange={(event) => setNewKind(event.target.value as MemoryKind)}>
          {(Object.keys(KIND_LABELS) as MemoryKind[]).map((kind) => <option key={kind} value={kind}>{KIND_LABELS[kind]}</option>)}
        </select></label>
        <label>偏好内容<textarea
          placeholder="例如：使用简洁的技术文档风格，保留 API 和 SDK 英文原名"
          value={newContent} onChange={(event) => setNewContent(event.target.value)} autoFocus
        /></label>
        <div className="actions"><button type="button" onClick={handleCreate} disabled={!newContent.trim() || pending === 'create'}>{pending === 'create' ? '保存中…' : '保存偏好'}</button><button type="button" className="cancel" onClick={() => { setCreating(false); setNewContent(''); }}>取消</button></div>
      </div>}

      <div className="hub-memory-list">
        {memories.length === 0 && !creating && <div className="hub-card hub-memory-empty"><span>✦</span><b>还没有协作偏好</b><p>添加偏好后，Nerva 会在知识整理和对话时遵循它们。</p><button type="button" onClick={() => setCreating(true)}>添加第一条偏好</button></div>}
        {memories.map((memory) => <article key={memory.id} className={`hub-card hub-memory-card ${memory.status}`}>
          <div className="memory-card-head"><div><span className="memory-kind">{KIND_LABELS[memory.kind]}</span><span className={`memory-status ${memory.status}`}>{STATUS_LABELS[memory.status]}</span></div><span className="memory-origin">{memory.origin === 'user_explicit' ? '手动添加' : 'Nerva 建议'}</span></div>
          {editing === memory.id ? <div className="memory-form">
            <textarea value={editContent} onChange={(event) => setEditContent(event.target.value)} autoFocus />
            <div className="actions"><button type="button" onClick={() => handleSave(memory.id)} disabled={!editContent.trim() || pending === memory.id}>{pending === memory.id ? '保存中…' : '保存'}</button><button type="button" className="cancel" onClick={() => setEditing(null)}>取消</button></div>
          </div> : <>
            <p className="memory-content">{memory.content}</p>
            <footer><span>{memory.use_count > 0 ? `已应用 ${memory.use_count} 次` : '尚未应用'}</span><div>
              <button type="button" disabled={pending === memory.id} onClick={() => startEdit(memory)}>编辑</button>
              <button type="button" className={memory.status === 'candidate' ? 'confirm' : ''} disabled={pending === memory.id} onClick={() => handleStatusToggle(memory)}>{memory.status === 'active' ? '停用' : memory.status === 'candidate' ? '确认启用' : '启用'}</button>
              <button type="button" className="delete" disabled={pending === memory.id} onClick={() => handleDelete(memory)}>删除</button>
            </div></footer>
          </>}
        </article>)}
      </div>
    </section>
  </div>;
}
