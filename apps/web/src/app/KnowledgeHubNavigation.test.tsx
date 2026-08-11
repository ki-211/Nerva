import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { AppShell } from './AppShell';
import { UserAppShell } from './UserAppShell';

const user = { id: 'user-1', email: 'user@example.com', display_name: 'Hub User', role: 'user' as const };

describe('knowledge hub navigation', () => {
  it('shows the canonical active entry in the web shell', () => {
    render(<MemoryRouter initialEntries={['/knowledge-hub']}><AppShell
      user={user} documentCount={0} eventCount={0} libraryDirty={false} onSignOut={vi.fn()}
    ><div /></AppShell></MemoryRouter>);

    expect(screen.getByRole('button', { name: /知识中枢/ })).toHaveClass('active');
  });

  it('shows the canonical active entry in the EXE shell', () => {
    render(<MemoryRouter initialEntries={['/knowledge-hub']}><UserAppShell
      user={user} documentCount={0} eventCount={0} libraryDirty={false} onSignOut={vi.fn()}
    ><div /></UserAppShell></MemoryRouter>);

    expect(screen.getByRole('button', { name: /知识中枢/ })).toHaveClass('active');
  });
});
