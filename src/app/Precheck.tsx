import { useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { api, InterviewSession, tokenStorage } from '../api';
import { useAuth } from '../authContext';
import { errText, Steps } from './ui';

const READ_ALOUD = 'I am ready to begin my interview. I will take a moment to think before each answer and explain my reasoning clearly.';

// Consent → camera and mic → a short read-aloud baseline → session created → live room.
export default function Precheck() {
  const { user } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const guestId = tokenStorage.getGuestSessionId();
  const isGuest = !user && !!guestId;
  const [step, setStep] = useState<0 | 1 | 2>(0);
  const [agree, setAgree] = useState([false, false, false]);
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [deviceErr, setDeviceErr] = useState('');
  const [level, setLevel] = useState(0);
  const [peakDb, setPeakDb] = useState(-90);
  const [reading, setReading] = useState(false);
  const [secs, setSecs] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const videoRef = useRef<HTMLVideoElement>(null);
  const dbSamples = useRef<number[]>([]);

  useEffect(() => {
    if (isGuest) return;
    api.getLatestConsent().then((c) => { if (c?.accepted) setStep(1); }).catch(() => {});
  }, []);

  // Acquire camera + mic on the device step and drive the level meter.
  useEffect(() => {
    if (step < 1 || stream) return;
    let raf = 0, ctx: AudioContext | null = null, cancelled = false;
    navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true }, video: { width: { ideal: 640 }, height: { ideal: 480 } } })
      .then((s) => {
        if (cancelled) { s.getTracks().forEach((t) => t.stop()); return; }
        setStream(s);
        ctx = new AudioContext();
        const an = ctx.createAnalyser();
        an.fftSize = 1024;
        ctx.createMediaStreamSource(s).connect(an);
        const buf = new Float32Array(an.fftSize);
        const tick = () => {
          an.getFloatTimeDomainData(buf);
          let sum = 0;
          for (const v of buf) sum += v * v;
          const rms = Math.sqrt(sum / buf.length);
          const db = 20 * Math.log10(Math.max(rms, 1e-5));
          setLevel(Math.min(100, Math.max(0, (db + 60) * 2)));
          dbSamples.current.push(db);
          if (dbSamples.current.length > 600) dbSamples.current.shift();
          setPeakDb((p) => Math.max(p, db));
          raf = requestAnimationFrame(tick);
        };
        tick();
      })
      .catch((e) => setDeviceErr(e?.name === 'NotAllowedError' ? 'Camera or microphone access was blocked. Allow it in the address bar, then retry.' : 'No camera or microphone found.'));
    return () => { cancelled = true; cancelAnimationFrame(raf); ctx?.close(); };
  }, [step, stream]);

  useEffect(() => {
    if (videoRef.current && stream) { videoRef.current.srcObject = stream; videoRef.current.play().catch(() => {}); }
  }, [stream, step]);

  // Release the devices when leaving; the live room opens its own stream.
  useEffect(() => () => { stream?.getTracks().forEach((t) => t.stop()); }, [stream]);

  useEffect(() => {
    if (!reading) return;
    if (secs <= 0) { setReading(false); return; }
    const t = setTimeout(() => setSecs(secs - 1), 1000);
    return () => clearTimeout(t);
  }, [reading, secs]);

  const consent = async () => {
    setError('');
    if (isGuest) { setStep(1); return; }
    try { await api.saveConsent('v1.0'); setStep(1); }
    catch (e) { setError(errText(e, 'Could not save your consent')); }
  };

  const launch = async () => {
    setBusy(true);
    setError('');
    try {
      let session: InterviewSession;
      if (guestId && !user) {
        session = await api.getSession(guestId);
      } else {
        let cfgId: number | undefined = (loc.state as any)?.configId;
        if (!cfgId) { try { cfgId = (await api.getLatestInterviewConfig()).id; } catch {} }
        session = await api.createSession(cfgId);
      }
      const samples = dbSamples.current.filter((d) => d > -70);
      const avg = samples.length ? samples.reduce((a, b) => a + b, 0) / samples.length : null;
      const quiet = [...dbSamples.current].sort((a, b) => a - b)[Math.floor(dbSamples.current.length * 0.1)] ?? null;
      await api.saveCalibration(session.id, {
        voice_baseline: avg !== null ? { average_volume_db: Math.round(avg * 10) / 10 } : {},
        ...(quiet !== null ? { background_noise_level_db: Math.round(quiet * 10) / 10 } : {}),
        calibration_text: READ_ALOUD,
      }).catch(() => {});
      stream?.getTracks().forEach((t) => t.stop());
      nav(`/interview/live/${session.id}`, { state: { wsUrl: session.ws_url } });
    } catch (e) {
      setError(errText(e, 'Could not start the session'));
      setBusy(false);
    }
  };

  const camOk = !!stream?.getVideoTracks().length;
  const micOk = peakDb > -45;

  return (
    <main className="page solo-narrow" style={{ margin: '0 auto' }}>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <Link className="brand" to={user ? '/dashboard' : '/'}>IntervAI</Link>
        <Link className="link" style={{ fontSize: 14 }} to={user ? '/interview/setup' : '/guest/setup'}>Back</Link>
      </div>
      <Steps total={3} at={step} />
      <p className="dim" style={{ fontSize: 13, marginTop: 10 }}>Step {step + 1} of 3 · {['Consent', 'Camera and microphone', 'Voice check'][step]}</p>

      {step === 0 ? (
        <div className="sec">
          <h2 className="serif" style={{ fontSize: 30 }}>Before you start</h2>
          <p className="dim" style={{ marginTop: 6 }}>Ava records your answers to score them. Please confirm:</p>
          {[
            'Record my camera and microphone during the interview.',
            'Analyse my answers, voice and posture with AI to produce a report.',
            isGuest ? 'Keep the recording for 24 hours, then delete it.' : 'Keep the recording for 30 days. I can delete it any time in Settings.',
          ].map((t, i) => (
            <label key={i} className="row" style={{ marginTop: 16, cursor: 'pointer', alignItems: 'flex-start' }}>
              <input type="checkbox" style={{ width: 'auto', marginTop: 4 }} checked={agree[i]} onChange={(e) => setAgree(agree.map((a, j) => (j === i ? e.target.checked : a)))} />
              <span>{t}</span>
            </label>
          ))}
          {error ? <p className="err">{error}</p> : null}
          <div className="stepnav"><span /><button className="btn" disabled={!agree.every(Boolean)} onClick={consent}>I agree</button></div>
        </div>
      ) : null}

      {step >= 1 ? (
        <div className="sec">
          <div className="grid2" style={{ alignItems: 'start' }}>
            <div style={{ aspectRatio: '4/3', background: '#1a1916', position: 'relative', overflow: 'hidden' }}>
              <video ref={videoRef} muted playsInline style={{ width: '100%', height: '100%', objectFit: 'cover', transform: 'scaleX(-1)' }} />
              {!stream ? <span style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', color: '#cfcac0', fontSize: 13 }}>{deviceErr || 'Waiting for camera…'}</span> : null}
            </div>
            <div>
              <div className="k"><span>Microphone</span><span>{micOk ? 'Working' : 'Say something'}</span></div>
              <div className="bar" style={{ height: 6 }}><i style={{ height: 6, width: `${level}%`, background: micOk ? 'var(--good)' : 'var(--fg)', transition: 'width .08s' }} /></div>
              <table className="list" style={{ marginTop: 20 }}>
                <tbody>
                  <tr><td>Camera</td><td className={camOk ? 'good' : 'ink'} style={{ textAlign: 'right' }}>{camOk ? 'On' : 'Off'}</td></tr>
                  <tr><td>Microphone</td><td className={micOk ? 'good' : 'dim'} style={{ textAlign: 'right' }}>{micOk ? 'Heard you' : 'Not heard yet'}</td></tr>
                  <tr><td>Browser speech recognition</td><td className={(window as any).webkitSpeechRecognition || (window as any).SpeechRecognition ? 'good' : 'ink'} style={{ textAlign: 'right' }}>{(window as any).webkitSpeechRecognition || (window as any).SpeechRecognition ? 'Available' : 'Use Chrome'}</td></tr>
                </tbody>
              </table>
              {deviceErr ? <button className="btn ghost" style={{ marginTop: 14 }} onClick={() => { setDeviceErr(''); setStream(null); }}>Retry</button> : null}
            </div>
          </div>

          {step === 1 ? (
            <div className="stepnav"><span className="dim" style={{ fontSize: 13 }}>Use headphones if you can, so Ava's voice isn't picked up.</span>
              <button className="btn" disabled={!camOk} onClick={() => setStep(2)}>Looks good</button></div>
          ) : (
            <div style={{ marginTop: 28 }}>
              <div className="k"><span>Read this out loud at your normal pace</span><span>{reading ? `${secs}s` : ''}</span></div>
              <p className="serif" style={{ fontSize: 24, lineHeight: 1.3, marginTop: 10 }}>{READ_ALOUD}</p>
              {error ? <p className="err">{error}</p> : null}
              <div className="stepnav">
                <button className="btn ghost" disabled={reading} onClick={() => { dbSamples.current = []; setSecs(8); setReading(true); }}>{reading ? 'Listening…' : secs === 0 && dbSamples.current.length ? 'Read again' : 'Start reading'}</button>
                <button className="btn" disabled={busy || reading} onClick={launch}>{busy ? 'Starting…' : 'Start interview'}</button>
              </div>
            </div>
          )}
        </div>
      ) : null}
    </main>
  );
}
