import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api, DashboardSessionItem, ImprovementPlanAction, SessionReportResponse, SessionResultData, SessionScoresResponse } from '../api';
import { useAuth } from '../authContext';
import { classLabel, errText, fmtDate, scoreText, Shell } from './ui';

export default function Report() {
  const { id } = useParams();
  const sessionId = Number(id);
  const { user } = useAuth();
  const nav = useNavigate();
  const [rep, setRep] = useState<SessionReportResponse | null>(null);
  const [res, setRes] = useState<SessionResultData | null>(null);
  const [scores, setScores] = useState<SessionScoresResponse | null>(null);
  const [plan, setPlan] = useState<ImprovementPlanAction[]>([]);
  const [stored, setStored] = useState<DashboardSessionItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [open, setOpen] = useState<number | null>(null);

  useEffect(() => {
    (async () => {
      const [r, s, sc] = await Promise.allSettled([api.getSessionReport(sessionId), api.getSessionResult(sessionId), api.getSessionScores(sessionId)]);
      if (r.status === 'fulfilled') setRep(r.value);
      else {
        try { setRep(await api.triggerReportGeneration(sessionId)); }
        catch (e) { if (s.status !== 'fulfilled') setError(errText(e, 'This report is not ready yet')); }
      }
      if (s.status === 'fulfilled') setRes(s.value);
      if (sc.status === 'fulfilled') setScores(sc.value);
      if (user) api.listUserSessions().then((l) => setStored(l.sessions.find((x) => x.id === sessionId) || null)).catch(() => {});
      api.getImprovementPlan(sessionId).then((p) => setPlan(p.actions || [])).catch(() => {});
      setLoading(false);
    })();
  }, [sessionId]);

  const pdf = async () => {
    try {
      const blob = await api.downloadReportPdf(sessionId);
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `intervai-report-${sessionId}.pdf`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    } catch (e) { setError(errText(e, 'Could not download the PDF')); }
  };

  const report = rep?.report;
  // The stored session score is the fallback when the per-signal recompute has nothing (e.g. seeded sessions).
  const overall = res?.overall_score ?? scores?.overall_scores?.composite_score ?? stored?.overall_score ?? null;
  const cls = (overall === null ? null : res?.classification && res.overall_score != null ? res.classification : stored?.classification) ?? res?.classification ?? scores?.classification ?? null;
  const mods: [string, number | null | undefined][] = [
    ['Content', res?.content_score ?? scores?.overall_scores?.content_score ?? stored?.content_score],
    ['Delivery', res?.speech_score ?? scores?.overall_scores?.speech_confidence_score ?? stored?.speech_score],
    ['Presence', res?.face_score ?? scores?.overall_scores?.face_posture_score ?? stored?.face_score],
  ];
  // Per-question rows: feedback text from the report, scores and question text from the score breakdown.
  const byId = new Map((scores?.per_question_breakdown || []).map((q) => [q.question_id, q]));
  const fb = report?.per_question_feedback || [];
  const rows = (fb.length ? fb.map((f) => ({ id: f.question_id, topic: f.topic, text: f.question_text || byId.get(f.question_id)?.question_text || '', score: f.score ?? byId.get(f.question_id)?.composite_score, f }))
    : (scores?.per_question_breakdown || []).map((q) => ({ id: q.question_id, topic: q.topic, text: q.question_text, score: q.composite_score, f: null as any })))
    .filter((r) => r.id !== 999 && r.topic !== 'Closing');
  const actions = plan.length ? plan : report?.improvement_plan || [];

  const body = loading ? <div className="loading">Loading report…</div> : (
    <main className="page">
      <div className="top">
        <div>
          <h1>{res?.round_type || 'Interview'} report</h1>
          <p>{res?.role ? `${res.role} · ` : ''}{fmtDate(res?.created_at || rep?.created_at)} · session {sessionId}</p>
        </div>
        <div className="acts">
          {user ? <button className="btn ghost" onClick={pdf}>Download PDF</button> : null}
          <Link className="btn" to={user ? `/interview/setup?round=${encodeURIComponent(res?.round_type || 'Technical')}` : '/signup'}>{user ? 'Practise again' : 'Create an account'}</Link>
        </div>
      </div>
      {error ? <p className="err">{error}</p> : null}

      <div className="sec" style={{ display: 'grid', gridTemplateColumns: 'minmax(220px,1fr) 2fr', gap: 36 }}>
        <div>
          <div className="k"><span>Overall</span></div>
          <div className="row" style={{ alignItems: 'flex-end', marginTop: 8 }}>
            <b className="num" style={{ fontSize: 96, fontWeight: 500, lineHeight: 0.9 }}>{scoreText(overall)}</b>
            <span style={{ paddingBottom: 8, fontSize: 14 }} className={cls === 'STRONG' ? 'good' : cls === 'WEAK' ? 'ink' : ''}>{classLabel(cls)}<br /><span className="dim">out of 100</span></span>
          </div>
          {overall === null ? <p className="dim" style={{ fontSize: 13, marginTop: 10 }}>No answers were captured, so this interview has no score.</p> : null}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 12, marginTop: 22 }}>
            {mods.map(([k, v]) => (
              <div key={k} style={{ fontSize: 13 }} className="dim">{k}<b className="num" style={{ display: 'block', fontSize: 20, fontWeight: 500, color: 'var(--fg)' }}>{scoreText(v)}</b><div className="bar"><i style={{ width: `${v ?? 0}%` }} /></div></div>
            ))}
          </div>
        </div>
        <div>
          <div className="k"><span>Summary</span></div>
          <p className="serif" style={{ fontSize: 22, lineHeight: 1.4, marginTop: 8 }}>{report?.overall_summary || 'The written summary is not available for this interview.'}</p>
        </div>
      </div>

      {(report?.strengths?.length || report?.gaps?.length) ? (
        <div className="sec grid2">
          <div>
            <div className="k"><span>What went well</span></div>
            {(report?.strengths || []).map((s, i) => <div key={i} style={{ padding: '12px 0', borderTop: '1px solid var(--line)' }}><b style={{ fontWeight: 500 }}>{s.title}</b><p className="dim" style={{ fontSize: 14 }}>{s.claim}</p></div>)}
            {!report?.strengths?.length ? <p className="empty">Nothing stood out yet.</p> : null}
          </div>
          <div>
            <div className="k"><span>What to work on</span></div>
            {(report?.gaps || []).map((s, i) => <div key={i} style={{ padding: '12px 0', borderTop: '1px solid var(--line)' }}><b style={{ fontWeight: 500 }}>{s.title}</b><p className="dim" style={{ fontSize: 14 }}>{s.claim}</p></div>)}
            {!report?.gaps?.length ? <p className="empty">No gaps flagged.</p> : null}
          </div>
        </div>
      ) : null}

      <div className="sec">
        <div className="k"><span>Answer by answer</span><span>Click a question to open it</span></div>
        {rows.length === 0 ? <p className="empty">No answers were scored.</p> : rows.map((r, i) => (
          <div key={r.id} style={{ borderTop: '1px solid var(--line)' }}>
            <button onClick={() => setOpen(open === i ? null : i)} style={{ width: '100%', display: 'grid', gridTemplateColumns: '44px 1fr 60px', gap: 12, padding: '14px 0', textAlign: 'left', alignItems: 'baseline' }}>
              <span className="dim" style={{ fontSize: 13 }}>Q{i + 1}</span>
              <span>{r.text || r.topic}<span className="dim" style={{ fontSize: 13 }}> · {r.topic}</span></span>
              <span className="num" style={{ textAlign: 'right', fontSize: 16 }}>{scoreText(r.score)}</span>
            </button>
            {open === i ? (
              <div style={{ padding: '0 0 18px 56px', display: 'grid', gap: 14, fontSize: 14 }}>
                {r.f?.what_was_good ? <div><div className="k"><span>Good</span></div><p>{r.f.what_was_good}</p></div> : null}
                {r.f?.what_was_missing ? <div><div className="k"><span>Missing</span></div><p>{r.f.what_was_missing}</p></div> : null}
                {r.f?.sample_answer_outline ? <div><div className="k"><span>A strong answer would cover</span></div><p style={{ whiteSpace: 'pre-line' }}>{r.f.sample_answer_outline}</p></div> : null}
                {byId.get(r.id)?.all_deductions?.length ? (
                  <div><div className="k"><span>Where points were lost</span></div>
                    {byId.get(r.id)!.all_deductions.slice(0, 5).map((d, j) => <p key={j} className="dim">−{Math.round(d.deduction)} · {d.reason}</p>)}
                  </div>
                ) : null}
                {!r.f && !byId.get(r.id)?.all_deductions?.length ? <p className="dim">No detailed feedback for this answer.</p> : null}
              </div>
            ) : null}
          </div>
        ))}
      </div>

      {actions.length ? (
        <div className="sec">
          <div className="k"><span>What to practise next</span></div>
          {actions.map((a) => (
            <div key={a.id} style={{ padding: '14px 0', borderTop: '1px solid var(--line)', display: 'grid', gridTemplateColumns: '1fr auto', gap: 16 }}>
              <div>
                <b style={{ fontWeight: 500 }}>{a.title}</b> <span className={a.priority === 'HIGH' ? 'ink' : 'dim'} style={{ fontSize: 12 }}>{a.priority === 'HIGH' ? 'High priority' : ''}</span>
                <p className="dim" style={{ fontSize: 14 }}>{a.description}</p>
                {a.resources?.length ? <p style={{ fontSize: 13, marginTop: 6 }}>{a.resources.slice(0, 3).map((r) => <a key={r.url} className="ink" href={r.url} target="_blank" rel="noreferrer" style={{ marginRight: 14 }}>{r.title} ↗</a>)}</p> : null}
              </div>
              {user ? <button className="link" style={{ fontSize: 13 }} onClick={() => nav(`/interview/setup?focus=${encodeURIComponent(a.topic)}`)}>Practise</button> : null}
            </div>
          ))}
        </div>
      ) : null}

      {!user ? (
        <div className="sec row" style={{ justifyContent: 'space-between' }}>
          <span>Guest reports are deleted after 24 hours. Create an account to keep this one and track progress.</span>
          <Link className="btn" to="/signup">Create an account</Link>
        </div>
      ) : null}
    </main>
  );

  return user ? <Shell>{body}</Shell> : <div className="solo">{body}</div>;
}
