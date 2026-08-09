import { useEffect, useState } from 'react';
import { adminApi } from '../../lib/adminApi';
import type { AdminUser, KnowledgeOwnership, User } from '../../lib/types';
import { PublicLibraryPage } from '../documents/PublicLibraryPage';
import './admin.css';

type Props = {
  user: User;
};

export function AdminPage({ user }: Props) {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [ownership, setOwnership] = useState<KnowledgeOwnership[]>([]);
  const [publicDocumentId, setPublicDocumentId] = useState<string | null>(null);
  const [selectedOwnership, setSelectedOwnership] = useState<KnowledgeOwnership | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    Promise.all([adminApi.users(), adminApi.knowledgeOwnership()])
      .then(([nextUsers, nextOwnership]) => {
        setUsers(nextUsers);
        setOwnership(nextOwnership);
      })
      .catch((cause) => {
        setError(cause instanceof Error ? cause.message : '管理员数据加载失败');
      });
  }, []);

  const closeDocument = () => setSelectedOwnership(null);

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
          <div><h2>知识库归属</h2><p>仅展示标题、归属、版本和状态；管理员不能读取普通用户私有正文。</p></div>
        </div>
        <div className="admin-table">
          <div className="admin-row ownership head"><span>文档</span><span>归属</span><span>范围</span><span>版本</span></div>
          {ownership.map((item) => (
            <button
              type="button"
              className="admin-row ownership data-row"
              key={item.id}
              onClick={() => setSelectedOwnership(item)}
            >
              <span><b>{item.title}</b><small>{new Date(item.updated_at).toLocaleString('zh-CN')}</small></span>
              <span>{item.owner_display_name}<small>{item.owner_email}</small></span>
              <span>{item.visibility === 'public' ? '大众知识库' : '私有'}<small>{item.index_status === 'ready' ? '索引完成' : item.index_status === 'failed' ? '索引失败·关键词可用' : '索引处理中'}</small></span>
              <span>v{item.version}<small>查看元数据 →</small></span>
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
            <div className="admin-detail-body admin-metadata-only">
              <dl>
                <dt>文档 ID</dt><dd>{selectedOwnership.id}</dd>
                <dt>用户 ID</dt><dd>{selectedOwnership.user_id}</dd>
                <dt>创建时间</dt><dd>{new Date(selectedOwnership.created_at).toLocaleString('zh-CN')}</dd>
                <dt>更新时间</dt><dd>{new Date(selectedOwnership.updated_at).toLocaleString('zh-CN')}</dd>
              </dl>
              <div className="admin-private-note">
                正文未传输到管理端。大众知识正文仅通过下方“大众知识库维护”读取和编辑。
              </div>
            </div>
          </section>
        </div>
      )}
    </section>
  );
}
