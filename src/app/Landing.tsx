import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../authContext';
import { ThemeButton } from './ui';
import './landing.css';

function Clock() {
  const fmt = () => {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone.split('/').pop()!.slice(0, 3).toUpperCase();
    return `${zone}  ${new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}`;
  };
  const [t, setT] = useState(fmt());
  useEffect(() => {
    const id = setInterval(() => setT(fmt()), 30000);
    return () => clearInterval(id);
  }, []);
  return <span className="clock">{t}</span>;
}

export default function Landing() {
  const { user } = useAuth();
  const nav = useNavigate();
  const hero = useRef<HTMLElement>(null);
  const start = user ? '/interview/setup' : '/signup';

  // Hero drifts up and fades as you scroll; edge glint tracks page progress; sections fade up on view.
  useEffect(() => {
    const root = document.documentElement;
    const clamp = (v: number) => Math.min(1, Math.max(0, v));
    const frame = () => {
      const y = scrollY, H = innerHeight, max = Math.max(1, root.scrollHeight - H);
      root.style.setProperty('--p', (y / max).toFixed(4));
      hero.current?.style.setProperty('--hy', `${-y * 0.2}px`);
      hero.current?.style.setProperty('--ho', (1 - clamp(y / (H * 0.8))).toFixed(3));
    };
    const onScroll = () => requestAnimationFrame(frame);
    addEventListener('scroll', onScroll, { passive: true });
    addEventListener('resize', frame);
    frame();
    const io = new IntersectionObserver(
      (es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } }),
      { threshold: 0.15 },
    );
    document.querySelectorAll('.landing .rv').forEach((el, i) => {
      (el as HTMLElement).style.transitionDelay = el.parentElement?.classList.contains('rows') ? `${(i % 3) * 0.08}s` : '0s';
      io.observe(el);
    });
    return () => { removeEventListener('scroll', onScroll); removeEventListener('resize', frame); io.disconnect(); };
  }, []);

  const toHow = (e: React.MouseEvent) => {
    e.preventDefault();
    document.getElementById('how')?.scrollIntoView({ behavior: 'smooth' });
  };

  return (
    <div className="landing">
      <header className="ltop">
        <Link className="logo" to="/">Interv<br />AI</Link>
        <nav>
          <a href="#how" onClick={toHow}>How it works</a>
          <Link to="/guest/setup">Try as guest</Link>
          {user ? <Link to="/dashboard">Dashboard</Link> : <Link to="/login">Log in</Link>}
        </nav>
        <div className="r"><Clock /><Link className="pill" to={start}>Start <i>→</i></Link></div>
      </header>
      <span className="frame l" /><span className="frame r" />

      <main>
        <section className="hero" ref={hero}>
          <h1 className="thin">Practise the<br />interview before<br />it counts</h1>
          <div className="foot">
            <p>Ava asks out loud, listens, follows up,<br />and scores every answer.</p>
            <div className="acts">
              <Link className="solid" to={start}>Start an interview</Link>
              <Link to="/guest/setup">Try as guest</Link>
            </div>
          </div>
        </section>

        <section className="case">
          <div className="rv">
            <small>Live interview</small>
            <h2 className="thin">A real conversation, with a transcript, a timer and a hint when you stall.</h2>
            <div className="acts">
              <Link className="solid" to={start}>Start an interview</Link>
              <Link to="/guest/setup">Try as guest</Link>
            </div>
          </div>
          <div className="card rv" aria-hidden="true">
            <div className="mini">
              <div className="mh"><b>IntervAI</b><span>Technical round · Question 2 of 5</span><span className="mr">● Recording</span></div>
              <div className="mb">
                <span className="ms">Your turn</span>
                <p className="serif">Clients all retry at the top of each minute and you get a spike. What would you change?</p>
                <div className="mt">I'd add a small burst allowance and jitter the reset per key, so clients don't all come back in the same second<i /></div>
              </div>
            </div>
          </div>
        </section>

        <section className="after" id="how">
          <p className="lead thin rv">You answer on camera. <span>Afterwards you get every answer scored, with your own words marked up and what to practise next.</span></p>
          <div className="rows">
            <Link className="rv" to={start}><span className="n">01</span><h3 className="thin">Pick a round</h3><p>Technical, HR, Managerial or Mixed. Add your CV and the job description.</p></Link>
            <Link className="rv" to={start}><span className="n">02</span><h3 className="thin">Talk to Ava</h3><p>Questions out loud, live transcript, follow-ups when you're vague.</p></Link>
            <Link className="rv" to={user ? '/dashboard' : '/signup'}><span className="n">03</span><h3 className="thin">Read the report</h3><p>Content, delivery and presence, and a dashboard that tracks you over time.</p></Link>
          </div>
        </section>
      </main>

      <section className="reveal">
        <div className="row"><h2 className="thin">Your next<br />interview<br />starts here</h2><button className="pill" onClick={() => nav(start)}>Start <i>→</i></button></div>
        <footer><span>© IntervAI</span><ThemeButton className="" /><Link to="/guest/setup">Try as guest</Link><Link to="/login">Log in</Link></footer>
      </section>
    </div>
  );
}
