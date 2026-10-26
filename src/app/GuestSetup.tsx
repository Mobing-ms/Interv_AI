import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api';
import { errText, ROUNDS } from './ui';

const ROLES = ['Software engineer', 'Backend engineer', 'Frontend engineer', 'Data analyst', 'Product manager', 'ML engineer'];
const SITE_KEY = import.meta.env.VITE_TURNSTILE_SITE_KEY || '';

// One free interview without an account: 3 questions, about 10 minutes, deleted after 24 hours.
export default function GuestSetup() {
  const nav = useNavigate();
  const [role, setRole] = useState(ROLES[0]);
  const [round, setRound] = useState('Technical');
  const [difficulty, setDifficulty] = useState('Medium');
  const [cvId, setCvId] = useState<number | undefined>();
  const [cvName, setCvName] = useState('');
  const [agree, setAgree] = useState(false);
  const [captcha, setCaptcha] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const widget = useRef<HTMLDivElement>(null);

  // Real Cloudflare Turnstile only when a site key is configured; the dev backend skips the check without a secret.
  useEffect(() => {
    if (!SITE_KEY || !widget.current) return;
    const render = () => (window as any).turnstile?.render(widget.current, { sitekey: SITE_KEY, callback: setCaptcha });
    if ((window as any).turnstile) { render(); return; }
    const s = document.createElement('script');
    s.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js';
    s.async = true;
    s.onload = render;
    document.head.appendChild(s);
  }, []);

  const pickCv = async (f: File) => {
    setError('');
    if (f.size > 2 * 1024 * 1024) { setError('The CV must be under 2 MB.'); return; }
    setCvName(`Uploading ${f.name}…`);
    try {
      const r = await api.uploadGuestCv(f);
      setCvId(r.cv_document_id);
      setCvName(f.name);
    } catch (e) {
      setCvName('');
      setError(errText(e, 'Could not upload the CV'));
    }
  };

  const start = async () => {
    setBusy(true);
    setError('');
    try {
      await api.startGuestSession({ target_role: role, round_type: round, difficulty, cv_document_id: cvId, turnstile_token: captcha || undefined });
      nav('/interview/precheck');
    } catch (e) {
      setError(errText(e, 'Could not start the guest interview'));
      setBusy(false);
    }
  };

  return (
    <main className="page solo-narrow" style={{ margin: '0 auto' }}>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <Link className="brand" to="/">IntervAI</Link>
        <Link className="link" style={{ fontSize: 14 }} to="/login">Log in</Link>
      </div>
      <h1 className="serif" style={{ fontSize: 38, marginTop: 36 }}>Try one interview</h1>
      <p className="dim">No account. Three questions, about ten minutes, and a scored report.</p>

      <div className="sec">
        <div className="k"><span>Role</span></div>
        <div className="chips">
          {ROLES.map((r) => <button key={r} className={`opt ${role === r ? 'on' : ''}`} style={{ padding: '6px 12px' }} onClick={() => setRole(r)}>{r}</button>)}
        </div>
        <label className="field"><span>Or type your own</span><input value={ROLES.includes(role) ? '' : role} placeholder="e.g. DevOps engineer" onChange={(e) => setRole(e.target.value || ROLES[0])} /></label>
      </div>

      <div className="sec grid2">
        <div>
          <div className="k"><span>Round</span></div>
          <div className="opts" style={{ gridTemplateColumns: '1fr 1fr' }}>
            {ROUNDS.map((r) => <button key={r} className={`opt ${round === r ? 'on' : ''}`} onClick={() => setRound(r)}>{r}</button>)}
          </div>
        </div>
        <div>
          <div className="k"><span>Difficulty</span></div>
          <div className="opts" style={{ gridTemplateColumns: '1fr 1fr 1fr' }}>
            {['Easy', 'Medium', 'Hard'].map((d) => <button key={d} className={`opt ${difficulty === d ? 'on' : ''}`} onClick={() => setDifficulty(d)}>{d}</button>)}
          </div>
        </div>
      </div>

      <div className="sec">
        <div className="k"><span>CV · optional, under 2 MB</span></div>
        <label className="btn ghost" style={{ marginTop: 10, cursor: 'pointer' }}>
          {cvName || 'Choose a PDF or DOCX'}
          <input type="file" accept=".pdf,.docx" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) pickCv(f); }} />
        </label>
      </div>

      <div className="sec">
        <label className="row" style={{ cursor: 'pointer', alignItems: 'flex-start', fontSize: 14 }}>
          <input type="checkbox" style={{ width: 'auto', marginTop: 4 }} checked={agree} onChange={(e) => setAgree(e.target.checked)} />
          <span>I understand the recording and report are kept for 24 hours and then deleted.</span>
        </label>
        {SITE_KEY ? <div ref={widget} style={{ marginTop: 14 }} /> : null}
      </div>

      {error ? <p className="err">{error}</p> : null}
      <div className="stepnav">
        <span className="dim" style={{ fontSize: 13 }}>{role} · {round} · {difficulty}</span>
        <button className="btn" disabled={!agree || busy || (!!SITE_KEY && !captcha)} onClick={start}>{busy ? 'Starting…' : 'Continue to device check'}</button>
      </div>
    </main>
  );
}
