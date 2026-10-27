import { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { api, CVStatusResponse, InterviewBlueprint, UserContext } from '../api';
import { Chips, errText, ROUNDS, Shell } from './ui';

const ROUND_NOTE: Record<string, string> = {
  Technical: 'Concepts, problem solving and the projects on your CV.',
  HR: 'Motivation, behaviour and how you work with people.',
  Managerial: 'Prioritising, conflict, ownership and decisions.',
  Mixed: 'A bit of each, like a real loop.',
};

export default function Setup() {
  const nav = useNavigate();
  const [params] = useSearchParams();
  const initialRound = ROUNDS.find((r) => r === params.get('round')) || 'Technical';
  const initialFocus = (params.get('focus') || '').split(',').map((s) => s.trim()).filter(Boolean);

  const [round, setRound] = useState<string>(initialRound);
  const [difficulty, setDifficulty] = useState('Medium');
  const [duration, setDuration] = useState(15);
  const [pressure, setPressure] = useState(false);
  const [focus, setFocus] = useState<string[]>(initialFocus);
  const [ctx, setCtx] = useState<UserContext | null>(null);
  const [plan, setPlan] = useState<InterviewBlueprint | null>(null);
  const [cv, setCv] = useState<CVStatusResponse | null | undefined>(undefined);
  const [cvConfirmed, setCvConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    // Interviews use the confirmed profile, so a CV only counts once the profile is confirmed
    Promise.allSettled([api.getLatestCV(), api.getCanonicalProfile()]).then(([c, p]) => {
      const file = c.status === 'fulfilled' && c.value?.status === 'extracted' ? c.value : null;
      setCvConfirmed(p.status === 'fulfilled' && !!p.value?.cv_document_id);
      setCv(file);
    });
    api.getInterviewContext().then((c) => {
      setCtx(c);
      if (!params.get('round') && c.recommended_round && ROUNDS.includes(c.recommended_round as any)) setRound(c.recommended_round);
      if (c.recommended_difficulty && ['Easy', 'Medium', 'Hard', 'Adaptive'].includes(c.recommended_difficulty)) setDifficulty(c.recommended_difficulty);
    }).catch(() => {});
  }, []);

  // Preview of the plan the backend would build for these settings.
  useEffect(() => {
    const t = setTimeout(() => {
      api.generateInterviewBlueprint({ round_type: round, difficulty, duration_minutes: duration, mode: pressure ? 'pressure' : 'normal', focus_topics: focus })
        .then(setPlan).catch(() => setPlan(null));
    }, 300);
    return () => clearTimeout(t);
  }, [round, difficulty, duration, pressure, focus.join('|')]);

  const start = async () => {
    setBusy(true);
    setError('');
    try {
      const cfg = await api.saveInterviewConfig({
        round_type: round, difficulty, duration_minutes: duration, language: 'English',
        mode: pressure ? 'pressure' : 'normal', focus_topics: focus,
      });
      nav('/interview/precheck', { state: { configId: cfg.id } });
    } catch (e) {
      setError(errText(e, 'Could not save the interview settings'));
    } finally {
      setBusy(false);
    }
  };

  const weak = (ctx?.weak_areas || []).filter((w) => !focus.includes(w));

  return (
    <Shell>
      <main className="page narrow">
        <div className="top"><div><h1>New interview</h1><p>Pick the round, then check your camera and mic.</p></div></div>

        {cv !== undefined ? (
          <div className="sec row" style={{ justifyContent: 'space-between', fontSize: 14 }}>
            {cv && cvConfirmed ? <span>Using your CV <b style={{ fontWeight: 500 }}>{cv.filename}</b> <span className="dim">· questions will cover your projects and experience</span></span>
              : cv ? <span className="ink">{cv.filename} is uploaded but your profile isn't confirmed yet, so this interview won't use it.</span>
              : <span className="dim">No CV on your profile, so questions won't cover your own projects.</span>}
            <Link className="link" to="/onboarding">{cv && cvConfirmed ? 'Change' : cv ? 'Confirm profile' : 'Add your CV'}</Link>
          </div>
        ) : null}

        <div className="sec">
          <div className="k"><span>Round</span></div>
          <div className="opts" style={{ gridTemplateColumns: '1fr 1fr' }}>
            {ROUNDS.map((r) => (
              <button key={r} className={`opt ${round === r ? 'on' : ''}`} onClick={() => setRound(r)}>
                <b style={{ fontWeight: 500 }}>{r}</b><br /><span className="dim" style={{ fontSize: 13 }}>{ROUND_NOTE[r]}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="sec grid2">
          <div>
            <div className="k"><span>Difficulty</span></div>
            <div className="opts" style={{ gridTemplateColumns: 'repeat(4,1fr)' }}>
              {['Easy', 'Medium', 'Hard', 'Adaptive'].map((x) => (
                <button key={x} className={`opt ${difficulty === x ? 'on' : ''}`} onClick={() => setDifficulty(x)}>{x}</button>
              ))}
            </div>
          </div>
          <div>
            <div className="k"><span>Length</span></div>
            <div className="opts" style={{ gridTemplateColumns: 'repeat(4,1fr)' }}>
              {[10, 15, 30, 45].map((m) => (
                <button key={m} className={`opt ${duration === m ? 'on' : ''}`} onClick={() => setDuration(m)}>{m} min</button>
              ))}
            </div>
          </div>
        </div>

        <div className="sec">
          <label className="row" style={{ cursor: 'pointer', fontSize: 14 }}>
            <input type="checkbox" checked={pressure} onChange={(e) => setPressure(e.target.checked)} style={{ width: 'auto' }} />
            <span>Pressure mode <span className="dim">· shorter answer timer and more follow-ups</span></span>
          </label>
        </div>

        <div className="sec">
          <div className="k"><span>Focus topics · optional</span></div>
          <Chips items={focus} onRemove={(v) => setFocus(focus.filter((f) => f !== v))} onAdd={(v) => setFocus([...focus, v])} placeholder="Add a topic and press Enter" />
          {weak.length ? (
            <p className="dim" style={{ fontSize: 13, marginTop: 12 }}>
              From your past answers:{' '}
              {weak.map((w) => <button key={w} className="ink" style={{ marginRight: 10 }} onClick={() => setFocus([...focus, w])}>+ {w}</button>)}
            </p>
          ) : null}
        </div>

        {plan ? (
          <div className="sec">
            <div className="k"><span>Plan</span><span>{plan.total_question_count} questions · about {Math.round(plan.time_per_question_seconds / 60 * 10) / 10} min each</span></div>
            <table className="list">
              <tbody>
                {plan.topics.filter((t) => t.allocated_questions > 0).map((t) => (
                  <tr key={t.name}>
                    <td>{t.name}{t.is_weak_area ? <span className="ink" style={{ fontSize: 12 }}> · weak area</span> : null}</td>
                    <td className="dm">{t.category}</td>
                    <td className="n">{t.allocated_questions}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        {error ? <p className="err">{error}</p> : null}
        <div className="stepnav">
          <span className="dim" style={{ fontSize: 13 }}>{round} · {difficulty} · {duration} min</span>
          <button className="btn" onClick={start} disabled={busy}>{busy ? 'Saving…' : 'Continue to device check'}</button>
        </div>
      </main>
    </Shell>
  );
}
