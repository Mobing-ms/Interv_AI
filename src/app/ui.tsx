import React, { useEffect, useState } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { api, DashboardSummaryResponse, tokenStorage } from '../api';
import { useAuth } from '../authContext';

export const ROUNDS = ['Technical', 'HR', 'Managerial', 'Mixed'] as const;

export function errText(e: any, fallback = 'Something went wrong'): string {
  return (e && (e.detail || e.message)) || fallback;
}

export function initials(name?: string): string {
  return (name || '?').split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]!.toUpperCase()).join('');
}

export function fmtDate(iso?: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const today = new Date();
  if (d.toDateString() === today.toDateString()) return 'Today';
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
}

export function classLabel(c?: string | null): string {
  if (!c || c === 'NOT_SCORED') return 'Not scored';
  return c[0] + c.slice(1).toLowerCase();
}

export function scoreText(n?: number | null): string {
  return n === null || n === undefined ? '—' : String(Math.round(n));
}

// Light/dark toggle shared by every page; the choice is kept per browser.
export function useTheme(): [string, () => void] {
  const root = document.documentElement;
  const isDark = () =>
    root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  const [dark, setDark] = useState(isDark());
  const toggle = () => {
    root.dataset.theme = isDark() ? 'light' : 'dark';
    try { localStorage.setItem('theme', root.dataset.theme); } catch {}
    setDark(isDark());
  };
  return [dark ? 'Light' : 'Dark', toggle];
}

export function ThemeButton({ className = 'link' }: { className?: string }) {
  const [label, toggle] = useTheme();
  return <button className={className} onClick={toggle}>{label}</button>;
}

export function RequireUser({ children, allowGuest = false }: { children: React.ReactNode; allowGuest?: boolean }) {
  const { user, isLoading } = useAuth();
  const loc = useLocation();
  if (isLoading) return <div className="loading">Loading…</div>;
  if (!user && !(allowGuest && tokenStorage.getGuestSessionId())) {
    return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  }
  return <>{children}</>;
}

const NAV = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/interview/setup', label: 'New interview' },
  { to: '/history', label: 'History' },
  { to: '/onboarding', label: 'Profile & CV' },
  { to: '/settings', label: 'Settings' },
];

// Sidebar layout for signed-in pages. Focus areas come from the dashboard summary.
export function Shell({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const [summary, setSummary] = useState<DashboardSummaryResponse | null>(null);

  useEffect(() => {
    if (!user) return;
    api.getDashboardSummary().then(setSummary).catch(() => {});
  }, [user?.id]);

  const weak = summary?.current_weak_areas || [];
  const on = (to: string) => (loc.pathname === to || (to !== '/dashboard' && loc.pathname.startsWith(to)) ? 'on' : '');

  return (
    <div className="shell">
      <aside className="side">
        <Link className="brand" to="/dashboard">IntervAI</Link>
        <Link className="btn" to="/interview/setup">New interview</Link>
        <nav>
          {NAV.filter((n) => n.to !== '/interview/setup').map((n) => (
            <Link key={n.to} className={on(n.to)} to={n.to}>
              {n.label}
              {n.to === '/history' && summary ? <span>{summary.all_sessions_count}</span> : null}
            </Link>
          ))}
        </nav>
        <div className="fa">
          <h6>Focus areas</h6>
          {weak.length === 0 ? (
            <p className="dim" style={{ fontSize: 13, padding: '0 10px' }}>Appear after your first scored interview.</p>
          ) : (
            weak.slice(0, 6).map((w) => (
              <button key={w} onClick={() => nav(`/interview/setup?focus=${encodeURIComponent(w)}`)}>
                <span className="dot" />{w}
              </button>
            ))
          )}
        </div>
        {user ? (
          <div className="me">
            <i>{initials(user.name)}</i><span>{user.name}</span>
            <ThemeButton />
          </div>
        ) : null}
        {user ? (
          <button className="link" style={{ textAlign: 'left', padding: '0 10px', fontSize: 13 }}
            onClick={async () => { await logout(); nav('/'); }}>Log out</button>
        ) : null}
      </aside>
      <div>
        <nav className="mobnav">
          <Link className="brand" to="/dashboard">IntervAI</Link>
          {NAV.map((n) => <Link key={n.to} className={on(n.to)} to={n.to}>{n.label}</Link>)}
        </nav>
        {children}
      </div>
    </div>
  );
}

export function Steps({ total, at }: { total: number; at: number }) {
  return (
    <div className="steps">
      {Array.from({ length: total }, (_, i) => <i key={i} className={i < at ? 'past' : i === at ? 'now' : ''} />)}
    </div>
  );
}

export function Chips({ items, onRemove, onAdd, placeholder }: {
  items: string[]; onRemove?: (v: string) => void; onAdd?: (v: string) => void; placeholder?: string;
}) {
  const [v, setV] = useState('');
  return (
    <div>
      <div className="chips">
        {items.map((it) => (
          <span className="chip" key={it}>{it}{onRemove ? <button onClick={() => onRemove(it)} aria-label={`Remove ${it}`}>×</button> : null}</span>
        ))}
      </div>
      {onAdd ? (
        <input
          placeholder={placeholder || 'Add and press Enter'}
          value={v}
          onChange={(e) => setV(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && v.trim()) {
              e.preventDefault();
              if (!items.includes(v.trim())) onAdd(v.trim());
              setV('');
            }
          }}
        />
      ) : null}
    </div>
  );
}
