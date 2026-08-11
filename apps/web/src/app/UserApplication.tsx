import { useCallback, useEffect, useState } from 'react';
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { api } from '../lib/api';
import { ApiError, displayError } from '../lib/errors';
import { clientLogger } from '../lib/clientLogger';
import { completedUserIds, isOnboardingComplete } from '../lib/onboarding';
import type { Document, KnowledgeEvent, User } from '../lib/types';
import { UserAuthPage } from '../features/auth/UserAuthPage';
import { OnboardingWizard, type OnboardingStep } from '../features/onboarding/OnboardingWizard';
import { UserAppShell } from './UserAppShell';
import { CaptureView } from '../features/capture/CaptureView';
import { LibraryView, GrowthView } from '../features/documents/knowledgeViews';
import { KnowledgeHubPage } from '../features/knowledge-hub/KnowledgeHubPage';
import { ChatPage } from '../features/chat/ChatPage';
import { SearchPage } from '../features/search/SearchPage';
import { ResearchPage } from '../features/research/ResearchPage';
import { PrintExportPage } from '../features/documents/exportViews';

export function UserApplication() {
  const location = useLocation();
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [startupError, setStartupError] = useState<ApiError | null>(null);
  const [restoreAttempt, setRestoreAttempt] = useState(0);
  // A non-empty list means the wizard already ran on this device, which is the only
  // signal available before api.me() resolves.
  const [deviceKnown] = useState(() => completedUserIds().length > 0);
  const [wizardDone, setWizardDone] = useState(false);
  const [pendingChangeSetId, setPendingChangeSetId] = useState<string | null>(null);

  useEffect(() => {
    setReady(false); setStartupError(null);
    api.me().then(setUser).catch((cause) => {
      if (cause instanceof ApiError && cause.status === 401) { setUser(null); return; }
      const error = cause instanceof ApiError ? cause : new ApiError('服务暂时不可用，请检查网络', 0);
      setStartupError(error);
      clientLogger.error('session_restore_failed', cause, { operation: 'auth.restore', errorCode: error.code, requestId: error.requestId });
    }).finally(() => setReady(true));
  }, [restoreAttempt]);

  useEffect(() => {
    const expire = () => setUser(null);
    window.addEventListener('nerva:session-expired', expire);
    return () => window.removeEventListener('nerva:session-expired', expire);
  }, []);

  const consumeChangeSet = useCallback(() => setPendingChangeSetId(null), []);

  const onboardingStep: OnboardingStep | null = !ready || wizardDone ? null
    : user ? (isOnboardingComplete(user.id) ? null : 'capture')
    : deviceKnown ? null
    : startupError ? 'connect' : 'welcome';

  if (!ready) return <div className="auth-loading">正在恢复 Nerva 会话…</div>;
  if (onboardingStep) return <OnboardingWizard
    initialStep={onboardingStep}
    initialUser={user}
    onAuthenticated={(loggedIn) => { setUser(loggedIn); setStartupError(null); }}
    onFinish={(changeSetId) => { setPendingChangeSetId(changeSetId); setWizardDone(true); }}
  />;
  if (startupError) return <main className="fatal-error" role="alert"><h1>暂时无法连接 Nerva</h1><p>{displayError(startupError)}</p><button type="button" onClick={() => setRestoreAttempt((value) => value + 1)}>重试</button></main>;

  return <Routes>
    <Route path="/login" element={user ? <Navigate to="/" replace /> : <UserAuthPage onAuthenticated={setUser} />} />
    <Route path="/register" element={<Navigate to="/login" replace />} />
    <Route path="/admin" element={<Navigate to="/" replace />} />
    <Route path="/admin/*" element={<Navigate to="/" replace />} />
    <Route path="/export/print" element={user ? <PrintExportPage /> : <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />} />
    <Route path="/*" element={user ? <UserKnowledgeApp user={user} onSignedOut={() => setUser(null)} pendingChangeSetId={pendingChangeSetId} onChangeSetConsumed={consumeChangeSet} /> : <Navigate to="/login" replace state={{ from: location.pathname }} />} />
  </Routes>;
}

type KnowledgeAppProps = {
  user: User;
  onSignedOut: () => void;
  pendingChangeSetId?: string | null;
  onChangeSetConsumed?: () => void;
};

function UserKnowledgeApp({ user, onSignedOut, pendingChangeSetId, onChangeSetConsumed }: KnowledgeAppProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const [documents, setDocuments] = useState<Document[]>([]);
  const [events, setEvents] = useState<KnowledgeEvent[]>([]);
  const [libraryDirty, setLibraryDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const view = location.pathname.startsWith('/research') ? 'research'
    : location.pathname.startsWith('/search') ? 'search'
    : location.pathname.startsWith('/library') ? 'library'
    : location.pathname.startsWith('/chat') ? 'chat'
    : location.pathname.startsWith('/growth') ? 'growth'
    : location.pathname.startsWith('/knowledge-hub') || location.pathname.startsWith('/memories') ? 'knowledge-hub' : 'capture';
  const selectedDocumentId = view === 'library' ? decodeURIComponent(location.pathname.split('/')[2] || '') || null : null;
  const selectedEventId = view === 'growth' ? decodeURIComponent(location.pathname.split('/')[2] || '') || null : null;
  const selectedChatSessionId = view === 'chat' ? decodeURIComponent(location.pathname.split('/')[2] || '') || null : null;
  const selectedResearchSessionId = view === 'research' ? decodeURIComponent(location.pathname.split('/')[2] || '') || null : null;
  const selectedPublicDocumentId = new URLSearchParams(location.search).get('public_document');

  useEffect(() => {
    if (!location.pathname.startsWith('/memories')) return;
    navigate('/knowledge-hub', { replace: true });
  }, [location.pathname, navigate]);

  useEffect(() => {
    if (!location.pathname.startsWith('/public-library')) return;
    const legacyId = decodeURIComponent(location.pathname.split('/')[2] || '');
    navigate(legacyId ? `/?public_document=${encodeURIComponent(legacyId)}#public-knowledge` : '/#public-knowledge', { replace: true });
  }, [location.pathname, navigate]);

  useEffect(() => {
    Promise.all([api.documents(), api.events()]).then(([docs, log]) => { setDocuments(docs); setEvents(log); }).catch((cause) => {
      if (cause instanceof ApiError && cause.status === 401) { onSignedOut(); navigate('/login', { replace: true }); }
    });
  }, [navigate, onSignedOut]);

  const signOut = async () => {
    setBusy(true);
    try { await api.logout(); } catch { /* Local logout still clears client UI state. */ }
    finally { setBusy(false); onSignedOut(); navigate('/login', { replace: true }); }
  };
  const openDocument = (id: string, visibility: string) => navigate(visibility === 'public' ? `/?public_document=${encodeURIComponent(id)}#public-knowledge` : `/library/${encodeURIComponent(id)}`);

  return <UserAppShell user={user} documentCount={documents.length} eventCount={events.length} libraryDirty={libraryDirty} onSignOut={signOut}>
    {busy && <span className="visually-hidden">正在退出</span>}
    {view === 'capture' && <CaptureView publicDocumentId={selectedPublicDocumentId} initialChangeSetId={pendingChangeSetId} onInitialChangeSetConsumed={onChangeSetConsumed} onRefresh={(docs, log) => { setDocuments(docs); setEvents(log); }} />}
    {view === 'chat' && <ChatPage sessionId={selectedChatSessionId} onOpenSession={(id) => navigate(id ? `/chat/${encodeURIComponent(id)}` : '/chat')} onOpenDocument={openDocument} onOpenCapture={() => navigate('/')} />}
    {view === 'research' && <ResearchPage sessionId={selectedResearchSessionId} onOpenSession={(id) => navigate(id ? `/research/${encodeURIComponent(id)}` : '/research')} onRefresh={(docs, log) => { setDocuments(docs); setEvents(log); }} />}
    {view === 'search' && <SearchPage onOpenDocument={openDocument} />}
    {view === 'library' && <LibraryView documents={documents} selectedDocumentId={selectedDocumentId} onSelect={(id) => navigate(`/library/${encodeURIComponent(id)}`)} onDirtyChange={setLibraryDirty} onSaved={async (updated) => { setDocuments((current) => current.map((item) => item.id === updated.id ? updated : item)); setEvents(await api.events()); }} />}
    {view === 'growth' && <GrowthView events={events} selectedEventId={selectedEventId} onOpen={(id) => navigate(`/growth/${encodeURIComponent(id)}`)} onClose={() => navigate('/growth')} onOpenDocument={(id) => navigate(`/library/${encodeURIComponent(id)}`)} />}
    {view === 'knowledge-hub' && <KnowledgeHubPage documents={documents} events={events} onOpenLibrary={() => navigate('/library')} onOpenMemorySource={(channel, sessionId) => navigate(`/${channel}/${encodeURIComponent(sessionId)}`)} />}
  </UserAppShell>;
}
