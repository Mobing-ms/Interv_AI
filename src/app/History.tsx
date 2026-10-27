import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api, DashboardSessionItem } from '../api';
import { useAuth } from '../authContext';
import { classLabel, errText, fmtDate, ROUNDS, scoreText, Shell, ThemeButton } from './ui';

export function History() {
  const nav = useNavigate();
  const [rows, setRows] = useState<DashboardSessionItem[] | null>(null);
  const [round, setRound] = useState('All');
  const [error, setError] = useState('');

  useEffect(() => {
    api.listUserSessions().then((r) => setRows(r.sessions || [])).catch((e) => setError(errText(e, 'Could not load your interviews')));
  }, []);

  const shown = (rows || []).filter((r) => round === 'All' || r.round_type === round);

  const csv = () => {
    const head = ['id', 'date', 'round', 'role', 'difficulty', 'status', 'overall', 'content', 'delivery', 'presence', 'class'];
    const lines = shown.map((r) => [r.id, r.created_at || '', r.round_type, r.role, r.difficulty, r.status, r.overall_score ?? '', r.content_score ?? '', r.speech_score ?? '', r.face_score ?? '', r.classification ?? '']
      .map((v) => `"${String(v).replace(/"/g, '""')}"`).join(','));
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([[head.join(','), ...lines].join('\n')], { type: 'text/csv' }));
    a.download = 'intervai-history.csv';
    a.click();
  };

  return (
    <Shell>
      <main className="page">
        <div className="top">
          <div><h1>History</h1><p>{rows ? `${rows.length} interview${rows.length === 1 ? '' : 's'}` : ''}</p></div>
          <div className="acts">{shown.length ? <button className="btn ghost" onClick={csv}>Export CSV</button> : null}<Link className="btn" to="/interview/setup">New interview</Link></div>
        </div>
        <div className="row" style={{ marginTop: 16, gap: 8, flexWrap: 'wrap' }}>
          {['All', ...ROUNDS].map((r) => <button key={r} className={`opt ${round === r ? 'on' : ''}`} style={{ padding: '6px 12px' }} onClick={() => setRound(r)}>{r}</button>)}
        </div>
        {error ? <p className="err">{error}</p> : !rows ? <div className="loading">Loading…</div> : shown.length === 0 ? (
          <p className="empty">No interviews yet{round !== 'All' ? ` for ${round}` : ''}.</p>
        ) : (
          <table className="list" style={{ marginTop: 18 }}>
            <thead><tr><th>Round</th><th>Date</th><th>Difficulty</th><th>Result</th><th>Content</th><th>Delivery</th><th>Presence</th><th style={{ textAlign: 'right' }}>Score</th></tr></thead>
            <tbody>
              {shown.map((s) => {
                const ready = s.overall_score !== null || s.has_report;
                return (
                  <tr key={s.id} className="click" onClick={() => nav(ready ? `/report/${s.id}` : `/interview/processing/${s.id}`)}>
                    <td>{s.round_type}{s.role ? <span className="dim"> · {s.role}</span> : null}</td>
                    <td className="dm">{s.date_display || fmtDate(s.created_at)}</td>
                    <td className="dm">{s.difficulty}</td>
                    <td className="dm">{ready ? classLabel(s.classification) : s.status === 'active' ? 'Not finished' : 'Processing'}</td>
                    <td className="dm num">{scoreText(s.content_score)}</td>
                    <td className="dm num">{scoreText(s.speech_score)}</td>
                    <td className="dm num">{scoreText(s.face_score)}</td>
                    <td className="n">{scoreText(s.overall_score)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </main>
    </Shell>
  );
}

export function Settings() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const [sure, setSure] = useState(false);
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);

  const wipe = async () => {
    if (!sure) { setSure(true); return; }
    setBusy(true);
    try {
      await api.deleteMyData();
      setMsg('All your interviews, recordings, CVs and profile data were deleted.');
      setSure(false);
    } catch (e) {
      setMsg(errText(e, 'Deletion failed. Nothing was removed.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Shell>
      <main className="page narrow">
        <div className="top"><div><h1>Settings</h1><p>{user?.email}</p></div></div>
        <div className="sec row" style={{ justifyContent: 'space-between' }}>
          <div><h2>Account</h2><p className="dim" style={{ fontSize: 14 }}>{user?.name} · signed in with {user?.auth_provider === 'google' ? 'Google' : 'email'}</p></div>
          <button className="btn ghost" onClick={async () => { await logout(); nav('/'); }}>Log out</button>
        </div>
        <div className="sec row" style={{ justifyContent: 'space-between' }}>
          <div><h2>Profile & CV</h2><p className="dim" style={{ fontSize: 14 }}>Education, target role, CV and skills Ava uses for questions.</p></div>
          <Link className="btn ghost" to="/onboarding">Edit</Link>
        </div>
        <div className="sec row" style={{ justifyContent: 'space-between' }}>
          <div><h2>Appearance</h2><p className="dim" style={{ fontSize: 14 }}>Light or dark paper.</p></div>
          <ThemeButton className="btn ghost" />
        </div>
        <div className="sec">
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <div><h2>Delete my data</h2><p className="dim" style={{ fontSize: 14 }}>Permanently removes every interview, recording, transcript, report, CV and profile. Your login stays.</p></div>
            <button className="btn ghost" style={sure ? { borderColor: 'var(--ink)', color: 'var(--ink)' } : {}} disabled={busy} onClick={wipe}>{busy ? 'Deleting…' : sure ? 'Click again to delete' : 'Delete everything'}</button>
          </div>
          {msg ? <p style={{ fontSize: 14, marginTop: 12 }}>{msg}</p> : null}
        </div>
      </main>
    </Shell>
  );
}
