import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from './api';
import { MarkdownView } from './knowledgeViews';
import type { Document } from './types';
import './exportViews.css';


export function PrintExportPage() {
  const [params] = useSearchParams();
  const scope = params.get('scope');
  const documentId = params.get('document_id');
  const requestedVersion = params.get('version');
  const version = requestedVersion ? Number(requestedVersion) : null;
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const autoPrinted = useRef(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        if (scope === 'library') {
          if (documentId || requestedVersion) throw new Error('全部导出不接受文档或版本参数');
          const result = await api.documents();
          if (!cancelled) setDocuments([...result].sort((a, b) => a.title.localeCompare(b.title, 'zh-CN')));
        } else if (scope === 'document' && documentId) {
          const current = await api.document(documentId);
          if (version == null || version === current.version) {
            if (!cancelled) setDocuments([current]);
          } else {
            const historical = (await api.documentVersions(documentId)).find((item) => item.version === version);
            if (!historical) throw new Error(`找不到文档版本 v${version}`);
            if (!cancelled) setDocuments([{
              ...current, title: historical.title, markdown: historical.markdown,
              version: historical.version, updated_at: historical.created_at,
            }]);
          }
        } else {
          throw new Error('导出参数无效');
        }
      } catch (reason) {
        if (!cancelled) setError(reason instanceof Error ? reason.message : '打印内容加载失败');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [scope, documentId, requestedVersion, version]);

  useEffect(() => {
    if (loading || error || autoPrinted.current) return;
    autoPrinted.current = true;
    const pageTitle = scope === 'library' ? 'Nerva 知识库' : documents[0]?.title || 'Nerva 文档';
    window.document.title = `${pageTitle} - 打印`;
    const printWhenReady = async () => {
      await window.document.fonts?.ready;
      window.setTimeout(() => window.print(), 350);
    };
    printWhenReady();
  }, [loading, error, documents, scope]);

  return <main className="print-page">
    <div className="print-controls"><div><b>PDF 导出预览</b><span>在打印窗口中选择“另存为 PDF”</span></div><button onClick={() => window.print()} disabled={loading || Boolean(error)}>打印 / 另存为 PDF</button></div>
    {loading && <div className="print-state">正在准备排版…</div>}
    {error && <div className="print-state error">{error}</div>}
    {!loading && !error && scope === 'library' && <>
      <section className="print-cover"><span>NERVA · KNOWLEDGE LIBRARY</span><h1>个人知识库</h1><p>导出时间：{new Date().toLocaleString('zh-CN')}</p><p>共 {documents.length} 篇正式知识文档</p></section>
      <section className="print-index"><h1>文档目录</h1>{documents.length ? <ol>{documents.map((item) => <li key={item.id}>{item.title}<span>v{item.version}</span></li>)}</ol> : <p>知识库当前为空。</p>}</section>
    </>}
    {!loading && !error && documents.map((item) => <article className="print-document" key={`${item.id}-${item.version}`}>
      <header><div><span>正式知识文档 · v{item.version}</span><h1>{item.title}</h1></div><time>{new Date(item.updated_at).toLocaleString('zh-CN')}</time></header>
      <MarkdownView markdown={item.markdown}/>
    </article>)}
  </main>;
}
