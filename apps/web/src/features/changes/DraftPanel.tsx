import type { ChangeSet, SourceProcessing } from '../../lib/types';

type Props = {
  draft: ChangeSet;
  draftProcessing: SourceProcessing | null;
  selected: string[];
  busy: boolean;
  reprocessOpen: boolean;
  reprocessInstruction: string;
  onToggle: (id: string, checked: boolean) => void;
  onReprocessOpen: () => void;
  onReprocessClose: () => void;
  onReprocessInstructionChange: (value: string) => void;
  onReprocess: () => void;
  onDiscard: () => void;
  onApply: () => void;
};

export function DraftPanel({
  draft,
  draftProcessing,
  selected,
  busy,
  reprocessOpen,
  reprocessInstruction,
  onToggle,
  onReprocessOpen,
  onReprocessClose,
  onReprocessInstructionChange,
  onReprocess,
  onDiscard,
  onApply,
}: Props) {
  const reviewable = draft.status === 'proposed';
  const statusLabel = {
    applied: '已全部入库',
    partially_applied: '已按选择入库',
    rejected: '已放弃',
    superseded: '已被新草案取代',
  }[draft.status as Exclude<typeof draft.status, 'proposed'>];

  return (
    <div className="panel draft-panel">
      <div className="draft-head">
        <div>
          <span className="tag">AI 变更草案</span>
          <h2>{draft.summary}</h2>
        </div>
        <span className="safe">{reviewable ? '尚未修改知识库' : statusLabel}</span>
      </div>

      {draftProcessing && draftProcessing.total_inputs > 0 && (
        <div className="coverage-summary">
          <b>
            已覆盖 {draftProcessing.covered_inputs} / {draftProcessing.total_inputs} 张图片
          </b>
          <span>知识提取 {draftProcessing.extraction_attempts} 次</span>
          <div>
            {draftProcessing.input_coverage.map((item) => (
              <em key={item.input_index}>
                图片 {item.input_index} · {item.knowledge_unit_count} 个知识单元
              </em>
            ))}
          </div>
        </div>
      )}

      {draft.supersedes_change_set_id && (
        <div className="superseded-note">已根据你的建议生成新草案，旧草案已保留为"已取代"。</div>
      )}

      {draft.items.map((item) => (
        <label className="change" key={item.id}>
          <input
            type="checkbox"
            checked={reviewable ? selected.includes(item.id) : item.accepted === true}
            disabled={!reviewable}
            onChange={(e) => onToggle(item.id, e.target.checked)}
          />
          <div className="change-body">
            <div>
              <span className={`operation ${item.operation.toLowerCase()}`}>
                {item.operation === 'CREATE_DOCUMENT' ? '新增文档' : '自动合并'}
              </span>
              <b>{item.target_title}</b>
              <small>置信度 {Math.round(item.confidence * 100)}%</small>
            </div>
            <p>{item.reason}</p>
            <pre>{item.after}</pre>
            <details>
              <summary>查看依据</summary>
              <blockquote>{item.evidence}</blockquote>
            </details>
          </div>
        </label>
      ))}

      {reviewable && reprocessOpen && (
        <div className="reprocess-box">
          <label>
            给 AI 的组织建议（不会作为事实来源）
            <textarea
              maxLength={2000}
              value={reprocessInstruction}
              onChange={(event) => onReprocessInstructionChange(event.target.value)}
              placeholder="例如：数据库内容单独成文档，重点整理事务隔离级别"
            />
          </label>
          <small>{reprocessInstruction.length} / 2000</small>
          <div>
            <button className="secondary" disabled={busy} onClick={onReprocessClose}>
              取消
            </button>
            <button disabled={busy} onClick={onReprocess}>
              {busy ? '重新分析中…' : '开始重新分析'}
            </button>
          </div>
        </div>
      )}

      <div className="draft-actions">
        {reviewable ? <>
          <button className="secondary" disabled={busy} onClick={onReprocessOpen}>
            重新分析
          </button>
          <button className="secondary" onClick={onDiscard}>
            放弃草案
          </button>
          <button disabled={busy || selected.length === 0} onClick={onApply}>
            接受 {selected.length} 项变更
          </button>
        </> : <button className="secondary" onClick={onDiscard}>关闭入库结果</button>}
      </div>
    </div>
  );
}
