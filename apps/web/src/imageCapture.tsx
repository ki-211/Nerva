import { ChangeEvent, DragEvent, useEffect, useRef, useState } from 'react';
import { ApiError, api } from './api';
import type { ChangeSet, SourceProcessing } from './types';
import './imageCapture.css';

type SelectedImage = { id: string; file: File; previewUrl: string };

type Props = {
  title: string;
  note: string;
  onTitleChange: (value: string) => void;
  onNoteChange: (value: string) => void;
  onDraft: (draft: ChangeSet, processing: SourceProcessing) => void;
  onError: (error: unknown) => void;
};

const MAX_FILE_BYTES = 6 * 1024 * 1024;
const MAX_BATCH_BYTES = 30 * 1024 * 1024;
const ALLOWED_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp']);

const stageIndex: Record<SourceProcessing['stage'], number> = {
  queued: 0, ocr: 1, extracting: 2, coverage_repair: 3, retrieving: 4, planning: 5, complete: 6, failed: -1,
};

export function ImageCapture({
  title, note, onTitleChange, onNoteChange, onDraft, onError,
}: Props) {
  const [images, setImages] = useState<SelectedImage[]>([]);
  const imagesRef = useRef<SelectedImage[]>([]);
  const stopped = useRef(false);
  const [busy, setBusy] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [processing, setProcessing] = useState<SourceProcessing | null>(null);
  const [localError, setLocalError] = useState('');

  useEffect(() => { imagesRef.current = images; }, [images]);
  useEffect(() => () => {
    stopped.current = true;
    imagesRef.current.forEach((image) => URL.revokeObjectURL(image.previewUrl));
  }, []);

  const clearImages = () => {
    imagesRef.current.forEach((image) => URL.revokeObjectURL(image.previewUrl));
    imagesRef.current = [];
    setImages([]);
  };

  const addFiles = (incoming: File[]) => {
    setLocalError('');
    const combined = [...images.map((image) => image.file), ...incoming];
    if (combined.length > 10) { setLocalError('一次最多选择 10 张图片'); return; }
    if (incoming.some((file) => !ALLOWED_TYPES.has(file.type))) {
      setLocalError('仅支持 JPG、PNG 和 WebP 图片'); return;
    }
    if (incoming.some((file) => file.size > MAX_FILE_BYTES)) {
      setLocalError('单张图片不能超过 6 MB'); return;
    }
    if (combined.reduce((total, file) => total + file.size, 0) > MAX_BATCH_BYTES) {
      setLocalError('一批图片总大小不能超过 30 MB'); return;
    }
    const selected = incoming.map((file) => ({
      id: crypto.randomUUID(), file, previewUrl: URL.createObjectURL(file),
    }));
    setImages((current) => [...current, ...selected]);
  };

  const chooseFiles = (event: ChangeEvent<HTMLInputElement>) => {
    addFiles(Array.from(event.target.files || []));
    event.target.value = '';
  };

  const dropFiles = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    if (!busy) addFiles(Array.from(event.dataTransfer.files));
  };

  const remove = (id: string) => setImages((current) => {
    const target = current.find((image) => image.id === id);
    if (target) URL.revokeObjectURL(target.previewUrl);
    return current.filter((image) => image.id !== id);
  });

  const move = (index: number, direction: -1 | 1) => setImages((current) => {
    const nextIndex = index + direction;
    if (nextIndex < 0 || nextIndex >= current.length) return current;
    const next = [...current];
    [next[index], next[nextIndex]] = [next[nextIndex], next[index]];
    return next;
  });

  const waitForResult = async (initial: SourceProcessing) => {
    let current = initial;
    while (!stopped.current) {
      setProcessing(current);
      if (current.status === 'proposed' && current.change_set_id) {
        const draft = await api.changeSet(current.change_set_id);
        onDraft(draft, current);
        clearImages();
        return;
      }
      if (current.status === 'failed') {
        if (current.error?.requires_reupload) clearImages();
        throw new ApiError(
          current.error?.message || '图片处理失败', 400, current.error?.code,
          current.source_id, current.error?.retryable,
          undefined, current.error?.requires_reupload,
        );
      }
      await new Promise((resolve) => window.setTimeout(resolve, 1500));
      current = await api.sourceProcessing(current.source_id);
    }
  };

  const submit = async () => {
    if (images.length === 0 || busy) return;
    stopped.current = false;
    setBusy(true); setUploadProgress(0); setLocalError(''); setProcessing(null);
    try {
      const result = await api.uploadImages(
        images.map((image) => image.file), title, note, setUploadProgress,
      );
      await waitForResult(result);
    } catch (error) {
      if (error instanceof ApiError && error.requiresReupload) clearImages();
      onError(error);
    } finally {
      setBusy(false);
    }
  };

  const currentStage = processing ? stageIndex[processing.stage] : -1;
  const steps = ['上传完成', '识别图片文字', '提取知识单元', '检查并补提遗漏', '召回旧文档', '规划变更', '等待审批'];

  return <>
    <div className="panel editor-panel image-editor-panel">
      <div className="panel-title"><span>01</span><div><b>上传文字资料图片</b><small>图片只用于临时 OCR，处理结束后立即删除</small></div></div>
      <input value={title} onChange={(event) => onTitleChange(event.target.value)} placeholder="标题（可选）" />
      <textarea value={note} onChange={(event) => onNoteChange(event.target.value)} placeholder="补充说明（可选）" />
      <label className={`image-dropzone ${busy ? 'disabled' : ''}`} onDragOver={(event) => event.preventDefault()} onDrop={dropFiles}>
        <input type="file" accept="image/jpeg,image/png,image/webp" multiple disabled={busy} onChange={chooseFiles} />
        <b>拖拽图片到这里，或点击选择</b>
        <small>JPG / PNG / WebP · 最多 10 张 · 单张 6 MB</small>
      </label>
      {images.length > 0 && <div className="image-grid">{images.map((image, index) => <article key={image.id}>
        <img src={image.previewUrl} alt={`待识别图片 ${index + 1}`} />
        <span>{index + 1}</span>
        <div><button disabled={busy || index === 0} onClick={() => move(index, -1)}>↑</button><button disabled={busy || index === images.length - 1} onClick={() => move(index, 1)}>↓</button><button disabled={busy} onClick={() => remove(image.id)}>×</button></div>
      </article>)}</div>}
      {localError && <div className="image-local-error">{localError}</div>}
      <div className="editor-foot"><span>{images.length} / 10 张</span><button disabled={busy || images.length === 0} onClick={submit}>{busy ? '处理中…' : '上传并生成草案 →'}</button></div>
      {busy && uploadProgress < 100 && <div className="upload-progress"><i style={{ width: `${uploadProgress}%` }} /><span>上传 {uploadProgress}%</span></div>}
    </div>
    <div className="panel process-panel image-process-panel">
      <div className="panel-title"><span>02</span><div><b>图片知识整合流程</b><small>后台处理期间可以看到真实阶段</small></div></div>
      {steps.map((step, index) => {
        const done = processing?.status === 'proposed' || currentStage > index || (index === 0 && processing !== null);
        const active = processing?.status === 'processing' && currentStage === index;
        const detail = index === 1 && processing
          ? `${processing.processed_inputs} / ${processing.total_inputs} 张`
          : index === 3 && processing?.stage === 'coverage_repair'
            ? `已覆盖 ${processing.covered_inputs} / ${processing.total_inputs} 张，正在补提`
            : done ? '已完成' : active ? '处理中' : '等待';
        return <div className="step" key={step}><i>{index + 1}</i><div><b>{step}</b><small>{detail}</small></div><strong className={done ? 'done' : ''}>{done ? '✓' : active ? '…' : '—'}</strong></div>;
      })}
    </div>
  </>;
}
