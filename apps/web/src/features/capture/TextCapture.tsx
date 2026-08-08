type Props = {
  title: string;
  content: string;
  onTitleChange: (value: string) => void;
  onContentChange: (value: string) => void;
  onGenerate: () => void;
  busy: boolean;
  draftReady: boolean;
};

export function TextCapture({
  title,
  content,
  onTitleChange,
  onContentChange,
  onGenerate,
  busy,
  draftReady,
}: Props) {
  return (
    <>
      <div className="panel editor-panel">
        <div className="panel-title">
          <span>01</span>
          <div>
            <b>输入一条新资料</b>
            <small>文字将直接进入知识提取与整合</small>
          </div>
        </div>
        <input
          value={title}
          onChange={(e) => onTitleChange(e.target.value)}
          placeholder="标题（可选）"
        />
        <textarea
          value={content}
          onChange={(e) => onContentChange(e.target.value)}
          placeholder="粘贴资料、笔记或灵感……"
        />
        <div className="editor-foot">
          <span>{content.length} 字</span>
          <button disabled={busy || content.trim().length < 2} onClick={onGenerate}>
            {busy ? '分析中…' : '生成变更草案 →'}
          </button>
        </div>
      </div>
      <div className="panel process-panel">
        <div className="panel-title">
          <span>02</span>
          <div>
            <b>知识整合流程</b>
            <small>每一步都保留来源与版本</small>
          </div>
        </div>
        {['提取原始知识', '召回相关旧文档', '规划块级变更', '等待你的确认'].map(
          (item, index) => (
            <div className="step" key={item}>
              <i>{index + 1}</i>
              <div>
                <b>{item}</b>
                <small>
                  {draftReady && index < 3
                    ? '已完成'
                    : index === 3 && draftReady
                    ? '草案已就绪'
                    : '等待输入'}
                </small>
              </div>
              <strong className={draftReady ? 'done' : ''}>
                {draftReady ? '✓' : '—'}
              </strong>
            </div>
          )
        )}
      </div>
    </>
  );
}
