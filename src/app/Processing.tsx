import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { AnalysisStatus, api } from '../api';
import { useAuth } from '../authContext';
import { errText } from './ui';

const STEPS = [
  { at: 25, label: 'Collecting your recording' },
  { at: 50, label: 'Lining up the transcript' },
  { at: 75, label: 'Scoring content, delivery and presence' },
  { at: 100, label: 'Writing your report' },
];

export default function Processing() {
  const { id } = useParams();
  const sessionId = Number(id);
  const nav = useNavigate();
  const { user } = useAuth();
  const [st, setSt] = useState<AnalysisStatus | null>(null);
  const [error, setError] = useState('');
  const kicked = useRef(false);

  useEffect(() => {
    let stop = false, timer: any;
    const poll = async () => {
      try {
        const s = await api.getAnalysisStatus(sessionId);
        if (stop) return;
        setSt(s);
        if (s.status === 'not_started' && !kicked.current) {
          kicked.current = true;
          await api.finalizeSession(sessionId).catch(() => {});
        } else if (s.status === 'completed' || s.status === 'partial') {
          setTimeout(() => nav(`/report/${sessionId}`, { replace: true }), 900);
          return;
        } else if (s.status === 'failed') {
          setError(s.error_message || 'Analysis failed.');
          return;
        }
      } catch (e) {
        if (!stop) setError(errText(e, 'Could not check the analysis'));
        return;
      }
      timer = setTimeout(poll, 2000);
    };
    poll();
    return () => { stop = true; clearTimeout(timer); };
  }, [sessionId]);

  const retry = async () => {
    setError('');
    kicked.current = true;
    try { await api.finalizeSession(sessionId); location.reload(); }
    catch (e) { setError(errText(e, 'Retry failed')); }
  };

  const p = st?.progress ?? 0;
  return (
    <main className="page solo-narrow" style={{ margin: '0 auto', minHeight: '100vh', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
      <span className="brand">IntervAI</span>
      <h1 className="serif" style={{ fontSize: 38, marginTop: 32 }}>Preparing your report</h1>
      <p className="dim" style={{ marginTop: 6 }}>This usually takes under a minute. You can leave; it will be on your dashboard.</p>
      <div className="bar" style={{ marginTop: 28 }}><i style={{ width: `${p}%`, background: 'var(--ink)', transition: 'width .6s' }} /></div>
      <ol style={{ listStyle: 'none', marginTop: 22 }}>
        {STEPS.map((s) => (
          <li key={s.at} style={{ padding: '7px 0', color: p >= s.at ? 'var(--fg)' : 'var(--dim)' }}>{p >= s.at ? '✓  ' : ''}{s.label}</li>
        ))}
      </ol>
      {st?.current_step ? <p className="dim" style={{ fontSize: 13, marginTop: 10 }}>{st.current_step}</p> : null}
      {error ? (
        <div style={{ marginTop: 20 }}>
          <p className="err">{error}</p>
          <div className="row" style={{ marginTop: 14 }}><button className="btn" onClick={retry}>Try again</button><Link className="btn ghost" to={user ? '/dashboard' : '/'}>Back</Link></div>
        </div>
      ) : (
        <Link className="link" style={{ marginTop: 28, fontSize: 14 }} to={user ? '/dashboard' : '/'}>Back to {user ? 'dashboard' : 'home'}</Link>
      )}
    </main>
  );
}
