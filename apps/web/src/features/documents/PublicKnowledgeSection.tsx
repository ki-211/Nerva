import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ApiError, api } from '../../lib/api';
import type { Document } from '../../lib/types';
import { MarkdownView } from './knowledgeViews';
import './PublicKnowledgeSection.css';

const PAGE_SIZE = 8;

type Props = {
  documentId: string | null;
  onAuthError: () => void;
};

export function PublicKnowledgeSection({ documentId, onAuthError }: Props) {
  const navigate = useNavigate();
  const [documents, setDocuments] = useState<Document[]>([]);
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const selected = documents.find((document) => document.id === documentId) || null;
  const filtered = useMemo(() => {
    const keyword = query.trim().toLocaleLowerCase();
    if (!keyword) return documents;
    return documents.filter((document) =>
      `${document.title}\n${document.markdown}`.toLocaleLowerCase().includes(keyword),
    );
  }, [documents, query]);
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const pageDocuments = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  useEffect(() => {
    api.publicDocuments()
      .then(setDocuments)
      .catch((cause) => {
        if (cause instanceof ApiError && cause.status === 401) return onAuthError();
        setError(cause instanceof Error ? cause.message : '大众知识库加载失败');
      })
      .finally(() => setLoading(false));
  }, [onAuthError]);

  useEffect(() => {
    if (!selected) return;
    window.requestAnimationFrame(() => {
      document.getElementById('public-knowledge-detail')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }, [selected?.id]);

  useEffect(() => {
    setPage(1);
  }, [query]);

  useEffect(() => {
    if (page > pageCount) setPage(pageCount);
  }, [page, pageCount]);

  const open = (id: string) => {
    navigate(`/?public_document=${encodeURIComponent(id)}#public-knowledge`);
  };

  return (
    <section className="public-knowledge" id="public-knowledge">
      <header className="public-knowledge-header">
        <div>
          <span className="eyebrow">PUBLIC KNOWLEDGE · 大众知识库</span>
          <h2>大家都能阅读的技术知识</h2>
          <p>由管理员维护。点击任意文章卡片，即可在当前页面查看完整内容。</p>
        </div>
        <strong>{documents.length} 篇</strong>
      </header>

      <label className="public-knowledge-search">
        <span>⌕</span>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索大众知识库"
        />
      </label>

      {loading && <div className="public-knowledge-state">正在加载大众知识库…</div>}
      {error && <div className="public-knowledge-state error-state">{error}</div>}
      {!loading && !error && (
        <div className="public-knowledge-grid">
          {pageDocuments.map((item, index) => (
            <button
              key={item.id}
              className={item.id === selected?.id ? 'active' : ''}
              onClick={() => open(item.id)}
            >
              <span className="public-card-number">
                {String((page - 1) * PAGE_SIZE + index + 1).padStart(2, '0')}
              </span>
              <span className="public-card-body">
                <b>{item.title}</b>
                <small>{item.markdown.replace(/[#>*`\[\]]/g, '').replace(/\s+/g, ' ').slice(0, 92)}</small>
              </span>
              <span className="public-card-arrow">查看详情 →</span>
            </button>
          ))}
        </div>
      )}

      {!loading && !error && filtered.length > PAGE_SIZE && (
        <nav className="public-pagination" aria-label="大众知识库分页">
          <button
            className="secondary"
            disabled={page === 1}
            onClick={() => setPage((current) => Math.max(1, current - 1))}
          >
            ← 上一页
          </button>
          <div>
            {Array.from({ length: pageCount }, (_, index) => index + 1).map((pageNumber) => (
              <button
                key={pageNumber}
                className={pageNumber === page ? 'active' : 'secondary'}
                aria-current={pageNumber === page ? 'page' : undefined}
                onClick={() => setPage(pageNumber)}
              >
                {pageNumber}
              </button>
            ))}
          </div>
          <button
            className="secondary"
            disabled={page === pageCount}
            onClick={() => setPage((current) => Math.min(pageCount, current + 1))}
          >
            下一页 →
          </button>
        </nav>
      )}

      {selected && (
        <article className="public-knowledge-detail" id="public-knowledge-detail">
          <div className="public-detail-toolbar">
            <div>
              <span>大众知识库 · v{selected.version}</span>
              <h2>{selected.title}</h2>
              <small>更新于 {new Date(selected.updated_at).toLocaleString('zh-CN')}</small>
            </div>
            <button className="secondary" onClick={() => navigate('/#public-knowledge')}>
              收起详情
            </button>
          </div>
          <MarkdownView markdown={selected.markdown} />
        </article>
      )}
    </section>
  );
}
