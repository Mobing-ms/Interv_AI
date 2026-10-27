import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api, DashboardSummaryResponse } from '../api';
import { useAuth } from '../authContext';
import { classLabel, errText, fmtDate, scoreText, Shell } from './ui';
import './dashboard.css';

function Trend({ points }: { points: { score: number; date: string; round: string }[] }) {
  if (points.length < 2) {
    return <p className="empty">The chart appears after two scored interviews.</p>;
  }
  const W = 1000, H = 190, top = 20, bottom = 160;
  const lo = Math.max(0, Math.min(...points.map((p) => p.score)) - 10);
  const hi = Math.min(100, Math.max(...points.map((p) => p.score)) + 10);
  const x = (i: number) => 40 + (i * (W - 80)) / (points.length - 1);
  const y = (s: number) => bottom - ((s - lo) / Math.max(1, hi - lo)) * (bottom - top);
  const mid = Math.round((lo + hi) / 2);
  return (
    <svg className="ch" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet" role="img" aria-label="Score by interview">
      {[hi, mid, lo].map((v) => (
        <g key={v}><line className="g" x1="0" x2={W} y1={y(v)} y2={y(v)} /><text x="0" y={y(v) - 4}>{Math.round(v)}</text></g>
      ))}
      <polyline className="l" points={points.map((p, i) => `${x(i)},${y(p.score)}`).join(' ')} />
      {points.map((p, i) => (
        <g key={i}>
          <circle className={i === points.length - 1 ? 'last' : ''} cx={x(i)} cy={y(p.score)} r={i === points.length - 1 ? 5 : 4}>
            <title>{`${p.round} · ${Math.round(p.score)}`}</title>
          </circle>
          {points.length <= 8 ? <text x={x(i) - 20} y={H - 5}>{`${fmtDate(p.date)} · ${p.round[0]}`}</text> : null}
        </g>
      ))}
    </svg>
  );
}

export default function Dashboard() {
  const { user } = useAuth();
  const nav = useNavigate();
  const [d, setD] = useState<DashboardSummaryResponse | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    api.getDashboardSummary().then(setD).catch((e) => setError(errText(e, 'Could not load the dashboard')));
  }, []);

  const today = new Date().toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' });
  const last = d?.last_session;
  const weak = d?.current_weak_areas || [];
  const topics = Object.entries(d?.topic_scores || {}).sort((a, b) => a[1] - b[1]);
  const scored = (d?.recent_sessions || []).filter((s) => s.overall_score !== null);
  const best = (() => {
    const by: Record<string, number[]> = {};
    scored.forEach((s) => (by[s.round_type] ||= []).push(s.overall_score!));
    const avg = Object.entries(by).map(([r, xs]) => [r, xs.reduce((a, b) => a + b, 0) / xs.length] as const);
    return avg.sort((a, b) => b[1] - a[1])[0];
  })();
  const practise = (topic: string) => nav(`/interview/setup?focus=${encodeURIComponent(topic)}`);

  return (
    <Shell>
      <main className="page dash">
        <div className="top">
          <div>
            <h1>{user ? `Hi, ${user.name.split(' ')[0]}` : 'Dashboard'}</h1>
            <p>{today}{d ? ` · ${d.session_count} interview${d.session_count === 1 ? '' : 's'} so far` : ''}</p>
          </div>
          <div className="acts">
            {weak.length ? <button className="btn ghost" onClick={() => practise(weak.slice(0, 3).join(','))}>Retake weak areas</button> : null}
            <Link className="btn" to="/interview/setup">New interview</Link>
          </div>
        </div>

        {error ? <p className="err">{error}</p> : !d ? <div className="loading">Loading…</div> : (
          <div className="grid">
            {d.profile_confirmed ? null : (
              <div className="cell full notice">
                <span>Add your CV and target role so Ava asks about your real experience.</span>
                <Link className="btn" to="/onboarding">Finish your profile</Link>
              </div>
            )}

            <div className="cell last">
              {last ? (
                <>
                  <div className="k"><span>Last interview · {last.round_type} · {fmtDate(last.created_at)}</span>
                    {last.has_report || last.overall_score !== null ? <Link to={`/report/${last.id}`}>Full report</Link> : null}</div>
                  <div className="score">
                    <b className="num">{scoreText(last.overall_score)}</b>
                    <div>
                      <span className={`cls ${last.classification === 'WEAK' ? 'ink' : last.classification === 'STRONG' ? 'good' : ''}`}>{classLabel(last.classification)}</span>
                      <br />out of 100 · {last.role || last.difficulty}
                    </div>
                  </div>
                  <div className="mods">
                    {([['Content', last.content_score], ['Delivery', last.speech_score], ['Presence', last.face_score]] as const).map(([k, v]) => (
                      <div key={k}>{k}<b className="num">{scoreText(v)}</b><div className="bar"><i style={{ width: `${v ?? 0}%` }} /></div></div>
                    ))}
                  </div>
                </>
              ) : (
                <>
                  <div className="k"><span>Last interview</span></div>
                  <h2 className="serif first">No interviews yet.</h2>
                  <p className="dim" style={{ marginTop: 8 }}>Your first one takes about ten minutes. You'll get a score for every answer.</p>
                  <div style={{ marginTop: 'auto', paddingTop: 18 }}><Link className="btn" to="/interview/setup">Start your first interview</Link></div>
                </>
              )}
            </div>

            <div className="cell stats">
              <div><div className="k">Interviews</div><b>{d.session_count}</b><small>{d.all_sessions_count} started</small></div>
              <div><div className="k">Average</div><b>{d.session_count ? Math.round(d.average_score) : '—'}</b><small>across scored</small></div>
              <div><div className="k">Best round</div><b>{best ? best[0] : '—'}</b><small>{best ? `${Math.round(best[1])} avg` : 'no scores yet'}</small></div>
              <div><div className="k">Next up</div><b>{d.recommended_next_round || '—'}</b><small>recommended</small></div>
              <div className="rhythm">
                <div className="k"><span>Score by interview</span><Link to="/history">History</Link></div>
                <Trend points={d.trend_scores} />
              </div>
            </div>

            <div className="cell focus">
              <div className="k"><span>Focus areas · from your answers</span><span>Click to practise</span></div>
              <div className="fl">
                {topics.length === 0 && weak.length === 0 ? <p className="empty">Nothing yet. Focus areas come from your scored answers.</p> : null}
                {(topics.length ? topics : weak.map((w) => [w, NaN] as [string, number])).slice(0, 5).map(([t, s]) => (
                  <button key={t} onClick={() => practise(t)}>
                    <span>{t}{weak.includes(t) ? <small>Flagged as weak</small> : null}</span>
                    <span className={`d ${!isNaN(s) && s < 60 ? 'ink' : 'good'}`}>{isNaN(s) ? 'weak' : Math.round(s)}</span>
                    <span className="go">Practise</span>
                  </button>
                ))}
              </div>
            </div>

            <div className="cell recent">
              <div className="k"><span>Recent interviews</span><Link to="/history">All</Link></div>
              {d.recent_sessions.length === 0 ? <p className="empty">Your interviews will be listed here.</p> : (
                <table className="list">
                  <tbody>
                    {d.recent_sessions.slice(0, 5).map((s) => (
                      <tr key={s.id} className="click" onClick={() => nav(s.overall_score !== null || s.has_report ? `/report/${s.id}` : `/interview/processing/${s.id}`)}>
                        <td>{s.round_type}{s.role ? ` · ${s.role}` : ''}</td>
                        <td className="dm">{s.date_display || fmtDate(s.created_at)}</td>
                        <td className="dm">{classLabel(s.classification)}</td>
                        <td className="n">{scoreText(s.overall_score)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            <div className="cell next">
              <Link to={`/interview/setup?round=${encodeURIComponent(d.quick_actions?.try_next_round?.round_type || 'Mixed')}`}>
                <span className="k">Next round</span><h3>{d.quick_actions?.try_next_round?.label || 'Try a Mixed round'}</h3><p>Put the rounds together.</p>
              </Link>
              <Link to={`/interview/setup?round=${encodeURIComponent(d.quick_actions?.retake_same_round?.round_type || last?.round_type || 'Technical')}`}>
                <span className="k">Retake</span><h3>{d.quick_actions?.retake_same_round?.label || 'Retake the same round'}</h3><p>See if the score moves.</p>
              </Link>
              <Link to="/onboarding">
                <span className="k">Profile</span><h3>Update your CV and target role</h3><p>Questions get closer to the real role.</p>
              </Link>
            </div>
          </div>
        )}
      </main>
    </Shell>
  );
}
