import { useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { api, AuthResponse } from '../api';
import { useAuth } from '../authContext';
import { errText } from './ui';

export default function Auth({ signup }: { signup: boolean }) {
  const { setUser } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const googleRef = useRef<HTMLDivElement>(null);
  const googleClientId = import.meta.env.VITE_GOOGLE_CLIENT_ID || '';

  const after = (data: AuthResponse) => {
    setUser(data.user);
    const from = (loc.state as any)?.from;
    if (signup || (data.user.onboarding_status && data.user.onboarding_status !== 'profile_confirmed')) {
      nav('/onboarding');
    } else {
      nav(from && from !== '/login' ? from : '/dashboard');
    }
  };

  useEffect(() => {
    if (!googleClientId || !googleRef.current) return;
    let tries = 0;
    const init = () => {
      const g = (window as any).google?.accounts?.id;
      if (!g) { if (tries++ < 20) setTimeout(init, 250); return; }
      g.initialize({
        client_id: googleClientId,
        callback: async (resp: { credential?: string }) => {
          if (!resp.credential) return;
          try { after(await api.googleAuth({ credential: resp.credential })); }
          catch (e) { setError(errText(e, 'Google sign-in failed')); }
        },
      });
      g.renderButton(googleRef.current, { type: 'standard', theme: 'outline', size: 'large', text: 'continue_with', shape: 'rectangular', width: 320 });
    };
    init();
  }, [googleClientId, signup]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (signup && password !== confirm) { setError('Passwords do not match.'); return; }
    if (signup && password.length < 8) { setError('Use at least 8 characters for the password.'); return; }
    setBusy(true);
    try {
      after(signup ? await api.signup(name.trim(), email.trim(), password) : await api.login(email.trim(), password));
    } catch (err) {
      setError(errText(err, signup ? 'Could not create the account' : 'Could not log in'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth">
      <div className="pitch">
        <Link className="brand" to="/">IntervAI</Link>
        <div>
          <h1 className="thin">{signup ? <>Start<br />practising</> : <>Welcome<br />back</>}</h1>
          <p className="dim" style={{ marginTop: 20, maxWidth: '28em' }}>
            Ava asks out loud, listens, follows up, and scores every answer. Your dashboard keeps track of what to practise next.
          </p>
        </div>
      </div>
      <form onSubmit={submit}>
        <h2>{signup ? 'Create your account' : 'Log in'}</h2>
        <p className="dim" style={{ fontSize: 14, marginTop: 4 }}>
          {signup ? <>Already have one? <Link className="ink" to="/login">Log in</Link></> : <>New here? <Link className="ink" to="/signup">Create an account</Link></>}
        </p>
        {signup ? (
          <label className="field"><span>Name</span><input value={name} onChange={(e) => setName(e.target.value)} required autoComplete="name" /></label>
        ) : null}
        <label className="field"><span>Email</span><input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" /></label>
        <label className="field"><span>Password</span><input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete={signup ? 'new-password' : 'current-password'} /></label>
        {signup ? (
          <label className="field"><span>Confirm password</span><input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required autoComplete="new-password" /></label>
        ) : null}
        {error ? <p className="err">{error}</p> : null}
        <button className="btn wide" style={{ marginTop: 28 }} disabled={busy}>{busy ? 'Please wait…' : signup ? 'Create account' : 'Log in'}</button>
        {googleClientId ? <div ref={googleRef} style={{ marginTop: 14 }} /> : null}
        <p className="dim" style={{ fontSize: 13, marginTop: 22 }}>Or <Link className="ink" to="/guest/setup">try one interview as a guest</Link>, no account needed.</p>
      </form>
    </div>
  );
}
