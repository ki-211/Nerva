import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { UserApplication } from './UserApplication';
import { configureApiTransport } from '../lib/api';

/** The first-launch wizard only steps aside once a user id is on record for this device. */
function markDeviceOnboarded(...userIds: string[]) {
  window.localStorage.setItem('nerva.onboarding', JSON.stringify({ users: userIds }));
}

beforeEach(() => window.localStorage.clear());

afterEach(() => {
  configureApiTransport((input, init) => globalThis.fetch(input, init));
  vi.restoreAllMocks();
});

describe('user-only application entry', () => {
  it('shows only email verification login', async () => {
    markDeviceOnboarded('user-1');
    configureApiTransport(vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: { code: 'AUTH_REQUIRED', message: '请先登录' },
    }), { status: 401, headers: { 'Content-Type': 'application/json' } })));

    render(<MemoryRouter initialEntries={['/login']}><UserApplication /></MemoryRouter>);

    expect(await screen.findByRole('heading', { name: '邮箱验证码登录' })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: '邮箱' })).toBeInTheDocument();
    expect(screen.queryByText(/管理员/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/密码/)).not.toBeInTheDocument();
  });

  it('opens the first-launch wizard instead of the login page on a fresh install', async () => {
    configureApiTransport(vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: { code: 'AUTH_REQUIRED', message: '请先登录' },
    }), { status: 401, headers: { 'Content-Type': 'application/json' } })));

    render(<MemoryRouter initialEntries={['/login']}><UserApplication /></MemoryRouter>);

    expect(await screen.findByRole('heading', { name: '欢迎使用 Nerva' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '邮箱验证码登录' })).not.toBeInTheDocument();
  });

  it('does not expose an administrator route', async () => {
    markDeviceOnboarded('user-1');
    configureApiTransport(vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: { code: 'AUTH_REQUIRED', message: '请先登录' },
    }), { status: 401, headers: { 'Content-Type': 'application/json' } })));

    render(<MemoryRouter initialEntries={['/admin']}><UserApplication /></MemoryRouter>);

    await waitFor(() => expect(screen.getByRole('heading', { name: '邮箱验证码登录' })).toBeInTheDocument());
    expect(screen.queryByText(/管理员控制台/)).not.toBeInTheDocument();
  });

  it('keeps the research session list inside the application content grid', async () => {
    markDeviceOnboarded('user-1');
    Element.prototype.scrollIntoView = vi.fn();
    configureApiTransport(vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      const payload = url.endsWith('/v1/auth/me')
        ? {
          id: 'user-1', email: 'user@example.com', display_name: 'Research User',
          role: 'user', created_at: '2026-08-09T00:00:00Z',
        }
        : [];
      return Promise.resolve(new Response(JSON.stringify(payload), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      }));
    }));

    render(<MemoryRouter initialEntries={['/research']}><UserApplication /></MemoryRouter>);

    await waitFor(() => expect(document.querySelector('.research-sessions')).not.toBeNull());
    const shellSidebar = document.querySelector<HTMLElement>('.app-shell > aside');
    const researchSidebar = document.querySelector<HTMLElement>('.research-sessions');
    const researchLayout = document.querySelector<HTMLElement>('.research-layout');
    expect(shellSidebar).not.toBeNull();
    expect(shellSidebar?.parentElement).toHaveClass('app-shell');
    expect(researchLayout).toContainElement(researchSidebar);
    expect(researchLayout?.firstElementChild).toBe(researchSidebar);
    expect(researchLayout?.lastElementChild).toHaveClass('research-workspace');
  });

  it('redirects the legacy memories route to the knowledge hub in the desktop app', async () => {
    markDeviceOnboarded('user-1');
    configureApiTransport(vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      const payload = url.endsWith('/v1/auth/me')
        ? {
          id: 'user-1', email: 'user@example.com', display_name: 'Hub User',
          role: 'user', created_at: '2026-08-09T00:00:00Z',
        }
        : url.endsWith('/v1/knowledge-hub/settings')
          ? { personalization_enabled: true, auto_learning_enabled: true }
          : [];
      return Promise.resolve(new Response(JSON.stringify(payload), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      }));
    }));

    render(<MemoryRouter initialEntries={['/memories']}><UserApplication /></MemoryRouter>);

    expect(await screen.findByRole('heading', { name: '知识中枢' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /知识中枢/ })).toHaveClass('active');
    expect(screen.queryByText('个性化偏好')).not.toBeInTheDocument();
  });

  it('sends an authenticated user who never finished onboarding to the first-capture step', async () => {
    configureApiTransport(vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      const payload = url.endsWith('/v1/auth/me')
        ? { id: 'user-1', email: 'user@example.com', display_name: 'New User', role: 'user' }
        : [];
      return Promise.resolve(new Response(JSON.stringify(payload), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      }));
    }));

    render(<MemoryRouter initialEntries={['/']}><UserApplication /></MemoryRouter>);

    expect(await screen.findByRole('heading', { name: '试一次真正的录入' })).toBeInTheDocument();
  });
});
