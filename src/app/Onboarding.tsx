import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, CrossCheckFlag, StructuredCV } from '../api';
import { useAuth } from '../authContext';
import { Chips, errText, fmtDate, Shell, Steps } from './ui';

const EMPTY_CV: StructuredCV = {
  personal: { name: '', email: '', phone: '', links: [] },
  education: [],
  skills: { languages: [], frameworks: [], tools: [], domains: [], soft: [] },
  projects: [],
  internships_experience: [],
  certifications: [],
  achievements: [],
};

const SKILL_GROUPS: [keyof StructuredCV['skills'], string][] = [
  ['languages', 'Languages'], ['frameworks', 'Frameworks'], ['tools', 'Tools'], ['domains', 'Domains'], ['soft', 'Soft skills'],
];

// Three steps: CV (parsed and used to prefill) → about you → review and confirm. Each step saves, so it can be resumed.
// The confirmed profile is what every new interview uses, so the CV is uploaded once.
export default function Onboarding() {
  const { user, refreshUser } = useAuth();
  const nav = useNavigate();
  const [step, setStep] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const [edu, setEdu] = useState({ degree: '', branch: '', college: '', graduation_year: '', cgpa: '', cgpa_scale: '10' });
  const [target, setTarget] = useState({ target_role: '', company_type: '', experience_level: '', job_description: '' });
  const [opts, setOpts] = useState<{ roles: string[]; companies: string[]; levels: string[] }>({ roles: [], companies: [], levels: [] });

  const [cvId, setCvId] = useState<number | null>(null);
  const [cvName, setCvName] = useState('');
  const [cvState, setCvState] = useState<'none' | 'uploading' | 'extracting' | 'extracted' | 'failed'>('none');
  const [cv, setCv] = useState<StructuredCV>(EMPTY_CV);
  const [flags, setFlags] = useState<CrossCheckFlag[]>([]);
  const [ack, setAck] = useState<Set<number>>(new Set());
  const fileRef = useRef<HTMLInputElement>(null);
  const [cvDate, setCvDate] = useState<string | null>(null);
  const [parsing, setParsing] = useState(false);
  const [prefilled, setPrefilled] = useState('');
  const [confirmed, setConfirmed] = useState(false);

  useEffect(() => {
    (async () => {
      const [st, e, t, sug, latest, prof] = await Promise.allSettled([
        api.getOnboardingStatus(), api.getEducationProfile(), api.getTargetProfile(), api.getTargetSuggestions(), api.getLatestCV(), api.getCanonicalProfile(),
      ]);
      if (e.status === 'fulfilled' && e.value) {
        const v = e.value;
        setEdu({ degree: v.degree || '', branch: v.branch || '', college: v.college || '', graduation_year: v.graduation_year ? String(v.graduation_year) : '', cgpa: v.cgpa != null ? String(v.cgpa) : '', cgpa_scale: v.cgpa_scale ? String(v.cgpa_scale) : '10' });
      }
      if (t.status === 'fulfilled' && t.value) {
        const v = t.value;
        setTarget({ target_role: v.target_role || '', company_type: v.company_type || '', experience_level: v.experience_level || '', job_description: v.job_description || '' });
      }
      if (sug.status === 'fulfilled') setOpts({ roles: sug.value.suggestions || [], companies: sug.value.company_types || [], levels: sug.value.experience_levels || [] });
      if (latest.status === 'fulfilled' && latest.value?.id) {
        setCvId(latest.value.id);
        setCvName(latest.value.filename);
        setCvState(latest.value.status === 'extracted' ? 'extracted' : latest.value.status === 'failed' ? 'failed' : 'extracting');
        setCvDate(latest.value.extracted_at || latest.value.created_at);
      }
      if (prof.status === 'fulfilled' && prof.value?.structured_data) setCv({ ...EMPTY_CV, ...prof.value.structured_data });
      else if (latest.status === 'fulfilled' && latest.value?.status === 'extracted') {
        // A CV uploaded earlier but never confirmed: reuse its parsed details instead of asking again
        try {
          const p = await api.getLatestParsedCV();
          setCv({ ...EMPTY_CV, ...p.structured_data });
          setFlags(p.cross_check_flags || []);
        } catch {}
      }
      if (st.status === 'fulfilled') {
        const s = st.value;
        setConfirmed(s.profile_confirmed);
        // A finished profile opens on the CV, with every step reachable; a new one resumes where it stopped
        setStep(s.profile_confirmed ? 0 : !s.cv_done && !s.education_done ? 0 : !s.education_done || !s.target_done ? 1 : 2);
      }
      setLoading(false);
    })();
  }, []);

  const saveAbout = async () => {
    setError('');
    if (!edu.degree || !edu.branch || !edu.college || !edu.graduation_year) { setError('Fill in degree, field, college and graduation year.'); return; }
    if (!target.target_role || !target.company_type || !target.experience_level) { setError('Fill in the target role, company type and experience level.'); return; }
    setBusy(true);
    try {
      await api.saveEducationProfile({
        degree: edu.degree, branch: edu.branch, college: edu.college, graduation_year: Number(edu.graduation_year),
        cgpa: edu.cgpa ? Number(edu.cgpa) : null, cgpa_scale: edu.cgpa ? Number(edu.cgpa_scale) : null,
      });
      await api.saveTargetProfile({ ...target, job_description: target.job_description || null });
      setStep(2);
    } catch (e) { setError(errText(e, 'Could not save')); }
    finally { setBusy(false); }
  };

  const upload = async (file: File) => {
    setError('');
    setCvName(file.name);
    setCvState('uploading');
    try {
      const r = await api.uploadCV(file);
      setCvId(r.id);
      setCvState('extracting');
      for (let i = 0; i < 40; i++) {
        await new Promise((res) => setTimeout(res, 1000));
        const s = await api.getCVStatus(r.id);
        if (s.status === 'extracted') { setCvState('extracted'); setCvDate(s.extracted_at || s.created_at); await parseAndPrefill(r.id); return; }
        if (s.status === 'failed') { setCvState('failed'); setError(s.error_message || 'Could not read that file. Try a different PDF or DOCX.'); return; }
      }
      setCvState('failed');
      setError('Reading the CV took too long. Try uploading again.');
    } catch (e) {
      setCvState('failed');
      setError(errText(e, 'Upload failed'));
    }
  };

  // Structure the CV and copy what it says into any form fields that are still empty.
  const parseAndPrefill = async (id: number) => {
    setParsing(true);
    try {
      const p = await api.parseCV(id);
      const data = { ...EMPTY_CV, ...p.structured_data };
      if (!data.personal.name && user) data.personal = { ...data.personal, name: user.name, email: data.personal.email || user.email };
      setCv(data);
      setFlags(p.cross_check_flags || []);
      setAck(new Set());
      const e0 = data.education[0];
      if (e0) {
        setEdu((cur) => ({
          ...cur,
          degree: cur.degree || e0.degree || '',
          branch: cur.branch || e0.branch || '',
          college: cur.college || e0.college || '',
          graduation_year: cur.graduation_year || (e0.year ? String(e0.year).match(/\d{4}/)?.[0] || '' : ''),
          cgpa: cur.cgpa || (e0.cgpa != null && !isNaN(Number(e0.cgpa)) ? String(e0.cgpa) : ''),
          cgpa_scale: cur.cgpa ? cur.cgpa_scale : e0.cgpa != null && Number(e0.cgpa) <= 4 ? '4' : cur.cgpa_scale,
        }));
      }
      const exp = data.internships_experience.length;
      setPrefilled(`Filled in from your CV: education, ${Object.values(data.skills).flat().length} skills, ${data.projects.length} projects${exp ? `, ${exp} roles` : ''}. Check the details below.`);
    } catch (e) {
      setError(errText(e, 'Could not read the structure of the CV; you can fill the details in by hand.'));
    } finally { setParsing(false); }
  };

  const confirm = async () => {
    setError('');
    const blocking = flags.filter((f, i) => f.severity === 'HIGH' && !ack.has(i));
    if (blocking.length) { setError('Review the highlighted mismatches first.'); return; }
    setBusy(true);
    try {
      const data: StructuredCV = cv.education.length ? cv : {
        ...cv,
        education: [{ degree: edu.degree, branch: edu.branch, college: edu.college, year: edu.graduation_year, cgpa: edu.cgpa || null }],
      };
      await api.confirmProfile({ structured_data: data, unresolved_flags: flags.filter((_, i) => !ack.has(i)), cv_document_id: cvId });
      await refreshUser();
      nav('/dashboard');
    } catch (e) { setError(errText(e, 'Could not save your profile')); }
    finally { setBusy(false); }
  };

  const setSkill = (k: keyof StructuredCV['skills'], v: string[]) => setCv({ ...cv, skills: { ...cv.skills, [k]: v } });

  if (loading) return <Shell><div className="loading">Loading your profile…</div></Shell>;

  return (
    <Shell>
      <main className="page narrow">
        <div className="top"><div><h1>Profile & CV</h1><p>Ava uses this to ask about your real experience and target role.</p></div></div>
        <Steps total={3} at={step} />
        <div className="row" style={{ gap: 18, marginTop: 10, fontSize: 13 }}>
          {['CV', 'About you', 'Review'].map((s, i) => (
            <button key={s} className={i === step ? 'ink' : 'dim'} onClick={() => (confirmed || i < step) && setStep(i)} disabled={!confirmed && i > step}>{i + 1}. {s}</button>
          ))}
        </div>

        {step === 1 ? (
          <>
            {prefilled ? <p className="sec good" style={{ fontSize: 14 }}>{prefilled}</p> : null}
            <div className="sec">
              <h2>Education</h2>
              <div className="grid2">
                <label className="field"><span>Degree</span><input value={edu.degree} placeholder="B.Tech, MSc…" onChange={(e) => setEdu({ ...edu, degree: e.target.value })} /></label>
                <label className="field"><span>Field of study</span><input value={edu.branch} placeholder="Computer Science" onChange={(e) => setEdu({ ...edu, branch: e.target.value })} /></label>
                <label className="field"><span>College / university</span><input value={edu.college} onChange={(e) => setEdu({ ...edu, college: e.target.value })} /></label>
                <label className="field"><span>Graduation year</span><input type="number" value={edu.graduation_year} onChange={(e) => setEdu({ ...edu, graduation_year: e.target.value })} /></label>
                <label className="field"><span>Grade (optional)</span><input type="number" step="0.01" value={edu.cgpa} onChange={(e) => setEdu({ ...edu, cgpa: e.target.value })} /></label>
                <label className="field"><span>Out of</span>
                  <select value={edu.cgpa_scale} onChange={(e) => setEdu({ ...edu, cgpa_scale: e.target.value })}><option value="10">10</option><option value="4">4</option><option value="100">100</option></select>
                </label>
              </div>
            </div>
            <div className="sec">
              <h2>Target</h2>
              <div className="grid2">
                <label className="field"><span>Target role</span><input list="roles" value={target.target_role} placeholder="Backend engineer" onChange={(e) => setTarget({ ...target, target_role: e.target.value })} />
                  <datalist id="roles">{opts.roles.map((r) => <option key={r} value={r} />)}</datalist></label>
                <label className="field"><span>Experience level</span>
                  <select value={target.experience_level} onChange={(e) => setTarget({ ...target, experience_level: e.target.value })}>
                    <option value="">Choose…</option>{(opts.levels.length ? opts.levels : ['Fresher', 'Junior', 'Mid', 'Senior']).map((l) => <option key={l}>{l}</option>)}
                  </select></label>
                <label className="field"><span>Company type</span>
                  <select value={target.company_type} onChange={(e) => setTarget({ ...target, company_type: e.target.value })}>
                    <option value="">Choose…</option>{(opts.companies.length ? opts.companies : ['Startup', 'Product', 'Service', 'Big tech']).map((l) => <option key={l}>{l}</option>)}
                  </select></label>
              </div>
              <label className="field"><span>Job description (optional, makes questions closer to the role)</span>
                <textarea value={target.job_description} onChange={(e) => setTarget({ ...target, job_description: e.target.value })} /></label>
            </div>
            {error ? <p className="err">{error}</p> : null}
            <div className="stepnav"><button className="link" onClick={() => setStep(0)}>Back</button><button className="btn" disabled={busy} onClick={saveAbout}>{busy ? 'Saving…' : 'Next'}</button></div>
          </>
        ) : null}

        {step === 0 ? (
          <>
            <div className="sec">
              <h2>Your CV</h2>
              <p className="dim" style={{ fontSize: 14 }}>PDF or DOCX. Upload it once: it fills in the rest of your profile, and every new interview asks about your projects and experience from it.</p>
              <div
                onClick={() => fileRef.current?.click()}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) upload(f); }}
                style={{ marginTop: 16, border: '1px dashed var(--line)', padding: '36px 20px', textAlign: 'center', cursor: 'pointer', background: 'var(--soft)' }}>
                {cvState === 'none' ? 'Drop your CV here or click to choose a file'
                  : cvState === 'uploading' ? `Uploading ${cvName}…`
                  : cvState === 'extracting' ? `Reading ${cvName}…`
                  : parsing ? `Reading the details in ${cvName}…`
                  : cvState === 'extracted' ? <>✓ {cvName}{cvDate ? <span className="dim"> · uploaded {fmtDate(cvDate)}</span> : null} <span className="dim">· click or drop a file to replace</span></>
                  : <span className="ink">Couldn't read {cvName}. Click to try another file.</span>}
              </div>
              <input ref={fileRef} type="file" accept=".pdf,.docx" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = ''; }} />
            </div>
            {error ? <p className="err">{error}</p> : null}
            <div className="stepnav">
              <span />
              <div className="row">
                {cvState !== 'extracted' ? <button className="link" style={{ fontSize: 14 }} onClick={() => setStep(1)}>Skip, fill it in by hand</button> : null}
                <button className="btn" disabled={parsing || cvState === 'uploading' || cvState === 'extracting'} onClick={() => setStep(1)}>{parsing ? 'Reading your CV…' : 'Next'}</button>
              </div>
            </div>
          </>
        ) : null}

        {step === 2 ? (
          <>
            {flags.length ? (
              <div className="sec">
                <h2>Check these</h2>
                <p className="dim" style={{ fontSize: 14 }}>Your CV and the form don't agree here. Fix the form or CV if needed, then mark each as checked.</p>
                {flags.map((f, i) => (
                  <div key={i} className="row" style={{ justifyContent: 'space-between', padding: '12px 0', borderTop: '1px solid var(--line)', fontSize: 14 }}>
                    <div>
                      <span className={f.severity === 'HIGH' ? 'ink' : 'dim'} style={{ fontSize: 12 }}>{f.severity.toLowerCase()} · {f.field}</span>
                      <p>{f.message}</p>
                      {f.cv_value || f.form_value ? <p className="dim" style={{ fontSize: 13 }}>CV: {f.cv_value || '—'} · Form: {f.form_value || '—'}</p> : null}
                    </div>
                    <button className={ack.has(i) ? 'good' : 'link'} onClick={() => { const n = new Set(ack); n.has(i) ? n.delete(i) : n.add(i); setAck(n); }}>{ack.has(i) ? '✓ Checked' : 'Mark checked'}</button>
                  </div>
                ))}
              </div>
            ) : null}

            <div className="sec">
              <h2>Contact</h2>
              <div className="grid2">
                <label className="field"><span>Name</span><input value={cv.personal.name || ''} onChange={(e) => setCv({ ...cv, personal: { ...cv.personal, name: e.target.value } })} /></label>
                <label className="field"><span>Email</span><input value={cv.personal.email || ''} onChange={(e) => setCv({ ...cv, personal: { ...cv.personal, email: e.target.value } })} /></label>
                <label className="field"><span>Phone</span><input value={cv.personal.phone || ''} onChange={(e) => setCv({ ...cv, personal: { ...cv.personal, phone: e.target.value } })} /></label>
              </div>
              <div className="field"><span>Links</span><Chips items={cv.personal.links} onRemove={(v) => setCv({ ...cv, personal: { ...cv.personal, links: cv.personal.links.filter((x) => x !== v) } })} onAdd={(v) => setCv({ ...cv, personal: { ...cv.personal, links: [...cv.personal.links, v] } })} placeholder="Add a link and press Enter" /></div>
            </div>

            <div className="sec">
              <h2>Skills</h2>
              {SKILL_GROUPS.map(([k, label]) => (
                <div className="field" key={k}><span>{label}</span>
                  <Chips items={cv.skills[k] || []} onRemove={(v) => setSkill(k, cv.skills[k].filter((x) => x !== v))} onAdd={(v) => setSkill(k, [...(cv.skills[k] || []), v])} />
                </div>
              ))}
            </div>

            <div className="sec">
              <h2>Experience</h2>
              {cv.internships_experience.length === 0 ? <p className="empty">None listed.</p> : cv.internships_experience.map((x, i) => (
                <div key={i} className="row" style={{ justifyContent: 'space-between', padding: '10px 0', borderTop: '1px solid var(--line)', fontSize: 14 }}>
                  <span><b style={{ fontWeight: 500 }}>{x.role}</b> · {x.company}{x.duration ? <span className="dim"> · {x.duration}</span> : null}</span>
                  <button className="link" onClick={() => setCv({ ...cv, internships_experience: cv.internships_experience.filter((_, j) => j !== i) })}>Remove</button>
                </div>
              ))}
              <h2 style={{ marginTop: 22 }}>Projects</h2>
              {cv.projects.length === 0 ? <p className="empty">None listed.</p> : cv.projects.map((x, i) => (
                <div key={i} className="row" style={{ justifyContent: 'space-between', padding: '10px 0', borderTop: '1px solid var(--line)', fontSize: 14 }}>
                  <span><b style={{ fontWeight: 500 }}>{x.title}</b>{x.tech_stack?.length ? <span className="dim"> · {x.tech_stack.join(', ')}</span> : null}</span>
                  <button className="link" onClick={() => setCv({ ...cv, projects: cv.projects.filter((_, j) => j !== i) })}>Remove</button>
                </div>
              ))}
            </div>

            <div className="sec grid2">
              <div className="field"><span>Certifications</span><Chips items={cv.certifications} onRemove={(v) => setCv({ ...cv, certifications: cv.certifications.filter((x) => x !== v) })} onAdd={(v) => setCv({ ...cv, certifications: [...cv.certifications, v] })} /></div>
              <div className="field"><span>Achievements</span><Chips items={cv.achievements} onRemove={(v) => setCv({ ...cv, achievements: cv.achievements.filter((x) => x !== v) })} onAdd={(v) => setCv({ ...cv, achievements: [...cv.achievements, v] })} /></div>
            </div>

            {error ? <p className="err">{error}</p> : null}
            <div className="stepnav">
              <button className="link" onClick={() => setStep(1)}>Back</button>
              <button className="btn" disabled={busy} onClick={confirm}>{busy ? 'Saving…' : 'Confirm profile'}</button>
            </div>
          </>
        ) : null}
      </main>
    </Shell>
  );
}
