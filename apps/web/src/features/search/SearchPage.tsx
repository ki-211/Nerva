import { FormEvent, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ApiError, api } from '../../lib/api';
import type { SearchResponse } from '../../lib/types';
import './search.css';

type Props = {
  onOpenDocument: (documentId: string, visibility: 'private' | 'public') => void;
  onAuthError: () => void;
};

export function SearchPage({ onOpenDocument, onAuthError }: Props) {
  const [query, setQuery] = useState('');
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [includePublic, setIncludePublic] = useState(true);
  const inputRef = useRef<HTMLInputElement>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const normalized = query.trim();
    if (!normalized || loading) {
      inputRef.current?.focus();
      return;
    }
    setLoading(true);
    setError('');
    try {
      setResponse(await api.search(normalized, 8, includePublic));
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        onAuthError();
        return;
      }
      setError(cause instanceof Error ? cause.message : '检索失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  };

  const modeLabel = response?.retrieval_mode === 'hybrid'
    ? '混合检索'
    : response?.retrieval_mode === 'keyword'
    ? '关键词检索'
    : '未找到结果';

  return (
    <section className="search-page">
      <header className="search-hero">
        <span className="search-eyebrow">KNOWLEDGE RETRIEVAL</span>
        <h1>知识检索</h1>
        <p>从正式知识中查找最相关的内容片段，并直接回到原文继续阅读。</p>
        <form className="search-form" onSubmit={submit}>
          <span aria-hidden="true">⌕</span>
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="输入问题、主题或关键词"
            maxLength={4000}
            aria-label="知识检索问题"
          />
          <button type="submit" disabled={loading || !query.trim()}>
            {loading ? '检索中…' : '检索'}
          </button>
        </form>
        <small>检索范围仅包含当前账号已经确认的正式知识。</small>
        <label className="search-public-toggle"><input type="checkbox" checked={includePublic} onChange={(event) => setIncludePublic(event.target.checked)} /> 包含大众知识库</label>
      </header>

      {error && <div className="search-error">{error}</div>}

      {!response && !loading && !error && (
        <div className="search-welcome">
          <span>⌕</span>
          <h2>寻找知识，而不是翻找文件</h2>
          <p>可以直接输入完整问题，例如“Orion 服务使用哪个端口？”</p>
        </div>
      )}

      {response && (
        <div className="search-results">
          <div className="search-summary">
            <div>
              <span>检索结果</span>
              <b>{response.items.length ? `找到 ${response.items.length} 条相关内容` : '没有找到相关内容'}</b>
            </div>
            <em className={`mode-${response.retrieval_mode}`}>{modeLabel}</em>
          </div>

          {response.items.length === 0 ? (
            <div className="search-empty">
              <h2>知识库里暂时没有匹配内容</h2>
              <p>尝试换一种说法、减少限定词，或先录入相关知识。</p>
            </div>
          ) : (
            <div className="search-result-list">
              {response.items.map((item, index) => (
                <article className="search-result-card" key={item.chunk_id}>
                  <div className="search-result-main">
                    <span className="result-number">{String(index + 1).padStart(2, '0')}</span>
                    <div>
                      <div className="result-title-row">
                        <h2>{item.title}</h2>
                        <small>{item.visibility === 'public' ? '大众知识库 · ' : ''}v{item.document_version}</small>
                      </div>
                      <div className="search-excerpt markdown-body">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{item.excerpt}</ReactMarkdown>
                      </div>
                      <button className="open-document" onClick={() => onOpenDocument(item.document_id, item.visibility)}>
                        打开完整文档 →
                      </button>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
