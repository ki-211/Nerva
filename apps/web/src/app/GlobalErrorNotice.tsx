import { useEffect, useState } from 'react';

export function notifyGlobalError(message: string): void {
  window.dispatchEvent(new CustomEvent('nerva:global-error', { detail: message }));
}

export function GlobalErrorNotice() {
  const [message, setMessage] = useState('');
  useEffect(() => {
    const listener = (event: Event) => setMessage((event as CustomEvent<string>).detail);
    window.addEventListener('nerva:global-error', listener);
    return () => window.removeEventListener('nerva:global-error', listener);
  }, []);
  if (!message) return null;
  return (
    <div className="global-error-notice" role="alert" aria-live="assertive">
      <span>{message}</span>
      <button type="button" onClick={() => setMessage('')}>关闭</button>
    </div>
  );
}
