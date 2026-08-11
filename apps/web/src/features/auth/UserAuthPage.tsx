import { useLocation, useNavigate } from 'react-router-dom';
import type { User } from '../../lib/types';
import { EmailCodeForm } from './EmailCodeForm';
import './auth.css';

type Props = { onAuthenticated: (user: User) => void };

export function UserAuthPage({ onAuthenticated }: Props) {
  const navigate = useNavigate();
  const location = useLocation();

  const authenticated = (user: User) => {
    onAuthenticated(user);
    const from = (location.state as { from?: string } | null)?.from || '/';
    navigate(from, { replace: true });
  };

  return <main className="auth-page">
    <section className="auth-card">
      <div className="auth-brand"><span className="brand-mark">N</span><div><b>Nerva</b><small>让知识随着每次输入持续成长</small></div></div>
      <span className="eyebrow">PERSONAL KNOWLEDGE OS</span>
      <h1>邮箱验证码登录</h1>
      <p>无需注册和密码。首次验证邮箱后会自动创建你的独立知识空间。</p>
      <EmailCodeForm onAuthenticated={authenticated} />
      <div className="auth-switch">验证码 5 分钟有效 · 首次登录自动创建账号</div>
    </section>
  </main>;
}
