import { FormEvent, useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { api } from '../../lib/api';
import type { User } from '../../lib/types';
import './auth.css';

type Props = { onAuthenticated: (user: User) => void };

export function UserAuthPage({ onAuthenticated }: Props) {
  const navigate = useNavigate();
  const location = useLocation();
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
      const user = await api.codeLogin(email, verificationCode);
      onAuthenticated(user);
      const from = (location.state as { from?: string } | null)?.from || '/';
      navigate(from, { replace: true });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '认证失败');
    } finally { setBusy(false); }
  };

  return <main className="auth-page">
    <section className="auth-card">
      <div className="auth-brand"><span className="brand-mark">N</span><div><b>Nerva</b><small>让知识随着每次输入持续成长</small></div></div>
      <span className="eyebrow">PERSONAL KNOWLEDGE OS</span>
      <h1>邮箱验证码登录</h1>
      <p>无需注册和密码。首次验证邮箱后会自动创建你的独立知识空间。</p>
      <form onSubmit={submit}>
        <label>邮箱<input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com" autoComplete="email" /></label>
        <label>邮箱验证码<div className="code-row">
          <input required inputMode="numeric" pattern="\d{6}" maxLength={6} value={verificationCode} onChange={(event) => setVerificationCode(event.target.value.replace(/\D/g, ''))} placeholder="6 位验证码" autoComplete="one-time-code" />
          <button type="button" disabled={busy || !email || countdown > 0} onClick={sendCode}>{countdown > 0 ? `${countdown} 秒` : '发送验证码'}</button>
        </div></label>
        {error && <div className="auth-error">{error}</div>}
        <button disabled={busy || verificationCode.length !== 6}>{busy ? '请稍候…' : '登录 Nerva'}</button>
      </form>
      <div className="auth-switch">验证码 5 分钟有效 · 首次登录自动创建账号</div>
    </section>
  </main>;
}
