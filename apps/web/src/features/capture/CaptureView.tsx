import { useCallback, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ApiError, api } from '../../lib/api';
import type { ChangeSet, Document, KnowledgeEvent, SourceProcessing } from '../../lib/types';
import { ImageCapture } from './imageCapture';
import { TextCapture } from './TextCapture';
import { DraftPanel } from '../changes/DraftPanel';
import { PublicKnowledgeSection } from '../documents/PublicKnowledgeSection';
import './CaptureView.css';

type Props = {
  publicDocumentId: string | null;
  onRefresh: (docs: Document[], events: KnowledgeEvent[]) => void;
};

export function CaptureView({ publicDocumentId, onRefresh }: Props) {
  const navigate = useNavigate();
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [captureMode, setCaptureMode] = useState<'text' | 'image'>('text');
  const [draft, setDraft] = useState<ChangeSet | null>(null);
  const [draftProcessing, setDraftProcessing] = useState<SourceProcessing | null>(null);
  const [reprocessOpen, setReprocessOpen] = useState(false);
  const [reprocessInstruction, setReprocessInstruction] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [failedSourceId, setFailedSourceId] = useState<string | null>(null);

  const handleError = useCallback(
    (e: unknown, fallback: string) => {
      if (e instanceof ApiError && e.sourceId && e.retryable) {
        setFailedSourceId(e.sourceId);
      }
      setError(e instanceof Error ? e.message : fallback);
    },
    []
  );

  const waitForSource = async (initial: SourceProcessing): Promise<ChangeSet> => {
    let current = initial;
    while (current.status === 'received' || current.status === 'processing') {
      setDraftProcessing(current);
      await new Promise((resolve) => window.setTimeout(resolve, 1500));
      current = await api.sourceProcessing(current.source_id);
    }
    setDraftProcessing(current);
    if (current.status === 'failed') {
      throw new ApiError(
        current.error?.message || '重新分析失败',
        400,
        current.error?.code,
        current.source_id,
        current.error?.retryable,
        undefined,
        current.error?.requires_reupload,
        current.source_id,
      );
    }
    if (!current.change_set_id) throw new ApiError('处理完成但没有生成草案', 500, 'CHANGE_SET_MISSING');
    return api.changeSet(current.change_set_id);
  };

  const generate = async () => {
    if (content.trim().length < 2) return;
    setBusy(true);
    setError('');
    setFailedSourceId(null);
    try {
      const result = await api.createIngestion(content, title);
      setDraft(result);
      setDraftProcessing(null);
      setSelected(result.items.map((item) => item.id));
    } catch (e) {
      handleError(e, '生成失败');
    } finally {
      setBusy(false);
    }
  };

  const retry = async () => {
    if (!failedSourceId) return;
    setBusy(true);
    setError('');
    try {
      const result = await api.retrySource(failedSourceId);
      const completed = 'items' in result ? result : await waitForSource(result);
      setDraft(completed);
      setSelected(completed.items.map((item) => item.id));
      setFailedSourceId(null);
    } catch (e) {
      handleError(e, '重试失败');
    } finally {
      setBusy(false);
    }
  };

  const reprocess = async () => {
    if (!draft?.source_id || busy) return;
    const previousProcessing = draftProcessing;
    setBusy(true);
    setError('');
    setFailedSourceId(null);
    try {
      const initial = await api.reprocessSource(draft.source_id, reprocessInstruction);
      const replacement = await waitForSource(initial);
      setDraft(replacement);
      setSelected(replacement.items.map((item) => item.id));
      setReprocessInstruction('');
      setReprocessOpen(false);
    } catch (e) {
      setDraftProcessing(previousProcessing);
      handleError(e, '重新分析失败，原草案仍然可用');
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    if (!draft) return;
    setBusy(true);
    setError('');
    try {
      await api.applyChangeSet(draft.id, selected);
      const [docs, events] = await Promise.all([api.documents(), api.events()]);
      onRefresh(docs, events);
      setDraft(null);
      setDraftProcessing(null);
      setContent('');
      setTitle('');
      navigate('/growth');
    } catch (e) {
      handleError(e, '提交失败');
    } finally {
      setBusy(false);
    }
  };

  const toggleItem = (id: string, checked: boolean) => {
    setSelected((prev) => (checked ? [...prev, id] : prev.filter((x) => x !== id)));
  };

  return (
    <section className="capture-view">
      <header className="capture-header">
        <div>
          <span className="eyebrow">NERVA · KNOWLEDGE GROWTH</span>
          <h1>让新输入，真正长进旧知识里</h1>
        </div>
        <div className="status">● 系统就绪</div>
      </header>

      <div className="capture-layout">
        <div className="capture-mode-tabs">
          <button
            className={captureMode === 'text' ? 'active' : ''}
            onClick={() => setCaptureMode('text')}
          >
            文字输入
          </button>
          <button
            className={captureMode === 'image' ? 'active' : ''}
            onClick={() => setCaptureMode('image')}
          >
            图片输入
          </button>
        </div>

        {captureMode === 'text' ? (
          <TextCapture
            title={title}
            content={content}
            onTitleChange={setTitle}
            onContentChange={setContent}
            onGenerate={generate}
            busy={busy}
            draftReady={Boolean(draft)}
          />
        ) : (
          <ImageCapture
            title={title}
            note={content}
            onTitleChange={setTitle}
            onNoteChange={setContent}
            onDraft={(result, processing) => {
              setDraft(result);
              setDraftProcessing(processing);
              setSelected(result.items.map((item) => item.id));
              setError('');
            }}
            onError={(cause) => handleError(cause, '图片处理失败')}
          />
        )}

        {draft && (
          <DraftPanel
            draft={draft}
            draftProcessing={draftProcessing}
            selected={selected}
            busy={busy}
            reprocessOpen={reprocessOpen}
            reprocessInstruction={reprocessInstruction}
            onToggle={toggleItem}
            onReprocessOpen={() => setReprocessOpen(true)}
            onReprocessClose={() => setReprocessOpen(false)}
            onReprocessInstructionChange={setReprocessInstruction}
            onReprocess={reprocess}
            onDiscard={() => {
              setDraft(null);
              setDraftProcessing(null);
            }}
            onApply={apply}
          />
        )}

        {error && (
          <div className="error">
            {error}
            {failedSourceId && (
              <button disabled={busy} onClick={retry}>
                {busy ? '重试中…' : '重试这条来源'}
              </button>
            )}
          </div>
        )}
      </div>
      <PublicKnowledgeSection documentId={publicDocumentId} />
    </section>
  );
}
