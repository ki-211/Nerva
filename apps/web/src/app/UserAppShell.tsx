import { useCallback } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import type { User } from '../lib/types';
import { clientLogger, exportDiagnosticLogs } from '../lib/clientLogger';
import './AppShell.css';

type Props = {
  user: User;
  documentCount: number;
  eventCount: number;
  libraryDirty: boolean;
  onSignOut: () => void;
  children: React.ReactNode;
};

export function UserAppShell({ user, documentCount, eventCount, libraryDirty, onSignOut, children }: Props) {
  const navigate = useNavigate();
  const location = useLocation();
  const view = location.pathname.startsWith('/research') ? 'research'
    : location.pathname.startsWith('/search') ? 'search'
    : location.pathname.startsWith('/library') ? 'library'
    : location.pathname.startsWith('/chat') ? 'chat'
    : location.pathname.startsWith('/growth') ? 'growth'
    : location.pathname.startsWith('/memories') ? 'memories' : 'capture';
  const go = useCallback((path: string) => {
    if (libraryDirty && !window.confirm('当前文档还有未保存的修改，确定离开吗？')) return;
    navigate(path);
  }, [libraryDirty, navigate]);

  return <div className="app-shell">
    <aside>
      <div className="brand"><span className="brand-mark">N</span><div><b>Nerva</b><small>个人知识操作系统</small></div></div>
      <button className="new" onClick={() => go('/')}>＋ 快速记录</button>
      <nav>
        <button className={view === 'capture' ? 'active' : ''} onClick={() => go('/')}>✦ 知识录入</button>
        <button className={view === 'research' ? 'active' : ''} onClick={() => go('/research')}>◈ 知识获取</button>
        <button className={view === 'chat' ? 'active' : ''} onClick={() => go('/chat')}>● 与知识库对话</button>
        <button className={view === 'search' ? 'active' : ''} onClick={() => go('/search')}>⌕ 知识检索</button>
        <button className={view === 'library' ? 'active' : ''} onClick={() => go('/library')}>▤ 知识库 <em>{documentCount}</em></button>
        <button className={view === 'growth' ? 'active' : ''} onClick={() => go('/growth')}>↗ 成长日志 <em>{eventCount}</em></button>
        <button className={view === 'memories' ? 'active' : ''} onClick={() => go('/memories')}>✧ 个性化偏好</button>
      </nav>
      <div className="account"><span>{user.display_name.slice(0, 2).toUpperCase()}</span><div><b>{user.display_name}</b><small>{user.email}</small></div><button onClick={onSignOut}>退出</button></div>
      <div className="side-note"><i /> Nerva 服务已连接<br /><span>PostgreSQL · 两阶段知识整合</span><br />
        <button type="button" onClick={() => exportDiagnosticLogs().catch((cause) => {
          if ((cause as DOMException)?.name !== 'AbortError') clientLogger.error('diagnostic_export_failed', cause, { operation: 'diagnostics.export' });
        })}>导出诊断日志</button>
      </div>
    </aside>
    <main>{children}</main>
  </div>;
}
