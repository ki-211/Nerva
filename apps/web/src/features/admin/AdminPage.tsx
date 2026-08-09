import { useEffect, useState } from 'react';
import { ApiError, api } from '../../lib/api';
import type { AdminUser, Document, KnowledgeOwnership, User } from '../../lib/types';
import { MarkdownView } from '../documents/knowledgeViews';
import { PublicLibraryPage } from '../documents/PublicLibraryPage';
import './admin.css';

type Props = {
  user: User;
  onAuthError: () => void;
};

export function AdminPage({ user, onAuthError }: Props) {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [ownership, setOwnership] = useState<KnowledgeOwnership[]>([]);
  const [publicDocumentId, setPublicDocumentId] = useState<string | null>(null);
  const [selectedOwnership, setSelectedOwnership] = useState<KnowledgeOwnership | null>(null);
  const [selectedDocument, setSelectedDocument] = useState<Document | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    Promise.all([api.adminUsers(), api.knowledgeOwnership()])
      .then(([nextUsers, nextOwnership]) => {
        setUsers(nextUsers);
        setOwnership(nextOwnership);
      })
      .catch((cause) => {
        if (cause instanceof ApiError && (cause.status === 401 || cause.status === 403)) {
          return onAuthError();
        }
        setError(cause instanceof Error ? cause.message : '管理员数据加载失败');
      });
  }, [onAuthError]);

  const openDocument = async (item: KnowledgeOwnership) => {
    setSelectedOwnership(item);
    setSelectedDocument(null);
    setDetailError('');
    setDetailLoading(true);
    try {
      setSelectedDocument(await api.adminDocument(item.id));
    } catch (cause) {
      if (cause instanceof ApiError && (cause.status === 401 || cause.status === 403)) {
        onAuthError();
        return;
      }
      setDetailError(cause instanceof Error ? cause.message : '文档详情加载失败');
    } finally {
      setDetailLoading(false);
    }
  };

  const closeDocument = () => {
    setSelectedOwnership(null);
    setSelectedDocument(null);
    setDetailError('');
  };

  return (
    <section className="admin-page">
      <header>
        <span>ADMIN CONSOLE</span>
        <h1>管理员控制台</h1>
        <p>查看用户、知识库归属和公开状态。普通用户无法访问此页面。</p>
      </header>

      {error && <div className="admin-error">{error}</div>}

      <div className="admin-stats">
        <article><b>{users.length}</b><span>用户</span></article>
        <article><b>{ownership.length}</b><span>知识文档</span></article>
        <article><b>{ownership.filter((item) => item.visibility === 'public').length}</b><span>公开文档</span></article>
      </div>

      <section className="admin-panel">
        <h2>全部用户</h2>
        <div className="admin-table">
          <div className="admin-row head"><span>用户</span><span>角色</span><span>状态</span><span>文档</span></div>
          {users.map((item) => (
            <div className="admin-row" key={item.id}>
              <span><b>{item.display_name}</b><small>{item.email}</small></span>
              <span>{item.role === 'admin' ? '管理员' : '普通用户'}</span>
              <span>{item.status === 'active' ? '正常' : '停用'}</span>
              <span>{item.document_count}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="admin-panel">
        <div className="admin-panel-heading">
          <div><h2>知识库归属</h2><p>点击任意文档行查看完整正文和归属信息。</p></div>
        </div>
        <div className="admin-table">
          <div className="admin-row ownership head"><span>文档</span><span>归属</span><span>范围</span><span>版本</span></div>
          {ownership.map((item) => (
            <button
              type="button"
              className="admin-row ownership data-row"
              key={item.id}
              onClick={() => openDocument(item)}
            >
              <span><b>{item.title}</b><small>{new Date(item.updated_at).toLocaleString('zh-CN')}</small></span>
              <span>{item.owner_display_name}<small>{item.owner_email}</small></span>
              <span>{item.visibility === 'public' ? '大众知识库' : '私有'}</span>
              <span>v{item.version}<small>查看详情 →</small></span>
            </button>
          ))}
        </div>
      </section>

      <section className="admin-panel public-document-admin">
        <h2>大众知识库维护</h2>
        <p>在这里新增、编辑或下架知识录入页下方展示的公共文章。</p>
        <PublicLibraryPage
          user={user}
          documentId={publicDocumentId}
          onOpen={(id) => setPublicDocumentId(id || null)}
          onAuthError={onAuthError}
        />
      </section>

      {selectedOwnership && (
        <div className="admin-detail-backdrop" onMouseDown={(event) => {
          if (event.target === event.currentTarget) closeDocument();
        }}>
          <section className="admin-document-detail" role="dialog" aria-modal="true" aria-labelledby="admin-detail-title">
            <div className="admin-detail-header">
              <div>
                <span className={`admin-visibility ${selectedOwnership.visibility}`}>
                  {selectedOwnership.visibility === 'public' ? '大众知识库' : '用户私有文档'}
                </span>
                <h2 id="admin-detail-title">{selectedOwnership.title}</h2>
                <p>
                  归属：{selectedOwnership.owner_display_name}（{selectedOwnership.owner_email}）
                  · v{selectedOwnership.version}
                </p>
              </div>
              <button type="button" className="secondary" onClick={closeDocument}>关闭</button>
            </div>
            <div className="admin-detail-body">
              {detailLoading && <div className="admin-detail-state">正在加载文档详情…</div>}
              {detailError && <div className="admin-error">{detailError}</div>}
              {selectedDocument && <MarkdownView markdown={selectedDocument.markdown} />}
            </div>
            {selectedOwnership.visibility === 'private' && (
              <div className="admin-private-note">管理员仅可查看归属用户的私有文档，不能在此修改。</div>
            )}
          </section>
        </div>
      )}
    </section>
  );
}
