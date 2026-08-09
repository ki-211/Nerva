import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { api } from './lib/api';
import { ApiError, displayError } from './lib/errors';
import { clientLogger, initializeClientMonitoring } from './lib/clientLogger';
import type { Document, KnowledgeEvent, User } from './lib/types';
import { AuthPage } from './features/auth/AuthPage';
import { AppShell } from './app/AppShell';
import { CaptureView } from './features/capture/CaptureView';
import { LibraryView, GrowthView } from './features/documents/knowledgeViews';
import { MemoriesPage } from './features/memories/MemoriesPage';
import { ChatPage } from './features/chat/ChatPage';
import { SearchPage } from './features/search/SearchPage';
import { AdminPage } from './features/admin/AdminPage';
import { PrintExportPage } from './features/documents/exportViews';
import { ErrorBoundary } from './app/ErrorBoundary';
import { GlobalErrorNotice, notifyGlobalError } from './app/GlobalErrorNotice';
import './styles.css';

initializeClientMonitoring();

function reportGlobalFailure(operation: string, cause: unknown): void {
  const error = cause instanceof ApiError
    ? cause
    : new ApiError('操作失败，请稍后重试', 0, 'CLIENT_UNHANDLED_ERROR');
  clientLogger.error(operation, cause, {
    operation, errorCode: error.code, requestId: error.requestId,
  });
  notifyGlobalError(error.message);
}

window.addEventListener('error', (event) => {
  reportGlobalFailure('window.error', event.error);
});
window.addEventListener('unhandledrejection', (event) => {
  reportGlobalFailure('window.unhandledrejection', event.reason);
});

function Root() {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [startupError, setStartupError] = useState<ApiError | null>(null);
  const [restoreAttempt, setRestoreAttempt] = useState(0);

  useEffect(() => {
    setReady(false);
    setStartupError(null);
    api
      .me()
      .then(setUser)
      .catch((cause) => {
        if (cause instanceof ApiError && cause.status === 401) {
          setUser(null);
          return;
        }
        const error = cause instanceof ApiError ? cause : new ApiError('服务暂时不可用，请检查网络', 0);
        setStartupError(error);
        clientLogger.error('session_restore_failed', cause, {
          operation: 'auth.restore', errorCode: error.code, requestId: error.requestId,
        });
      })
      .finally(() => setReady(true));
  }, [restoreAttempt]);

  useEffect(() => {
    const expire = () => setUser(null);
    window.addEventListener('nerva:session-expired', expire);
    return () => window.removeEventListener('nerva:session-expired', expire);
  }, []);

  if (!ready) return <div className="auth-loading">正在恢复 Nerva 会话…</div>;
  if (startupError) return (
    <main className="fatal-error" role="alert">
      <h1>暂时无法连接 Nerva</h1>
      <p>{displayError(startupError)}</p>
      <button type="button" onClick={() => setRestoreAttempt((value) => value + 1)}>重试</button>
    </main>
  );

  return (
    <Routes>
      <Route
        path="/login"
        element={user ? <Navigate to="/" replace /> : <AuthPage onAuthenticated={setUser} />}
      />
      <Route path="/register" element={<Navigate to="/login" replace />} />
      <Route
        path="/export/print"
        element={
          user ? (
            <PrintExportPage />
          ) : (
            <Navigate
              to="/login"
              replace
              state={{ from: location.pathname + location.search }}
            />
          )
        }
      />
      <Route
        path="/*"
        element={
          user ? (
            <KnowledgeApp user={user} onSignedOut={() => setUser(null)} />
          ) : (
            <Navigate to="/login" replace state={{ from: location.pathname }} />
          )
        }
      />
    </Routes>
  );
}

function KnowledgeApp({ user, onSignedOut }: { user: User; onSignedOut: () => void }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [documents, setDocuments] = useState<Document[]>([]);
  const [events, setEvents] = useState<KnowledgeEvent[]>([]);
  const [libraryDirty, setLibraryDirty] = useState(false);
  const [busy, setBusy] = useState(false);

  const view = location.pathname.startsWith('/search')
    ? 'search'
    : location.pathname.startsWith('/admin')
    ? 'admin'
    : location.pathname.startsWith('/library')
    ? 'library'
    : location.pathname.startsWith('/chat')
    ? 'chat'
    : location.pathname.startsWith('/growth')
    ? 'growth'
    : location.pathname.startsWith('/memories')
    ? 'memories'
    : 'capture';

  const selectedDocumentId =
    view === 'library' ? decodeURIComponent(location.pathname.split('/')[2] || '') || null : null;
  const selectedEventId =
    view === 'growth' ? decodeURIComponent(location.pathname.split('/')[2] || '') || null : null;
  const selectedChatSessionId =
    view === 'chat' ? decodeURIComponent(location.pathname.split('/')[2] || '') || null : null;
  const selectedPublicDocumentId = new URLSearchParams(location.search).get('public_document');

  useEffect(() => {
    if (view === 'admin' && user.role !== 'admin') navigate('/', { replace: true });
  }, [view, user.role, navigate]);

  useEffect(() => {
    if (!location.pathname.startsWith('/public-library')) return;
    const legacyId = decodeURIComponent(location.pathname.split('/')[2] || '');
    navigate(
      legacyId ? `/?public_document=${encodeURIComponent(legacyId)}#public-knowledge` : '/#public-knowledge',
      { replace: true },
    );
  }, [location.pathname, navigate]);

  useEffect(() => {
    Promise.all([api.documents(), api.events()])
      .then(([docs, log]) => {
        setDocuments(docs);
        setEvents(log);
      })
      .catch((e) => {
        if (e instanceof Error && 'status' in e && (e as any).status === 401) {
          onSignedOut();
          navigate('/login', { replace: true });
        }
      });
  }, [navigate, onSignedOut]);

  const handleRefresh = (docs: Document[], evts: KnowledgeEvent[]) => {
    setDocuments(docs);
    setEvents(evts);
  };

  const signOut = async () => {
    setBusy(true);
    try {
      await api.logout();
    } catch {
      /* Local logout still clears client auth */
    } finally {
      onSignedOut();
      navigate('/login', { replace: true });
    }
  };

  return (
    <AppShell
      user={user}
      documentCount={documents.length}
      eventCount={events.length}
      libraryDirty={libraryDirty}
      onSignOut={signOut}
    >
      {view === 'capture' && (
        <CaptureView
          publicDocumentId={selectedPublicDocumentId}
          onRefresh={handleRefresh}
        />
      )}

      {view === 'chat' && (
        <ChatPage
          sessionId={selectedChatSessionId}
          onOpenSession={(id) => navigate(id ? `/chat/${encodeURIComponent(id)}` : '/chat')}
          onOpenDocument={(id, visibility) => navigate(
            visibility === 'public'
              ? `/?public_document=${encodeURIComponent(id)}#public-knowledge`
              : `/library/${encodeURIComponent(id)}`
          )}
          onOpenCapture={() => navigate('/')}
        />
      )}

      {view === 'search' && (
        <SearchPage
          onOpenDocument={(id, visibility) => navigate(
            visibility === 'public'
              ? `/?public_document=${encodeURIComponent(id)}#public-knowledge`
              : `/library/${encodeURIComponent(id)}`
          )}
        />
      )}

      {view === 'library' && (
        <LibraryView
          documents={documents}
          selectedDocumentId={selectedDocumentId}
          onSelect={(id) => navigate(`/library/${encodeURIComponent(id)}`)}
          onDirtyChange={setLibraryDirty}
          onSaved={async (updated) => {
            setDocuments((current) => current.map((item) => (item.id === updated.id ? updated : item)));
            setEvents(await api.events());
          }}
        />
      )}

      {view === 'admin' && user.role === 'admin' && <AdminPage user={user} />}

      {view === 'growth' && (
        <GrowthView
          events={events}
          selectedEventId={selectedEventId}
          onOpen={(id) => navigate(`/growth/${encodeURIComponent(id)}`)}
          onClose={() => navigate('/growth')}
          onOpenDocument={(id) => navigate(`/library/${encodeURIComponent(id)}`)}
        />
      )}

      {view === 'memories' && <MemoriesPage />}
    </AppShell>
  );
}

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <BrowserRouter>
        <Root />
        <GlobalErrorNotice />
      </BrowserRouter>
    </ErrorBoundary>
  </React.StrictMode>
);
