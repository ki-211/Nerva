import { FormEvent, useEffect, useState } from 'react';
import { api } from '../../lib/api';
import type { User } from '../../lib/types';

type Props = {
  onAuthenticated: (user: User) => void;
  submitLabel?: string;
};

/**
 * Email + verification-code login form. Deliberately navigation-free so both the
 * login route and the first-launch wizard can host it without duplicating the
 * 60-second resend countdown.
 */
export function EmailCodeForm({ onAuthenticated, submitLabel = '登录 Nerva' }: Props) {
  const [email, setEmail] = useState('');
  const [verificationCode, setVerificationCode] = useState('');
  const [countdown, setCountdown] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (countdown <= 0) return;
    const timer = window.setTimeout(() => setCountdown(countdown - 1), 1_000);
    return () => window.clearTimeout(timer);
  }, [countdown]);

  const sendCode = async () => {
    if (!email || countdown > 0) return;
    setBusy(true); setError('');
    try {
      await api.sendVerificationCode(email);
      setCountdown(60);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '验证码发送失败');
    } finally { setBusy(false); }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true); setError('');
    try {
      onAuthenticated(await api.codeLogin(email, verificationCode));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '认证失败');
    } finally { setBusy(false); }
  };

  return <form onSubmit={submit}>
    <label>邮箱<input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com" autoComplete="email" /></label>
    <label>邮箱验证码<div className="code-row">
      <input required inputMode="numeric" pattern="\d{6}" maxLength={6} value={verificationCode} onChange={(event) => setVerificationCode(event.target.value.replace(/\D/g, ''))} placeholder="6 位验证码" autoComplete="one-time-code" />
      <button type="button" disabled={busy || !email || countdown > 0} onClick={sendCode}>{countdown > 0 ? `${countdown} 秒` : '发送验证码'}</button>
    </div></label>
    {error && <div className="auth-error">{error}</div>}
    <button disabled={busy || verificationCode.length !== 6}>{busy ? '请稍候…' : submitLabel}</button>
  </form>;
}
