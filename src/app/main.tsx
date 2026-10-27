import { useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Link, Route, Routes, useLocation } from 'react-router-dom';
import { Toaster } from 'sonner';
import { AuthProvider } from '../authContext';
import Auth from './Auth';
import Dashboard from './Dashboard';
import GuestSetup from './GuestSetup';
import { History, Settings } from './History';
import Landing from './Landing';
import Live from './Live';
import Onboarding from './Onboarding';
import Precheck from './Precheck';
import Processing from './Processing';
import Report from './Report';
import Setup from './Setup';
import { RequireUser } from './ui';
import './paper.css';

try { const t = localStorage.getItem('theme'); if (t) document.documentElement.dataset.theme = t; } catch {}

function ScrollTop() {
  const { pathname } = useLocation();
  useEffect(() => { window.scrollTo(0, 0); }, [pathname]);
  return null;
}

function NotFound() {
  return (
    <main className="page solo-narrow" style={{ margin: '0 auto', minHeight: '100vh', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
      <h1 className="thin" style={{ fontSize: 96, lineHeight: 0.9 }}>404</h1>
      <p className="dim" style={{ marginTop: 12 }}>This page doesn't exist.</p>
      <Link className="btn" style={{ marginTop: 24, alignSelf: 'flex-start' }} to="/">Home</Link>
    </main>
  );
}

function App() {
  return (
    <AuthProvider>
      <ScrollTop />
      <Toaster position="top-right" />
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/login" element={<Auth signup={false} />} />
        <Route path="/signup" element={<Auth signup />} />
        <Route path="/guest/setup" element={<GuestSetup />} />
        <Route path="/onboarding" element={<RequireUser><Onboarding /></RequireUser>} />
        <Route path="/dashboard" element={<RequireUser><Dashboard /></RequireUser>} />
        <Route path="/interview/setup" element={<RequireUser><Setup /></RequireUser>} />
        <Route path="/interview/precheck" element={<RequireUser allowGuest><Precheck /></RequireUser>} />
        <Route path="/interview/live/:id" element={<RequireUser allowGuest><Live /></RequireUser>} />
        <Route path="/interview/processing/:id" element={<RequireUser allowGuest><Processing /></RequireUser>} />
        <Route path="/report/:id" element={<RequireUser allowGuest><Report /></RequireUser>} />
        <Route path="/history" element={<RequireUser><History /></RequireUser>} />
        <Route path="/settings" element={<RequireUser><Settings /></RequireUser>} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </AuthProvider>
  );
}

createRoot(document.getElementById('root')!).render(
  <BrowserRouter>
    <App />
  </BrowserRouter>,
);
