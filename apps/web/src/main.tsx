import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { api } from './lib/api';
import type { Document, KnowledgeEvent, User } from './lib/types';
import { AuthPage } from './features/auth/AuthPage';
import { AppShell } from './app/AppShell';
import { CaptureView } from './features/capture/CaptureView';
import { LibraryView, GrowthView } from './features/documents/knowledgeViews';
import { MemoriesPage } from './features/memories/MemoriesPage';
import { ChatPage } from './features/chat/ChatPage';
import { PrintExportPage } from './features/documents/exportViews';
import './styles.css';

function Root() {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    api
      .me()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setReady(true));
  }, []);

  if (!ready) return <div className="auth-loading">正在恢复 Nerva 会话…</div>;

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

  const view = location.pathname.startsWith('/library')
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

  const handleAuthError = () => {
    onSignedOut();
    navigate('/login', { replace: true, state: { from: location.pathname } });
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
        <CaptureView onRefresh={handleRefresh} onAuthError={handleAuthError} />
      )}

      {view === 'chat' && (
        <ChatPage
          sessionId={selectedChatSessionId}
          onOpenSession={(id) => navigate(id ? `/chat/${encodeURIComponent(id)}` : '/chat')}
          onOpenDocument={(id) => navigate(`/library/${encodeURIComponent(id)}`)}
          onOpenCapture={() => navigate('/')}
          onAuthError={handleAuthError}
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

      {view === 'growth' && (
        <GrowthView
          events={events}
          selectedEventId={selectedEventId}
          onOpen={(id) => navigate(`/growth/${encodeURIComponent(id)}`)}
          onClose={() => navigate('/growth')}
          onOpenDocument={(id) => navigate(`/library/${encodeURIComponent(id)}`)}
        />
      )}

      {view === 'memories' && <MemoriesPage onAuthError={handleAuthError} />}
    </AppShell>
  );
}

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Root />
    </BrowserRouter>
  </React.StrictMode>
);
