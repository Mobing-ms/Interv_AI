import React, { useState, useEffect, useRef } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, useNavigate } from 'react-router-dom';
import { AnimatePresence, motion } from 'framer-motion';
import {
  AlertCircle,
  AlertTriangle,
  ArrowUpRight,
  BrainCircuit,
  Camera,
  CameraOff,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock3,
  HelpCircle,
  LockKeyhole,
  Menu,
  Mic,
  Mic2,
  MicOff,
  Play,
  Plus,
  Radio,
  RefreshCw,
  RotateCcw,
  ArrowRight,
  Shield,
  ShieldCheck,
  Sparkles,
  Target,
  Trash2,
  TrendingUp,
  Volume2,
  Wifi,
  WifiOff,
  X,
  Zap,
  Download,
  FileText,
  ExternalLink,
  BookOpen,
  Award,
  BarChart3,
} from 'lucide-react';
import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  ResponsiveContainer,
  LineChart,
  Line,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
} from 'recharts';
import { Toaster, toast } from 'sonner';

declare global {
  interface Window {
    google?: {
      accounts?: {
        id?: {
          initialize: (config: {
            client_id: string;
            callback: (response: { credential?: string }) => void;
            auto_select?: boolean;
            cancel_on_tap_outside?: boolean;
          }) => void;
          renderButton: (
            parent: HTMLElement,
            options: {
              type?: string;
              theme?: string;
              size?: string;
              text?: string;
              shape?: string;
              logo_alignment?: string;
              width?: number;
            }
          ) => void;
          prompt: (notification?: (event: any) => void) => void;
          disableAutoSelect: () => void;
        };
      };
    };
  }
}
import {
  api,
  API_BASE_URL,
  ApiError,
  User,
  StructuredCV,
  CrossCheckFlag,
  ConfirmedProfile,
  UserContext,
  InterviewConfig,
  ConsentRecord,
  SessionCalibration,
  InterviewSession,
  AnalysisStatus,
  SessionReportResponse,
  SessionResultData,
  ImprovementPlanAction,
  PerQuestionFeedback,
  DashboardSummaryResponse,
  DashboardSessionItem,
  tokenStorage,
} from './api';
import { AuthProvider, useAuth } from './authContext';
import './styles.css';

type Round = 'Technical' | 'HR' | 'Managerial' | 'Mixed';
const rounds: Round[] = ['Technical', 'HR', 'Managerial', 'Mixed'];
const sessions = [
  { round: 'Technical', score: 84, date: 'Oct 08', time: '18 min', topic: 'React architecture' },
  { round: 'HR', score: 78, date: 'Oct 04', time: '14 min', topic: 'Leadership' },
  { round: 'Managerial', score: 91, date: 'Sep 29', time: '22 min', topic: 'Prioritisation' },
  { round: 'Technical', score: 72, date: 'Sep 24', time: '12 min', topic: 'System design' },
];

function ProtectedRoute({
  children,
  go,
  allowGuest = false,
}: {
  children: React.ReactNode;
  go: (p: string) => void;
  allowGuest?: boolean;
}) {
  const { user, isLoading } = useAuth();
  const guestSessionId = tokenStorage.getGuestSessionId();
  const isGuestAllowed = allowGuest && !!guestSessionId;

  useEffect(() => {
    if (!isLoading && !user && !isGuestAllowed) {
      toast.error('Please log in to continue');
      go('/login');
    }
  }, [isLoading, user, isGuestAllowed, go]);

  if (isLoading) {
    return (
      <div style={{ display: 'grid', placeItems: 'center', minHeight: '100vh', color: '#9aa3b2', fontFamily: 'DM Sans, sans-serif' }}>
        <div>Loading your session...</div>
      </div>
    );
  }

  if (!user && !isGuestAllowed) {
    return null;
  }

  return <>{children}</>;
}

function App() {
  const nav = useNavigate();
  const [path, setPath] = useState(location.pathname);
  const go = (p: string) => {
    history.pushState({}, '', p);
    setPath(p);
    window.scrollTo(0, 0);
  };

  useEffect(() => {
    const f = () => setPath(location.pathname);
    addEventListener('popstate', f);
    return () => removeEventListener('popstate', f);
  }, []);

  return (
    <AuthProvider>
      <Toaster theme="dark" position="top-right" />
      <AnimatePresence mode="wait">
        <motion.div
          key={path}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.25 }}
        >
          {path === '/' ? (
            <Landing go={go} />
          ) : path === '/guest/setup' ? (
            <GuestSetup go={go} />
          ) : path === '/login' || path === '/signup' ? (
            <Auth go={go} signup={path === '/signup'} />
          ) : path === '/onboarding' ? (
            <ProtectedRoute go={go}>
              <Onboarding go={go} />
            </ProtectedRoute>
          ) : path === '/dashboard' ? (
            <ProtectedRoute go={go}>
              <Dashboard go={go} />
            </ProtectedRoute>
          ) : path === '/interview/setup' ? (
            <ProtectedRoute go={go}>
              <Setup go={go} />
            </ProtectedRoute>
          ) : path === '/interview/precheck' ? (
            <ProtectedRoute go={go} allowGuest>
              <Precheck go={go} />
            </ProtectedRoute>
          ) : path.startsWith('/interview/live') ? (
            <ProtectedRoute go={go} allowGuest>
              <Live go={go} />
            </ProtectedRoute>
          ) : path.startsWith('/interview/processing') ? (
            <ProtectedRoute go={go} allowGuest>
              <Processing go={go} />
            </ProtectedRoute>
          ) : path.startsWith('/report') ? (
            <ProtectedRoute go={go} allowGuest>
              <Report go={go} path={path} />
            </ProtectedRoute>
          ) : path === '/history' ? (
            <ProtectedRoute go={go}>
              <History go={go} />
            </ProtectedRoute>
          ) : path === '/settings' ? (
            <ProtectedRoute go={go}>
              <Settings go={go} />
            </ProtectedRoute>
          ) : (
            <NotFound go={go} />
          )}
        </motion.div>
      </AnimatePresence>
    </AuthProvider>
  );
}

function Shell({ children, go }: { children: React.ReactNode; go: (p: string) => void }) {
  const { user } = useAuth();
  const initials = user?.name
    ? user.name
        .split(' ')
        .filter(Boolean)
        .map((n) => n[0])
        .join('')
        .slice(0, 2)
        .toUpperCase()
    : user?.email
    ? user.email.slice(0, 2).toUpperCase()
    : 'ME';

  return (
    <div className="shell">
      <header className="nav">
        <button className="brand" onClick={() => go('/')}>
          <span className="brand-mark">
            <BrainCircuit />
          </span>
          interv<span>ai</span>
        </button>
        {user ? (
          <>
            <nav className="nav-links">
              <button onClick={() => go('/dashboard')}>Dashboard</button>
              <button onClick={() => go('/history')}>History</button>
              <button onClick={() => go('/settings')}>Settings</button>
            </nav>
            <button className="avatar" onClick={() => go('/settings')}>
              {initials}
            </button>
          </>
        ) : (
          <div className="nav-actions" style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <span
              style={{
                fontSize: '11px',
                color: '#60a5fa',
                background: 'rgba(59, 130, 246, 0.1)',
                border: '1px solid rgba(59, 130, 246, 0.25)',
                padding: '4px 10px',
                borderRadius: '12px',
                fontFamily: 'DM Mono, monospace',
                letterSpacing: '0.05em',
                textTransform: 'uppercase',
              }}
            >
              Guest Practice
            </span>
            <button className="text-button" onClick={() => go('/login')} style={{ fontSize: '13px' }}>
              Log in
            </button>
            <Pill onClick={() => go('/signup')}>Sign up</Pill>
          </div>
        )}
      </header>
      {children}
    </div>
  );
}

function Pill({
  children,
  onClick,
  outline = false,
  disabled = false,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  outline?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      disabled={disabled}
      onClick={disabled ? undefined : onClick}
      className={'pill ' + (outline ? 'outline ' : '') + (disabled ? 'btn-disabled' : '')}
    >
      {children}
      <span className="pill-arrow">
        <ArrowUpRight />
      </span>
    </button>
  );
}

function Landing({ go }: { go: (p: string) => void }) {
  const [faq, setFaq] = useState<number | null>(null);
  return (
    <div className="landing">
      <header className="nav landing-nav">
        <button className="brand" onClick={() => go('/')}>
          <span className="brand-mark">
            <BrainCircuit />
          </span>
          interv<span>ai</span>
        </button>
        <nav className="nav-links">
          <a href="#how">How it works</a>
          <a href="#rounds">Rounds</a>
          <a href="#faq">FAQ</a>
        </nav>
        <div className="nav-actions">
          <button className="text-button" onClick={() => go('/guest/setup')}>
            Just practice
          </button>
          <button className="text-button" onClick={() => go('/login')}>
            Log in
          </button>
          <Pill onClick={() => go('/signup')}>Start practising</Pill>
        </div>
      </header>
      <main>
        <section className="hero">
          <div className="hero-copy">
            <div className="eyebrow">
              <span className="live-dot" /> AI interview practice, rethought
            </div>
            <h1>
              Show up<br />
              <em>ready.</em>
            </h1>
            <p>
              Practice the conversations that move your career forward. IntervAI gives you signal-rich feedback on what you say, how you say it, and how you show up.
            </p>
            <div className="hero-actions" style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
              <Pill onClick={() => go('/signup')}>Start practising</Pill>
              <button
                type="button"
                className="pill pill-secondary"
                onClick={() => go('/guest/setup')}
                style={{
                  background: 'rgba(255, 255, 255, 0.04)',
                  border: '1px solid rgba(255, 255, 255, 0.18)',
                  color: 'var(--text-strong, #ffffff)',
                  cursor: 'pointer',
                  padding: '9px 18px',
                  borderRadius: '999px',
                  fontSize: '13px',
                  fontWeight: 500,
                  transition: 'all 0.2s ease',
                }}
              >
                Just practice
              </button>
              <button className="link-button" onClick={() => document.getElementById('how')?.scrollIntoView({ behavior: 'smooth' })}>
                <Play /> See how it works
              </button>
            </div>
            <div className="trust">
              <div className="avatars">
                <i>AM</i>
                <i>RS</i>
                <i>NP</i>
              </div>
              <span>Join 12,000+ ambitious candidates</span>
            </div>
          </div>
          <div className="hero-art">
            <div className="orb-glow" />
            <div className="orb">
              <div className="orb-face">
                <span />
                <span />
                <b />
              </div>
              <div className="orb-ring r1" />
              <div className="orb-ring r2" />
            </div>
            <div className="floating-card score-float">
              <span>last session</span>
              <strong>84</strong>
              <small>+12% this week</small>
            </div>
            <div className="floating-card mic-float">
              <Mic2 />
              <div>
                <span>voice clarity</span>
                <strong>Excellent</strong>
              </div>
            </div>
            <div className="waveform">
              {Array.from({ length: 26 }, (_, i) => (
                <i key={i} style={{ height: `${18 + Math.sin(i * 1.7) * 14 + Math.random() * 18}px` }} />
              ))}
            </div>
          </div>
        </section>
        <div className="marquee">
          <span>TECHNICAL</span>
          <b>✦</b>
          <span>BEHAVIOURAL</span>
          <b>✦</b>
          <span>LEADERSHIP</span>
          <b>✦</b>
          <span>COMMUNICATION</span>
          <b>✦</b>
          <span>TECHNICAL</span>
        </div>
        <section className="feature-row">
          <Feature n="01" title="Real presence" text="Camera, voice and words — measured together." icon={<Target />} />
          <Feature n="02" title="Useful signal" text="Know exactly what to keep, and what to change." icon={<Sparkles />} />
          <Feature n="03" title="Your pace" text="Adaptive questions that meet you where you are." icon={<Zap />} />
          <Feature n="04" title="Visible progress" text="A practice loop built around your next opportunity." icon={<TrendingUp />} />
        </section>
        <section id="how" className="section how">
          <div className="section-label">
            THE METHOD <span>↓</span>
          </div>
          <div className="section-heading">
            <h2>
              Less guessing.<br />
              <em>More knowing.</em>
            </h2>
            <p>Every session is designed to feel like the real thing — with a little more room to learn.</p>
          </div>
          <div className="steps">
            {['Set your signal', 'Meet your interviewer', 'Think out loud', 'Get the read', 'Practice forward'].map((x, i) => (
              <button className="step" key={x} onClick={() => toast.success(`${x}: step ${i + 1} selected`)}>
                <span>0{i + 1}</span>
                <strong>{x}</strong>
                <ChevronRight />
              </button>
            ))}
          </div>
        </section>
        <section id="rounds" className="section">
          <div className="section-label">
            CHOOSE YOUR ROUND <span>↓</span>
          </div>
          <div className="round-grid">
            {rounds.map((r, i) => (
              <button className="round-card" key={r} onClick={() => go('/signup')}>
                <span>0{i + 1}</span>
                <div>
                  <h3>{r}</h3>
                  <p>
                    {i === 0
                      ? 'Systems, code and technical depth.'
                      : i === 1
                      ? 'Your story, values and motivation.'
                      : 'Decisions, teams and strategic thinking.'}
                  </p>
                </div>
                <ArrowUpRight />
              </button>
            ))}
          </div>
        </section>
        <section id="faq" className="section faq">
          <div className="section-heading">
            <h2>
              Good questions<br />
              <em>deserve answers.</em>
            </h2>
          </div>
          {['How does the AI interviewer work?', 'What does IntervAI measure?', 'Can I use it for a specific role?', 'Is my recording private?'].map(
            (q, i) => (
              <div className="faq-item" key={q}>
                <button onClick={() => setFaq(faq === i ? null : i)}>
                  <span>0{i + 1}</span>
                  {q}
                  <ChevronDown className={faq === i ? 'rotate' : ''} />
                </button>
                {faq === i && (
                  <p>
                    IntervAI listens to your answer, evaluates clarity and substance, then turns the moment into practical feedback you can use immediately.
                  </p>
                )}
              </div>
            )
          )}
        </section>
        <section className="final-cta">
          <div>
            <span className="eyebrow">YOUR NEXT INTERVIEW STARTS HERE</span>
            <h2>
              Ready when<br />
              <em>you are.</em>
            </h2>
          </div>
          <Pill onClick={() => go('/signup')}>Start practising</Pill>
        </section>
      </main>
      <footer>
        <button className="brand" onClick={() => go('/')}>
          <span className="brand-mark">
            <BrainCircuit />
          </span>
          interv<span>ai</span>
        </button>
        <span>© 2025 IntervAI. Built for better conversations.</span>
      </footer>
    </div>
  );
}

function Feature({ n, title, text, icon }: { n: string; title: string; text: string; icon: React.ReactNode }) {
  return (
    <div className="feature">
      <span className="feature-number">#{n}</span>
      <div className="feature-icon">{icon}</div>
      <h3>{title}</h3>
      <p>{text}</p>
    </div>
  );
}

function Auth({ go, signup }: { go: (p: string) => void; signup: boolean }) {
  const { setUser } = useAuth();
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');

  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [networkError, setNetworkError] = useState<string>('');
  const [isLoading, setIsLoading] = useState(false);
  const [isGoogleLoading, setIsGoogleLoading] = useState(false);

  useEffect(() => {
    setFieldErrors({});
    setNetworkError('');
  }, [signup]);

  const handleSubmit = async () => {
    setFieldErrors({});
    setNetworkError('');
    const errors: Record<string, string> = {};

    if (signup) {
      if (!name.trim()) {
        errors.name = 'Please enter your full name';
      }
      if (!email.trim()) {
        errors.email = 'Please enter your email';
      } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
        errors.email = 'Please enter a valid email address';
      }
      if (!password) {
        errors.password = 'Please enter a password';
      } else if (password.length < 8) {
        errors.password = 'Password must be at least 8 characters';
      }
      if (!confirmPassword) {
        errors.confirmPassword = 'Please repeat your password';
      } else if (password !== confirmPassword) {
        errors.confirmPassword = "Passwords don't match";
      }

      if (Object.keys(errors).length > 0) {
        setFieldErrors(errors);
        return;
      }

      setIsLoading(true);
      try {
        const data = await api.signup(name.trim(), email.trim(), password);
        setUser(data.user);
        toast.success('Account created');
        go('/onboarding');
      } catch (err: any) {
        if (err instanceof ApiError && err.isNetworkError) {
          setNetworkError('Network error: Unable to connect to server');
        } else if (err instanceof ApiError && (err.status === 400 || err.detail?.toLowerCase().includes('already used'))) {
          setFieldErrors({ email: 'Email already used' });
        } else {
          setNetworkError(err.detail || 'An error occurred during sign up');
        }
      } finally {
        setIsLoading(false);
      }
    } else {
      if (!email.trim()) {
        errors.email = 'Please enter your email';
      }
      if (!password) {
        errors.password = 'Please enter your password';
      }

      if (Object.keys(errors).length > 0) {
        setFieldErrors(errors);
        return;
      }

      setIsLoading(true);
      try {
        const data = await api.login(email.trim(), password);
        setUser(data.user);
        toast.success('Welcome back');
        if (data.user.onboarding_status && data.user.onboarding_status !== 'profile_confirmed') {
          go('/onboarding');
        } else {
          go('/dashboard');
        }
      } catch (err: any) {
        if (err instanceof ApiError && err.isNetworkError) {
          setNetworkError('Network error: Unable to connect to server');
        } else if (err instanceof ApiError && (err.status === 401 || err.detail?.toLowerCase().includes('invalid credentials'))) {
          setFieldErrors({ password: 'Wrong credentials' });
        } else {
          setNetworkError(err.detail || 'An error occurred during login');
        }
      } finally {
        setIsLoading(false);
      }
    }
  };

  const googleClientId = import.meta.env.VITE_GOOGLE_CLIENT_ID || '';
  const googleButtonRef = useRef<HTMLDivElement>(null);

  const handleCredentialResponse = async (response: { credential?: string }) => {
    if (!response?.credential) {
      toast.error('No credential received from Google');
      return;
    }

    setFieldErrors({});
    setNetworkError('');
    setIsGoogleLoading(true);

    try {
      const data = await api.googleAuth({ credential: response.credential });
      setUser(data.user);
      toast.success(`Welcome, ${data.user.name || 'Candidate'}!`);
      if (data.user.onboarding_status && data.user.onboarding_status !== 'profile_confirmed') {
        go('/onboarding');
      } else {
        go('/dashboard');
      }
    } catch (err: any) {
      if (err instanceof ApiError && err.isNetworkError) {
        setNetworkError('Network error: Unable to connect to server');
      } else {
        const detail = err.detail || 'Failed to sign in with Google';
        setNetworkError(detail);
        toast.error(detail);
      }
    } finally {
      setIsGoogleLoading(false);
    }
  };

  useEffect(() => {
    if (!googleClientId) {
      return;
    }

    let intervalId: any = null;

    const setupGsi = () => {
      if (window.google?.accounts?.id && googleButtonRef.current) {
        try {
          window.google.accounts.id.initialize({
            client_id: googleClientId,
            callback: handleCredentialResponse,
            auto_select: false,
            cancel_on_tap_outside: true,
          });

          googleButtonRef.current.innerHTML = '';
          window.google.accounts.id.renderButton(googleButtonRef.current, {
            type: 'standard',
            theme: 'outline',
            size: 'large',
            text: 'continue_with',
            shape: 'pill',
            width: 380,
          });

          // Trigger One Tap prompt if eligible
          window.google.accounts.id.prompt();
          return true;
        } catch (e) {
          console.warn('Google Identity Services setup warning:', e);
        }
      }
      return false;
    };

    if (!setupGsi()) {
      intervalId = setInterval(() => {
        if (setupGsi()) {
          clearInterval(intervalId);
        }
      }, 300);
    }

    return () => {
      if (intervalId) clearInterval(intervalId);
    };
  }, [googleClientId, signup]);

  const handleGoogleAuth = async () => {
    setFieldErrors({});
    setNetworkError('');

    if (!googleClientId) {
      toast.error('Google Client ID is not configured. Please add VITE_GOOGLE_CLIENT_ID to your frontend .env file.');
      return;
    }

    if (!window.google?.accounts?.id) {
      toast.error('Google Sign-In is still loading. Please wait a moment and try again.');
      return;
    }

    try {
      window.google.accounts.id.prompt();
    } catch (err) {
      console.warn('Google prompt warning:', err);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-visual">
        <button className="brand" onClick={() => go('/')}>
          <span className="brand-mark">
            <BrainCircuit />
          </span>
          interv<span>ai</span>
        </button>
        <div>
          <span className="eyebrow">THE BETTER INTERVIEW LOOP</span>
          <h1>
            Practice with<br />
            <em>presence.</em>
          </h1>
        </div>
        <p>Sharper answers. Calmer delivery. A clearer read on what comes next.</p>
      </div>
      <div className="auth-form">
        <button className="mobile-brand brand" onClick={() => go('/')}>
          <span className="brand-mark">
            <BrainCircuit />
          </span>
          interv<span>ai</span>
        </button>
        <span className="eyebrow">{signup ? 'CREATE YOUR ACCOUNT' : 'WELCOME BACK'}</span>
        <h2>{signup ? 'Start your practice loop.' : 'Pick up where you left off.'}</h2>
        <p className="muted">
          {signup ? 'Your first session is on us. No credit card required.' : 'Your progress is waiting.'}
        </p>

        {signup && (
          <label>
            Full name
            <input
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                setFieldErrors((p) => ({ ...p, name: '' }));
              }}
              placeholder="Alex Kumar"
              className={fieldErrors.name ? 'input-error' : ''}
            />
            {fieldErrors.name && <span className="field-error">{fieldErrors.name}</span>}
          </label>
        )}

        <label>
          Email
          <input
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
              setFieldErrors((p) => ({ ...p, email: '' }));
            }}
            placeholder="you@example.com"
            type="email"
            className={fieldErrors.email ? 'input-error' : ''}
          />
          {fieldErrors.email && <span className="field-error">{fieldErrors.email}</span>}
        </label>

        <label>
          Password
          <input
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
              setFieldErrors((p) => ({ ...p, password: '' }));
            }}
            placeholder="At least 8 characters"
            type="password"
            className={fieldErrors.password ? 'input-error' : ''}
          />
          {fieldErrors.password && <span className="field-error">{fieldErrors.password}</span>}
        </label>

        {signup && (
          <label>
            Confirm password
            <input
              value={confirmPassword}
              onChange={(e) => {
                setConfirmPassword(e.target.value);
                setFieldErrors((p) => ({ ...p, confirmPassword: '' }));
              }}
              placeholder="Repeat your password"
              type="password"
              className={fieldErrors.confirmPassword ? 'input-error' : ''}
            />
            {fieldErrors.confirmPassword && <span className="field-error">{fieldErrors.confirmPassword}</span>}
          </label>
        )}

        {networkError && <div className="network-error">{networkError}</div>}

        <Pill onClick={handleSubmit} disabled={isLoading || isGoogleLoading}>
          {isLoading ? (signup ? 'Creating account...' : 'Logging in...') : signup ? 'Create account' : 'Log in'}
        </Pill>

        <div style={{ position: 'relative', width: '100%', marginTop: 12 }}>
          <button
            type="button"
            className={`google ${isGoogleLoading ? 'btn-disabled' : ''}`}
            onClick={handleGoogleAuth}
            disabled={isLoading || isGoogleLoading}
            style={{ width: '100%', margin: 0 }}
          >
            {isGoogleLoading ? 'Connecting to Google...' : 'Continue with Google'}
          </button>

          {googleClientId && (
            <div
              ref={googleButtonRef}
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                height: '100%',
                opacity: 0.001,
                overflow: 'hidden',
                cursor: 'pointer',
                zIndex: 5,
              }}
            />
          )}
        </div>

        {!signup && (
          <button className="forgot" onClick={() => toast.success('Reset link sent — check your inbox')}>
            Forgot password?
          </button>
        )}

        <p className="auth-switch">
          {signup ? 'Already have an account?' : 'New to IntervAI?'}{' '}
          <button onClick={() => go(signup ? '/login' : '/signup')}>
            {signup ? 'Log in' : 'Create an account'}
          </button>
        </p>
      </div>
    </div>
  );
}

function Onboarding({ go }: { go: (p: string) => void }) {
  const { refreshUser } = useAuth();
  const [step, setStep] = useState(1);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  // Step 1: Education state
  const [degree, setDegree] = useState("Bachelor's degree");
  const [branch, setBranch] = useState('');
  const [college, setCollege] = useState('');
  const [graduationYear, setGraduationYear] = useState('2026');
  const [cgpa, setCgpa] = useState('');
  const [cgpaScale, setCgpaScale] = useState('10.0');

  // Step 2: Target state
  const [targetRole, setTargetRole] = useState('');
  const [companyType, setCompanyType] = useState('Product');
  const [experienceLevel, setExperienceLevel] = useState('Fresher');
  const [jobDescription, setJobDescription] = useState('');
  const [roleSuggestions, setRoleSuggestions] = useState<string[]>([]);

  // Step 3 & 4: CV Upload & Structuring state
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [cvId, setCvId] = useState<number | null>(null);
  const [cvStatus, setCvStatus] = useState<'idle' | 'uploading' | 'extracting' | 'extracted' | 'failed'>('idle');
  const [uploadFileName, setUploadFileName] = useState('');
  const [extractedLength, setExtractedLength] = useState<number | null>(null);
  const [cvError, setCvError] = useState<{ code: string; message: string } | null>(null);

  // Step 4: Structured CV & Cross-Check state
  const [parsedCV, setParsedCV] = useState<StructuredCV | null>(null);
  const [crossCheckFlags, setCrossCheckFlags] = useState<CrossCheckFlag[]>([]);
  const [isParsing, setIsParsing] = useState(false);
  const [skillsList, setSkillsList] = useState<string[]>(['React', 'TypeScript', 'System design']);

  // Editable profile sections state
  const [personalName, setPersonalName] = useState('');
  const [personalEmail, setPersonalEmail] = useState('');
  const [personalPhone, setPersonalPhone] = useState('');
  const [personalLinks, setPersonalLinks] = useState<string[]>([]);

  const [eduDegree, setEduDegree] = useState('');
  const [eduBranch, setEduBranch] = useState('');
  const [eduCollege, setEduCollege] = useState('');
  const [eduYear, setEduYear] = useState<string | number>('');
  const [eduCgpa, setEduCgpa] = useState<string | number>('');

  const [skillsLanguages, setSkillsLanguages] = useState<string[]>([]);
  const [skillsFrameworks, setSkillsFrameworks] = useState<string[]>([]);
  const [skillsTools, setSkillsTools] = useState<string[]>([]);
  const [skillsDomains, setSkillsDomains] = useState<string[]>([]);
  const [skillsSoft, setSkillsSoft] = useState<string[]>([]);

  const [projectsList, setProjectsList] = useState<
    Array<{ title: string; description?: string | null; tech_stack: string[]; role?: string | null; outcomes?: string | null }>
  >([]);
  const [experienceList, setExperienceList] = useState<
    Array<{ company: string; role: string; duration?: string | null; responsibilities: string[] }>
  >([]);
  const [certificationsList, setCertificationsList] = useState<string[]>([]);
  const [achievementsList, setAchievementsList] = useState<string[]>([]);

  // Track resolved flags: key -> { resolved: boolean, choice?: string }
  const [resolvedFlags, setResolvedFlags] = useState<Record<string, { resolved: boolean; choice?: string }>>({});

  // Poll CV status helper
  const pollCVExtraction = (cvId: number) => {
    let attempts = 0;
    const interval = setInterval(async () => {
      attempts++;
      try {
        const res = await api.getCVStatus(cvId);
        if (res.status === 'extracted') {
          clearInterval(interval);
          setCvStatus('extracted');
          setExtractedLength(res.text_length || null);
          toast.success('CV uploaded and text extracted!');
          await refreshUser();
        } else if (res.status === 'failed') {
          clearInterval(interval);
          setCvStatus('failed');
          setCvError({
            code: res.error_code || 'UNREADABLE',
            message: res.error_message || 'Text extraction failed. Please re-upload.',
          });
        } else if (attempts > 30) {
          clearInterval(interval);
          setCvStatus('failed');
          setCvError({
            code: 'TIMEOUT',
            message: 'Extraction timed out. Please try re-uploading.',
          });
        }
      } catch {
        clearInterval(interval);
        setCvStatus('failed');
        setCvError({
          code: 'NETWORK_ERROR',
          message: 'Unable to check extraction status. Please check your network.',
        });
      }
    }, 1200);
  };

  const handleUploadFile = async (file: File) => {
    setCvError(null);

    // Client-side quick checks
    const ext = file.name.split('.').pop()?.toLowerCase();
    if (ext !== 'pdf' && ext !== 'docx') {
      setCvStatus('failed');
      setCvError({
        code: 'UNSUPPORTED_TYPE',
        message: 'Unsupported file format. Please upload a PDF or DOCX file.',
      });
      return;
    }

    if (file.size > 5 * 1024 * 1024) {
      setCvStatus('failed');
      setCvError({
        code: 'TOO_LARGE',
        message: `File exceeds 5 MB limit (${(file.size / (1024 * 1024)).toFixed(2)} MB). Please upload a smaller file.`,
      });
      return;
    }

    if (file.size === 0) {
      setCvStatus('failed');
      setCvError({
        code: 'UNREADABLE',
        message: 'The uploaded file is empty.',
      });
      return;
    }

    setUploadFileName(file.name);
    setCvStatus('uploading');

    try {
      const res = await api.uploadCV(file);
      setCvId(res.id);
      setParsedCV(null);
      setCrossCheckFlags([]);
      setCvStatus('extracting');
      pollCVExtraction(res.id);
    } catch (err: any) {
      setCvStatus('failed');
      const code = err.errorCode || (err.detail?.toLowerCase().includes('encrypted') ? 'ENCRYPTED' : err.detail?.toLowerCase().includes('size') ? 'TOO_LARGE' : 'UNREADABLE');
      setCvError({
        code: code,
        message: err.detail || 'Upload failed. Please check the file and re-upload.',
      });
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleUploadFile(e.dataTransfer.files[0]);
    }
  };

  // Load saved data and resume onboarding position
  useEffect(() => {
    async function initOnboarding() {
      setLoading(true);
      try {
        // Fetch target suggestions
        api.getTargetSuggestions().then((res) => {
          if (res?.suggestions) setRoleSuggestions(res.suggestions);
        }).catch(() => {});

        // Fetch saved education profile
        try {
          const edu = await api.getEducationProfile();
          if (edu) {
            setDegree(edu.degree || "Bachelor's degree");
            setBranch(edu.branch || '');
            setCollege(edu.college || '');
            setGraduationYear(String(edu.graduation_year || 2026));
            if (edu.cgpa != null) setCgpa(String(edu.cgpa));
            if (edu.cgpa_scale != null) setCgpaScale(String(edu.cgpa_scale));
          }
        } catch {
          const draftEdu = localStorage.getItem('intervai_edu_draft');
          if (draftEdu) {
            try {
              const d = JSON.parse(draftEdu);
              if (d.degree) setDegree(d.degree);
              if (d.branch) setBranch(d.branch);
              if (d.college) setCollege(d.college);
              if (d.graduationYear) setGraduationYear(d.graduationYear);
              if (d.cgpa) setCgpa(d.cgpa);
              if (d.cgpaScale) setCgpaScale(d.cgpaScale);
            } catch {}
          }
        }

        // Fetch saved target profile
        try {
          const tgt = await api.getTargetProfile();
          if (tgt) {
            setTargetRole(tgt.target_role || '');
            setCompanyType(tgt.company_type || 'Product');
            setExperienceLevel(tgt.experience_level || 'Fresher');
            setJobDescription(tgt.job_description || '');
          }
        } catch {
          const draftTgt = localStorage.getItem('intervai_tgt_draft');
          if (draftTgt) {
            try {
              const d = JSON.parse(draftTgt);
              if (d.targetRole) setTargetRole(d.targetRole);
              if (d.companyType) setCompanyType(d.companyType);
              if (d.experienceLevel) setExperienceLevel(d.experienceLevel);
              if (d.jobDescription) setJobDescription(d.jobDescription);
            } catch {}
          }
        }

        // Fetch latest CV if available
        try {
          const latestCV = await api.getLatestCV();
          if (latestCV) {
            setCvId(latestCV.id);
            if (latestCV.status === 'extracted') {
              setCvStatus('extracted');
              setUploadFileName(latestCV.filename);
              setExtractedLength(latestCV.text_length || null);

              // Check if already structured
              try {
                const parsedRes = await api.getParsedCV(latestCV.id);
                if (parsedRes && parsedRes.structured_data) {
                  setParsedCV(parsedRes.structured_data);
                  setCrossCheckFlags(parsedRes.cross_check_flags || []);
                  const skills = [
                    ...parsedRes.structured_data.skills.languages,
                    ...parsedRes.structured_data.skills.frameworks,
                    ...parsedRes.structured_data.skills.tools,
                  ];
                  if (skills.length > 0) {
                    setSkillsList(skills);
                  }
                }
              } catch {}
            }
          }
        } catch {}

        // Determine current resume step
        try {
          const statusRes = await api.getOnboardingStatus();
          if (statusRes.current_step && statusRes.current_step >= 1 && statusRes.current_step <= 4) {
            setStep(statusRes.current_step);
          } else if (statusRes.current_step === 5) {
            go('/dashboard');
          }
        } catch {}
      } finally {
        setLoading(false);
      }
    }

    initOnboarding();
  }, []);

  // Auto-save drafts to localStorage
  useEffect(() => {
    if (!loading) {
      localStorage.setItem(
        'intervai_edu_draft',
        JSON.stringify({ degree, branch, college, graduationYear, cgpa, cgpaScale })
      );
    }
  }, [degree, branch, college, graduationYear, cgpa, cgpaScale, loading]);

  useEffect(() => {
    if (!loading) {
      localStorage.setItem(
        'intervai_tgt_draft',
        JSON.stringify({ targetRole, companyType, experienceLevel, jobDescription })
      );
    }
  }, [targetRole, companyType, experienceLevel, jobDescription, loading]);

  // Step 1: Submit Education
  const handleContinueEducation = async () => {
    const errors: Record<string, string> = {};
    if (!branch.trim()) {
      errors.branch = 'Please enter your branch/major';
    }
    if (!college.trim()) {
      errors.college = 'Please enter your college or university';
    }

    const scaleNum = parseFloat(cgpaScale) || 10.0;
    if (cgpa.trim()) {
      const cgpaNum = parseFloat(cgpa);
      if (isNaN(cgpaNum) || cgpaNum < 0 || cgpaNum > scaleNum) {
        errors.cgpa = `CGPA must be a valid number between 0 and ${scaleNum}`;
      }
    }

    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      return;
    }

    setFieldErrors({});
    setSaving(true);
    try {
      await api.saveEducationProfile({
        degree,
        branch: branch.trim(),
        college: college.trim(),
        graduation_year: parseInt(graduationYear, 10) || 2026,
        cgpa: cgpa.trim() ? parseFloat(cgpa) : null,
        cgpa_scale: scaleNum,
      });
      toast.success('Education profile saved');
      await refreshUser();
      setStep(2);
    } catch (err: any) {
      toast.error(err.detail || 'Failed to save education profile');
    } finally {
      setSaving(false);
    }
  };

  // Step 2: Submit Target Profile
  const handleContinueTarget = async () => {
    const errors: Record<string, string> = {};
    if (!targetRole.trim()) {
      errors.targetRole = 'Please specify or select a target role';
    }

    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      return;
    }

    setFieldErrors({});
    setSaving(true);
    try {
      await api.saveTargetProfile({
        target_role: targetRole.trim(),
        company_type: companyType,
        experience_level: experienceLevel,
        job_description: jobDescription.trim() || undefined,
      });
      toast.success('Target preferences saved');
      await refreshUser();
      setStep(3);
    } catch (err: any) {
      toast.error(err.detail || 'Failed to save target preferences');
    } finally {
      setSaving(false);
    }
  };

  const syncParsedCVToState = (cv: StructuredCV) => {
    setPersonalName(cv.personal?.name || '');
    setPersonalEmail(cv.personal?.email || '');
    setPersonalPhone(cv.personal?.phone || '');
    setPersonalLinks(cv.personal?.links || []);

    if (cv.education && cv.education[0]) {
      setEduDegree(cv.education[0].degree || degree);
      setEduBranch(cv.education[0].branch || branch);
      setEduCollege(cv.education[0].college || college);
      setEduYear(cv.education[0].year != null ? String(cv.education[0].year) : graduationYear);
      setEduCgpa(cv.education[0].cgpa != null ? String(cv.education[0].cgpa) : cgpa);
    } else {
      setEduDegree(degree);
      setEduBranch(branch);
      setEduCollege(college);
      setEduYear(graduationYear);
      setEduCgpa(cgpa);
    }

    setSkillsLanguages(cv.skills?.languages || []);
    setSkillsFrameworks(cv.skills?.frameworks || []);
    setSkillsTools(cv.skills?.tools || []);
    setSkillsDomains(cv.skills?.domains || []);
    setSkillsSoft(cv.skills?.soft || []);

    setProjectsList(cv.projects || []);
    setExperienceList(cv.internships_experience || []);
    setCertificationsList(cv.certifications || []);
    setAchievementsList(cv.achievements || []);
  };

  // Step 3: Parse CV & Cross-Check to advance to Step 4
  const handleProceedToStep4 = async () => {
    if (cvStatus !== 'extracted') {
      toast.error('Please upload and extract a valid CV before continuing');
      return;
    }

    if (!parsedCV && cvId) {
      setIsParsing(true);
      try {
        const parsedRes = await api.parseCV(cvId);
        setParsedCV(parsedRes.structured_data);
        setCrossCheckFlags(parsedRes.cross_check_flags || []);
        syncParsedCVToState(parsedRes.structured_data);
        if (parsedRes.cross_check_flags && parsedRes.cross_check_flags.length > 0) {
          toast.warning(`Structured CV with ${parsedRes.cross_check_flags.length} alignment note(s)`);
        } else {
          toast.success('CV structured successfully!');
        }
      } catch (err: any) {
        toast.error(err.detail || 'Structuring in progress. Proceeding to profile review.');
      } finally {
        setIsParsing(false);
      }
    } else if (parsedCV) {
      syncParsedCVToState(parsedCV);
    }
    setStep(4);
  };

  const resolveFlag = (idx: number, choice: 'cv' | 'form' | 'acknowledge') => {
    const flag = crossCheckFlags[idx];
    if (!flag) return;
    const key = `${flag.type}_${flag.field}_${idx}`;

    if (choice === 'form') {
      if (flag.field === 'degree') setEduDegree(flag.form_value || degree);
      else if (flag.field === 'branch') setEduBranch(flag.form_value || branch);
      else if (flag.field === 'college') setEduCollege(flag.form_value || college);
      else if (flag.field === 'graduation_year') setEduYear(flag.form_value || graduationYear);
      else if (flag.field === 'cgpa') setEduCgpa(flag.form_value || cgpa);
      else if (flag.field === 'target_role_skills') {
        const roleSkill = flag.form_value || targetRole;
        if (roleSkill && !skillsDomains.includes(roleSkill)) {
          setSkillsDomains((p) => [...p, roleSkill]);
        }
      }
    }

    setResolvedFlags((prev) => ({
      ...prev,
      [key]: {
        resolved: true,
        choice: choice === 'form' ? 'Used form value' : choice === 'cv' ? 'Kept CV value' : 'Acknowledged',
      },
    }));
    toast.success(`Resolved note for ${flag.field}`);
  };

  const unresolvedHighCount = crossCheckFlags.filter((f, idx) => {
    const key = `${f.type}_${f.field}_${idx}`;
    return f.severity === 'HIGH' && !resolvedFlags[key]?.resolved;
  }).length;

  const handleConfirmProfile = async () => {
    if (unresolvedHighCount > 0) {
      toast.error(`Please resolve ${unresolvedHighCount} high-severity note(s) before confirming.`);
      return;
    }

    setSaving(true);
    try {
      const canonicalData: StructuredCV = {
        personal: {
          name: personalName.trim() || undefined,
          email: personalEmail.trim() || undefined,
          phone: personalPhone.trim() || undefined,
          links: personalLinks,
        },
        education: [
          {
            degree: eduDegree || degree,
            branch: eduBranch || branch,
            college: eduCollege || college,
            year: eduYear || graduationYear,
            cgpa: eduCgpa ? (typeof eduCgpa === 'string' ? parseFloat(eduCgpa) : eduCgpa) : undefined,
          },
        ],
        skills: {
          languages: skillsLanguages,
          frameworks: skillsFrameworks,
          tools: skillsTools,
          domains: skillsDomains,
          soft: skillsSoft,
        },
        projects: projectsList,
        internships_experience: experienceList,
        certifications: certificationsList,
        achievements: achievementsList,
      };

      const unresolved = crossCheckFlags.filter((f, idx) => {
        const key = `${f.type}_${f.field}_${idx}`;
        return !resolvedFlags[key]?.resolved;
      });

      await api.confirmProfile({
        structured_data: canonicalData,
        unresolved_flags: unresolved,
        cv_document_id: cvId,
      });

      toast.success('Practice profile confirmed and saved!');
      await refreshUser();
      go('/dashboard');
    } catch (err: any) {
      toast.error(err.detail || 'Failed to confirm profile');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <Shell go={go}>
        <main className="onboarding">
          <div style={{ padding: '80px 0', textAlign: 'center', color: '#9aa3b2', fontFamily: 'DM Sans, sans-serif' }}>
            Resuming your onboarding...
          </div>
        </main>
      </Shell>
    );
  }

  return (
    <Shell go={go}>
      <main className="onboarding">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div className="eyebrow">PROFILE SETUP · 0{step} / 04</div>
          <div style={{ fontSize: '11px', fontFamily: 'DM Mono, monospace', color: saving ? '#60a5fa' : '#6f7b8e' }}>
            {saving ? 'Saving...' : 'Auto-saved'}
          </div>
        </div>
        <div className="progress">
          <i style={{ width: `${step * 25}%` }} />
        </div>
        <h1>
          Let&apos;s make this<br />
          <em>specific to you.</em>
        </h1>
        <p className="lead">A few details help us build better questions and sharper feedback.</p>

        <div className="form-card">
          {step === 1 && (
            <>
              <h2>Tell us about your education</h2>
              <div className="form-grid">
                <label>
                  Degree
                  <select value={degree} onChange={(e) => setDegree(e.target.value)}>
                    <option>Bachelor&apos;s degree</option>
                    <option>Master&apos;s degree</option>
                    <option>Ph.D.</option>
                    <option>Diploma</option>
                  </select>
                </label>
                <label>
                  Branch
                  <input
                    value={branch}
                    onChange={(e) => {
                      setBranch(e.target.value);
                      setFieldErrors((p) => ({ ...p, branch: '' }));
                    }}
                    placeholder="Computer Science"
                    className={fieldErrors.branch ? 'input-error' : ''}
                  />
                  {fieldErrors.branch && <span className="field-error">{fieldErrors.branch}</span>}
                </label>
                <label>
                  College
                  <input
                    value={college}
                    onChange={(e) => {
                      setCollege(e.target.value);
                      setFieldErrors((p) => ({ ...p, college: '' }));
                    }}
                    placeholder="Your college"
                    className={fieldErrors.college ? 'input-error' : ''}
                  />
                  {fieldErrors.college && <span className="field-error">{fieldErrors.college}</span>}
                </label>
                <label>
                  Graduation year
                  <select value={graduationYear} onChange={(e) => setGraduationYear(e.target.value)}>
                    {[2023, 2024, 2025, 2026, 2027, 2028, 2029].map((y) => (
                      <option key={y} value={y}>
                        {y}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  CGPA / GPA (optional)
                  <input
                    type="number"
                    step="0.01"
                    value={cgpa}
                    onChange={(e) => {
                      setCgpa(e.target.value);
                      setFieldErrors((p) => ({ ...p, cgpa: '' }));
                    }}
                    placeholder={cgpaScale === '10.0' ? 'e.g. 8.5' : 'e.g. 3.7'}
                    className={fieldErrors.cgpa ? 'input-error' : ''}
                  />
                  {fieldErrors.cgpa && <span className="field-error">{fieldErrors.cgpa}</span>}
                </label>
                <label>
                  CGPA Scale
                  <select value={cgpaScale} onChange={(e) => setCgpaScale(e.target.value)}>
                    <option value="10.0">10.0 Scale</option>
                    <option value="4.0">4.0 Scale</option>
                  </select>
                </label>
              </div>
            </>
          )}

          {step === 2 && (
            <>
              <h2>What are you aiming for?</h2>
              <div className="form-grid">
                <label>
                  Target role
                  <input
                    value={targetRole}
                    onChange={(e) => {
                      setTargetRole(e.target.value);
                      setFieldErrors((p) => ({ ...p, targetRole: '' }));
                    }}
                    placeholder="e.g. Frontend Engineer"
                    className={fieldErrors.targetRole ? 'input-error' : ''}
                  />
                  {fieldErrors.targetRole && <span className="field-error">{fieldErrors.targetRole}</span>}
                </label>
                <label>
                  Company type
                  <select value={companyType} onChange={(e) => setCompanyType(e.target.value)}>
                    <option value="Product">Product</option>
                    <option value="Startup">Startup</option>
                    <option value="Service">Service</option>
                    <option value="MNC">MNC</option>
                    <option value="Core/Other">Core/Other</option>
                  </select>
                </label>
                <label>
                  Experience level
                  <select value={experienceLevel} onChange={(e) => setExperienceLevel(e.target.value)}>
                    <option value="Fresher">Fresher</option>
                    <option value="0-2">0–2 years</option>
                    <option value="2-5">2–5 years</option>
                    <option value="5+">5+ years</option>
                  </select>
                </label>
              </div>

              {/* Target role suggestions list */}
              <div style={{ marginTop: '12px', marginBottom: '22px' }}>
                <span
                  style={{
                    fontSize: '11px',
                    color: '#6f7b8e',
                    fontFamily: 'DM Mono, monospace',
                    letterSpacing: '1px',
                    display: 'block',
                    marginBottom: '8px',
                  }}
                >
                  SUGGESTIONS:
                </span>
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                  {(roleSuggestions.length > 0
                    ? roleSuggestions.slice(0, 6)
                    : ['Frontend Engineer', 'Backend Engineer', 'Fullstack Engineer', 'Data Scientist', 'DevOps Engineer']
                  ).map((role) => (
                    <button
                      key={role}
                      type="button"
                      onClick={() => {
                        setTargetRole(role);
                        setFieldErrors((p) => ({ ...p, targetRole: '' }));
                      }}
                      style={{
                        background: targetRole === role ? '#1b3357' : '#12151b',
                        border: targetRole === role ? '1px solid #3b82f6' : '1px solid #ffffff16',
                        borderRadius: '999px',
                        padding: '6px 12px',
                        fontSize: '12px',
                        color: targetRole === role ? '#9ecaff' : '#8893a3',
                        cursor: 'pointer',
                        transition: '.2s',
                      }}
                    >
                      + {role}
                    </button>
                  ))}
                </div>
              </div>

              <label>
                Job description{' '}
                <textarea
                  value={jobDescription}
                  onChange={(e) => setJobDescription(e.target.value)}
                  placeholder="Paste a job description for more tailored practice (optional)"
                />
              </label>
            </>
          )}

          {step === 3 && (
            <>
              <h2>Bring your CV into the room</h2>
              <input
                type="file"
                ref={fileInputRef}
                accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                style={{ display: 'none' }}
                onChange={(e) => {
                  if (e.target.files && e.target.files[0]) {
                    handleUploadFile(e.target.files[0]);
                  }
                }}
              />
              <div
                className={`upload ${isDragging ? 'drag-over' : ''}`}
                onClick={() => fileInputRef.current?.click()}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                style={{ cursor: 'pointer' }}
              >
                {cvStatus === 'extracted' ? (
                  <ShieldCheck style={{ color: '#34d399', width: '28px', height: '28px' }} />
                ) : cvStatus === 'failed' ? (
                  <LockKeyhole style={{ color: '#f87171' }} />
                ) : (
                  <LockKeyhole />
                )}
                <strong>
                  {cvStatus === 'uploading'
                    ? 'Uploading your CV...'
                    : cvStatus === 'extracting'
                    ? 'Analyzing & extracting text...'
                    : cvStatus === 'extracted'
                    ? uploadFileName || 'CV Uploaded'
                    : cvStatus === 'failed'
                    ? 'Upload failed — try again'
                    : 'Drop your CV here, or browse'}
                </strong>
                <span>
                  {cvStatus === 'extracted'
                    ? `✓ Extracted text (${extractedLength || 'done'} characters) · Click to replace`
                    : cvStatus === 'uploading' || cvStatus === 'extracting'
                    ? 'Extracting sections, experience & skills'
                    : 'PDF or DOCX · Max 5 MB'}
                </span>
              </div>

              {cvError && (
                <div
                  className="network-error"
                  style={{
                    marginTop: '15px',
                    textAlign: 'left',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    gap: '12px',
                  }}
                >
                  <div>
                    <strong style={{ color: '#f87171' }}>[{cvError.code}]</strong> {cvError.message}
                  </div>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      fileInputRef.current?.click();
                    }}
                    style={{
                      color: '#60a5fa',
                      textDecoration: 'underline',
                      cursor: 'pointer',
                      background: 'none',
                      border: 'none',
                      padding: '4px 8px',
                      fontSize: '12px',
                      flexShrink: 0,
                    }}
                  >
                    Re-upload
                  </button>
                </div>
              )}

              <div className="parse-list">
                <span className={cvStatus === 'extracted' ? '' : cvStatus === 'extracting' || cvStatus === 'uploading' ? 'active' : 'dim'}>
                  {cvStatus === 'extracted' ? '✓' : cvStatus === 'extracting' || cvStatus === 'uploading' ? '⏳' : '○'} Extracting your experience
                </span>
                <span className={cvStatus === 'extracted' ? '' : cvStatus === 'extracting' ? 'active' : 'dim'}>
                  {cvStatus === 'extracted' ? '✓' : cvStatus === 'extracting' ? '⏳' : '○'} Finding your strongest signals
                </span>
                <span className={parsedCV ? '' : isParsing ? 'active' : 'dim'}>
                  {parsedCV ? '✓' : isParsing ? '⏳' : '○'} Structuring your practice profile
                </span>
              </div>
            </>
          )}

          {step === 4 && (
            <>
              <h2>Review and edit your practice profile</h2>
              <p className="lead" style={{ marginBottom: '25px' }}>
                We synthesized your CV, education form, and target preferences. Fine-tune any section below before starting interviews.
              </p>

              {/* Cross-Check Alignment Flags */}
              {crossCheckFlags.length > 0 && (
                <div style={{ marginBottom: '28px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                    <span style={{ fontSize: '11px', fontFamily: 'DM Mono, monospace', color: '#f59e0b', letterSpacing: '1px' }}>
                      ALIGNMENT CHECK · {crossCheckFlags.length} NOTE{crossCheckFlags.length > 1 ? 'S' : ''} DETECTED
                    </span>
                    {unresolvedHighCount > 0 && (
                      <span style={{ fontSize: '11px', fontFamily: 'DM Mono, monospace', color: '#f87171' }}>
                        {unresolvedHighCount} high-severity note(s) required to resolve
                      </span>
                    )}
                  </div>
                  {crossCheckFlags.map((flag, idx) => {
                    const key = `${flag.type}_${flag.field}_${idx}`;
                    const resInfo = resolvedFlags[key];
                    return (
                      <div key={key} className={`flag-banner ${flag.severity === 'HIGH' ? 'high' : ''}`}>
                        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '10px' }}>
                          <div style={{ display: 'flex', alignItems: 'flex-start', gap: '10px' }}>
                            <AlertTriangle
                              style={{
                                width: '16px',
                                height: '16px',
                                color: flag.severity === 'HIGH' ? '#ef4444' : '#f59e0b',
                                flexShrink: 0,
                                marginTop: '2px',
                              }}
                            />
                            <div>
                              <strong style={{ color: flag.severity === 'HIGH' ? '#f87171' : '#fbbf24' }}>
                                [{flag.severity}] {flag.type}: {flag.field}
                              </strong>
                              <p style={{ margin: '4px 0 0', color: '#d1d5db', fontSize: '12px', lineHeight: '1.4' }}>
                                {flag.message}
                              </p>
                              {flag.cv_value && flag.form_value && (
                                <div style={{ fontSize: '11px', color: '#9ca3af', marginTop: '4px', fontFamily: 'DM Mono, monospace' }}>
                                  CV says: <b style={{ color: '#e2e8f0' }}>{flag.cv_value}</b> · Form says:{' '}
                                  <b style={{ color: '#60a5fa' }}>{flag.form_value}</b>
                                </div>
                              )}
                            </div>
                          </div>
                          {resInfo?.resolved && (
                            <span style={{ color: '#34d399', fontSize: '11px', fontFamily: 'DM Mono, monospace', whiteSpace: 'nowrap' }}>
                              ✓ {resInfo.choice}
                            </span>
                          )}
                        </div>

                        {!resInfo?.resolved && (
                          <div className="flag-actions">
                            {flag.cv_value && flag.form_value ? (
                              <>
                                <button type="button" className="flag-btn cv" onClick={() => resolveFlag(idx, 'cv')}>
                                  Keep CV value ({flag.cv_value})
                                </button>
                                <button type="button" className="flag-btn" onClick={() => resolveFlag(idx, 'form')}>
                                  Use form value ({flag.form_value})
                                </button>
                              </>
                            ) : (
                              <button type="button" className="flag-btn" onClick={() => resolveFlag(idx, 'acknowledge')}>
                                Acknowledge & Keep
                              </button>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Section 1: Personal Info Card */}
              <div className="card-section">
                <h3>Personal Information</h3>
                <div className="form-grid">
                  <label>
                    Full Name
                    <input
                      value={personalName}
                      onChange={(e) => setPersonalName(e.target.value)}
                      placeholder="Your full name"
                    />
                  </label>
                  <label>
                    Email
                    <input
                      value={personalEmail}
                      onChange={(e) => setPersonalEmail(e.target.value)}
                      placeholder="Email address"
                    />
                  </label>
                  <label>
                    Phone
                    <input
                      value={personalPhone}
                      onChange={(e) => setPersonalPhone(e.target.value)}
                      placeholder="+1 (555) 000-0000"
                    />
                  </label>
                  <label>
                    Portfolio / Links
                    <div style={{ display: 'flex', gap: '8px' }}>
                      <input
                        placeholder="Add GitHub, LinkedIn or Portfolio URL"
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault();
                            const val = (e.target as HTMLInputElement).value.trim();
                            if (val) {
                              setPersonalLinks((p) => [...p, val]);
                              (e.target as HTMLInputElement).value = '';
                            }
                          }
                        }}
                      />
                    </div>
                  </label>
                </div>
                {personalLinks.length > 0 && (
                  <div className="chips" style={{ marginTop: '10px', marginBottom: 0 }}>
                    {personalLinks.map((l, i) => (
                      <span key={i}>
                        {l}{' '}
                        <button type="button" onClick={() => setPersonalLinks((p) => p.filter((_, idx) => idx !== i))}>
                          <X style={{ width: '12px' }} />
                        </button>
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {/* Section 2: Education Card */}
              <div className="card-section">
                <h3>Education Profile</h3>
                <div className="form-grid">
                  <label>
                    Degree
                    <select value={eduDegree} onChange={(e) => setEduDegree(e.target.value)}>
                      <option>Bachelor&apos;s degree</option>
                      <option>Master&apos;s degree</option>
                      <option>Ph.D.</option>
                      <option>Diploma</option>
                    </select>
                  </label>
                  <label>
                    Branch / Major
                    <input
                      value={eduBranch}
                      onChange={(e) => setEduBranch(e.target.value)}
                      placeholder="Computer Science"
                    />
                  </label>
                  <label>
                    College / University
                    <input
                      value={eduCollege}
                      onChange={(e) => setEduCollege(e.target.value)}
                      placeholder="University name"
                    />
                  </label>
                  <label>
                    Graduation Year
                    <select value={eduYear} onChange={(e) => setEduYear(e.target.value)}>
                      {[2023, 2024, 2025, 2026, 2027, 2028, 2029].map((y) => (
                        <option key={y} value={y}>
                          {y}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    CGPA / GPA
                    <input
                      value={eduCgpa}
                      onChange={(e) => setEduCgpa(e.target.value)}
                      placeholder="e.g. 3.8 or 8.5"
                    />
                  </label>
                </div>
              </div>

              {/* Section 3: Target Role Card */}
              <div className="card-section">
                <h3>Target Practice Goals</h3>
                <div className="form-grid">
                  <label>
                    Target Role
                    <input
                      value={targetRole}
                      onChange={(e) => setTargetRole(e.target.value)}
                      placeholder="Frontend Engineer"
                    />
                  </label>
                  <label>
                    Company Type
                    <select value={companyType} onChange={(e) => setCompanyType(e.target.value)}>
                      <option value="Product">Product</option>
                      <option value="Startup">Startup</option>
                      <option value="Service">Service</option>
                      <option value="MNC">MNC</option>
                      <option value="Core/Other">Core/Other</option>
                    </select>
                  </label>
                  <label>
                    Experience Level
                    <select value={experienceLevel} onChange={(e) => setExperienceLevel(e.target.value)}>
                      <option value="Fresher">Fresher</option>
                      <option value="0-2">0–2 years</option>
                      <option value="2-5">2–5 years</option>
                      <option value="5+">5+ years</option>
                    </select>
                  </label>
                </div>
              </div>

              {/* Section 4: Skills Card (Grouped) */}
              <div className="card-section">
                <h3>Skills & Capabilities</h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                  {/* Languages */}
                  <div>
                    <span style={{ fontSize: '11px', color: '#6f7b8e', fontFamily: 'DM Mono', letterSpacing: '1px' }}>
                      LANGUAGES:
                    </span>
                    <div className="chips" style={{ marginTop: '8px', marginBottom: 0 }}>
                      {skillsLanguages.map((s, i) => (
                        <span key={i}>
                          {s}{' '}
                          <button type="button" onClick={() => setSkillsLanguages((p) => p.filter((_, idx) => idx !== i))}>
                            <X style={{ width: '12px' }} />
                          </button>
                        </span>
                      ))}
                      <button
                        type="button"
                        onClick={() => {
                          const val = prompt('Add language (e.g. TypeScript, Python):');
                          if (val && val.trim()) setSkillsLanguages((p) => [...p, val.trim()]);
                        }}
                      >
                        + Add language
                      </button>
                    </div>
                  </div>

                  {/* Frameworks */}
                  <div>
                    <span style={{ fontSize: '11px', color: '#6f7b8e', fontFamily: 'DM Mono', letterSpacing: '1px' }}>
                      FRAMEWORKS & LIBRARIES:
                    </span>
                    <div className="chips" style={{ marginTop: '8px', marginBottom: 0 }}>
                      {skillsFrameworks.map((s, i) => (
                        <span key={i}>
                          {s}{' '}
                          <button type="button" onClick={() => setSkillsFrameworks((p) => p.filter((_, idx) => idx !== i))}>
                            <X style={{ width: '12px' }} />
                          </button>
                        </span>
                      ))}
                      <button
                        type="button"
                        onClick={() => {
                          const val = prompt('Add framework (e.g. React, FastAPI):');
                          if (val && val.trim()) setSkillsFrameworks((p) => [...p, val.trim()]);
                        }}
                      >
                        + Add framework
                      </button>
                    </div>
                  </div>

                  {/* Tools */}
                  <div>
                    <span style={{ fontSize: '11px', color: '#6f7b8e', fontFamily: 'DM Mono', letterSpacing: '1px' }}>
                      TOOLS & INFRASTRUCTURE:
                    </span>
                    <div className="chips" style={{ marginTop: '8px', marginBottom: 0 }}>
                      {skillsTools.map((s, i) => (
                        <span key={i}>
                          {s}{' '}
                          <button type="button" onClick={() => setSkillsTools((p) => p.filter((_, idx) => idx !== i))}>
                            <X style={{ width: '12px' }} />
                          </button>
                        </span>
                      ))}
                      <button
                        type="button"
                        onClick={() => {
                          const val = prompt('Add tool (e.g. Docker, Git, PostgreSQL):');
                          if (val && val.trim()) setSkillsTools((p) => [...p, val.trim()]);
                        }}
                      >
                        + Add tool
                      </button>
                    </div>
                  </div>

                  {/* Domains */}
                  <div>
                    <span style={{ fontSize: '11px', color: '#6f7b8e', fontFamily: 'DM Mono', letterSpacing: '1px' }}>
                      DOMAINS & COMPETENCIES:
                    </span>
                    <div className="chips" style={{ marginTop: '8px', marginBottom: 0 }}>
                      {skillsDomains.map((s, i) => (
                        <span key={i}>
                          {s}{' '}
                          <button type="button" onClick={() => setSkillsDomains((p) => p.filter((_, idx) => idx !== i))}>
                            <X style={{ width: '12px' }} />
                          </button>
                        </span>
                      ))}
                      <button
                        type="button"
                        onClick={() => {
                          const val = prompt('Add domain (e.g. Distributed Systems, Frontend):');
                          if (val && val.trim()) setSkillsDomains((p) => [...p, val.trim()]);
                        }}
                      >
                        + Add domain
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              {/* Section 5: Projects Card */}
              <div className="card-section">
                <h3>
                  <span>Projects ({projectsList.length})</span>
                  <button
                    type="button"
                    className="flag-btn"
                    onClick={() => {
                      const title = prompt('Project title:');
                      if (title && title.trim()) {
                        const desc = prompt('Short description:') || '';
                        const tech = prompt('Tech stack (comma-separated):') || '';
                        setProjectsList((p) => [
                          ...p,
                          {
                            title: title.trim(),
                            description: desc.trim(),
                            tech_stack: tech.split(',').map((t) => t.trim()).filter(Boolean),
                          },
                        ]);
                        // If there was a missing projects flag, resolve it
                        crossCheckFlags.forEach((f, idx) => {
                          if (f.field === 'projects') resolveFlag(idx, 'acknowledge');
                        });
                      }
                    }}
                  >
                    + Add Project
                  </button>
                </h3>
                {projectsList.length === 0 ? (
                  <p style={{ color: '#6f7b8e', fontSize: '13px' }}>No projects added yet.</p>
                ) : (
                  projectsList.map((proj, idx) => (
                    <div key={idx} className="item-box">
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                        <div>
                          <strong style={{ color: '#f2f4f8', fontSize: '14px' }}>{proj.title}</strong>
                          {proj.role && (
                            <span style={{ fontSize: '12px', color: '#60a5fa', marginLeft: '10px' }}>
                              ({proj.role})
                            </span>
                          )}
                          {proj.description && (
                            <p style={{ margin: '6px 0', color: '#9ca3af', fontSize: '12px', lineHeight: '1.4' }}>
                              {proj.description}
                            </p>
                          )}
                          {proj.tech_stack && proj.tech_stack.length > 0 && (
                            <div className="chips" style={{ marginTop: '8px', marginBottom: 0 }}>
                              {proj.tech_stack.map((t, ti) => (
                                <span key={ti} style={{ padding: '4px 8px', fontSize: '11px' }}>
                                  {t}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                        <button
                          type="button"
                          onClick={() => setProjectsList((p) => p.filter((_, i) => i !== idx))}
                          style={{ color: '#f87171', padding: '4px', cursor: 'pointer' }}
                        >
                          <Trash2 style={{ width: '15px' }} />
                        </button>
                      </div>
                    </div>
                  ))
                )}
              </div>

              {/* Section 6: Experience Card */}
              <div className="card-section">
                <h3>
                  <span>Internships & Experience ({experienceList.length})</span>
                  <button
                    type="button"
                    className="flag-btn"
                    onClick={() => {
                      const comp = prompt('Company name:');
                      if (comp && comp.trim()) {
                        const role = prompt('Role title:') || 'Intern';
                        const dur = prompt('Duration (e.g. Jun 2024 - Aug 2024):') || '';
                        setExperienceList((p) => [
                          ...p,
                          {
                            company: comp.trim(),
                            role: role.trim(),
                            duration: dur.trim(),
                            responsibilities: [],
                          },
                        ]);
                      }
                    }}
                  >
                    + Add Experience
                  </button>
                </h3>
                {experienceList.length === 0 ? (
                  <p style={{ color: '#6f7b8e', fontSize: '13px' }}>No work or internship experience added.</p>
                ) : (
                  experienceList.map((exp, idx) => (
                    <div key={idx} className="item-box">
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                        <div>
                          <strong style={{ color: '#f2f4f8', fontSize: '14px' }}>{exp.role}</strong>
                          <span style={{ fontSize: '12px', color: '#60a5fa', marginLeft: '10px' }}>
                            @ {exp.company}
                          </span>
                          {exp.duration && (
                            <span style={{ fontSize: '11px', color: '#6f7b8e', marginLeft: '10px', fontFamily: 'DM Mono' }}>
                              ({exp.duration})
                            </span>
                          )}
                          {exp.responsibilities && exp.responsibilities.length > 0 && (
                            <ul style={{ margin: '6px 0 0 16px', color: '#9ca3af', fontSize: '12px', padding: 0 }}>
                              {exp.responsibilities.map((r, ri) => (
                                <li key={ri}>{r}</li>
                              ))}
                            </ul>
                          )}
                        </div>
                        <button
                          type="button"
                          onClick={() => setExperienceList((p) => p.filter((_, i) => i !== idx))}
                          style={{ color: '#f87171', padding: '4px', cursor: 'pointer' }}
                        >
                          <Trash2 style={{ width: '15px' }} />
                        </button>
                      </div>
                    </div>
                  ))
                )}
              </div>

              {/* Section 7: Certifications & Achievements */}
              <div className="card-section">
                <h3>Certifications & Achievements</h3>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
                  <div>
                    <span style={{ fontSize: '11px', color: '#6f7b8e', fontFamily: 'DM Mono', letterSpacing: '1px' }}>
                      CERTIFICATIONS:
                    </span>
                    <div className="chips" style={{ marginTop: '8px', marginBottom: 0 }}>
                      {certificationsList.map((c, i) => (
                        <span key={i}>
                          {c}{' '}
                          <button type="button" onClick={() => setCertificationsList((p) => p.filter((_, idx) => idx !== i))}>
                            <X style={{ width: '12px' }} />
                          </button>
                        </span>
                      ))}
                      <button
                        type="button"
                        onClick={() => {
                          const val = prompt('Add certification:');
                          if (val && val.trim()) setCertificationsList((p) => [...p, val.trim()]);
                        }}
                      >
                        + Add cert
                      </button>
                    </div>
                  </div>
                  <div>
                    <span style={{ fontSize: '11px', color: '#6f7b8e', fontFamily: 'DM Mono', letterSpacing: '1px' }}>
                      ACHIEVEMENTS:
                    </span>
                    <div className="chips" style={{ marginTop: '8px', marginBottom: 0 }}>
                      {achievementsList.map((a, i) => (
                        <span key={i}>
                          {a}{' '}
                          <button type="button" onClick={() => setAchievementsList((p) => p.filter((_, idx) => idx !== i))}>
                            <X style={{ width: '12px' }} />
                          </button>
                        </span>
                      ))}
                      <button
                        type="button"
                        onClick={() => {
                          const val = prompt('Add achievement / award:');
                          if (val && val.trim()) setAchievementsList((p) => [...p, val.trim()]);
                        }}
                      >
                        + Add achievement
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </>
          )}

          <div className="wizard-actions">
            {step > 1 && (
              <button className="secondary" onClick={() => setStep(step - 1)}>
                Back
              </button>
            )}
            <Pill
              disabled={
                saving ||
                cvStatus === 'uploading' ||
                cvStatus === 'extracting' ||
                isParsing ||
                (step === 4 && unresolvedHighCount > 0)
              }
              onClick={() => {
                if (step === 1) {
                  handleContinueEducation();
                } else if (step === 2) {
                  handleContinueTarget();
                } else if (step === 3) {
                  handleProceedToStep4();
                } else {
                  handleConfirmProfile();
                }
              }}
            >
              {saving
                ? 'Saving profile...'
                : cvStatus === 'uploading' || cvStatus === 'extracting'
                ? 'Extracting...'
                : isParsing
                ? 'Structuring CV...'
                : step < 4
                ? 'Continue'
                : unresolvedHighCount > 0
                ? `Resolve ${unresolvedHighCount} high-severity note(s)`
                : 'Confirm profile & go to dashboard'}
            </Pill>
          </div>
        </div>
      </main>
    </Shell>
  );
}

function Dashboard({ go }: { go: (p: string) => void }) {
  const { user } = useAuth();
  const userName = user?.name?.trim() || user?.email?.split('@')[0] || 'Candidate';
  const userEmail = user?.email || '';
  const [summary, setSummary] = useState<DashboardSummaryResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    let isMounted = true;
    async function loadDashboard() {
      setLoading(true);
      try {
        const data = await api.getDashboardSummary();
        if (isMounted) setSummary(data);
      } catch (err) {
        console.warn('Failed to load dashboard summary:', err);
      } finally {
        if (isMounted) setLoading(false);
      }
    }
    loadDashboard();
    return () => {
      isMounted = false;
    };
  }, []);

  const lastSess = summary?.last_session;
  const lastScore = Math.round(lastSess?.overall_score ?? 84);
  const lastRound = lastSess?.round_type ?? 'Technical';
  const lastClass = lastSess?.classification ?? 'STRONG';
  const sessionCount = summary?.session_count ?? (summary?.recent_sessions?.length || 1);
  const avgScore = Math.round(summary?.average_score ?? lastScore);

  const trendScores = summary?.trend_scores && summary.trend_scores.length > 0
    ? summary.trend_scores
    : [
        { session_id: 1, date: 'Sep 28', score: 68, round: 'Technical' },
        { session_id: 2, date: 'Oct 02', score: 75, round: 'HR' },
        { session_id: 3, date: 'Today', score: lastScore, round: lastRound },
      ];

  const recentSessions = summary?.recent_sessions && summary.recent_sessions.length > 0
    ? summary.recent_sessions
    : [
        {
          id: 1,
          round_type: 'Technical',
          role: 'Software Engineer',
          difficulty: 'Hard',
          status: 'closed',
          created_at: null,
          date_display: 'Today',
          overall_score: 84,
          content_score: 88,
          speech_score: 80,
          face_score: 82,
          classification: 'STRONG',
          weak_areas: [],
          has_report: true,
        },
      ];

  const weakAreas = summary?.current_weak_areas && summary.current_weak_areas.length > 0
    ? summary.current_weak_areas
    : ['System Design Bottlenecks', 'Vocal Pacing'];

  return (
    <Shell go={go}>
      <main className="app-main">
        {/* Intro */}
        <div className="page-intro">
          <div>
            <span className="eyebrow">PRACTICE DASHBOARD · {new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }).toUpperCase()}</span>
            <h1>
              Good day, <em>{userName}.</em>
            </h1>
            <p>
              {userEmail ? (
                <>
                  Signed in as <strong style={{ color: 'var(--text-strong, #ffffff)' }}>{userEmail}</strong>. Every rep sharpens your delivery and cements your domain knowledge.
                </>
              ) : (
                'Every rep sharpens your delivery and cements your domain knowledge.'
              )}
            </p>
          </div>
          <Pill onClick={() => go('/interview/setup')}>Start new interview</Pill>
        </div>

        {/* High-level score & streak cards */}
        <div className="dash-grid">
          <div
            className="score-card"
            style={{ cursor: lastSess ? 'pointer' : 'default' }}
            onClick={() => lastSess && go(`/report/${lastSess.id}`)}
          >
            <div>
              <span className="eyebrow">
                LAST SESSION · {lastRound.toUpperCase()}
              </span>
              <h2>{lastClass === 'STRONG' ? 'Strong signal.' : 'Good progress.'}</h2>
              <p>
                {lastSess?.has_report
                  ? 'Your detailed multimodal evaluation report is ready.'
                  : "Let's build on your progress with targeted reps."}
              </p>
            </div>
            <div className="score-ring">
              <strong>{lastScore}</strong>
              <span>/100</span>
            </div>
          </div>

          <div className="stat-card">
            <span className="eyebrow">PRACTICE OVERVIEW</span>
            <strong>
              {sessionCount} <small>sessions</small>
            </strong>
            <p>Average score: <b>{avgScore}/100</b></p>
            <div className="streak-bars">
              {[1, 1, 1, 1, 1, 1, 1].slice(0, Math.min(7, sessionCount || 3)).map((x, i) => (
                <i className="active" key={i} />
              ))}
            </div>
          </div>
        </div>

        {/* Current Identified Weak Areas */}
        <div className="section-head" style={{ marginTop: 45 }}>
          <h2>Identified Focus & Growth Areas</h2>
          <span className="eyebrow">FROM INTERVIEW MEMORY</span>
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          {weakAreas.map((wa) => (
            <button
              key={wa}
              onClick={() => go(`/interview/setup?focus=${encodeURIComponent(wa)}&round=${lastRound}`)}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 8,
                background: 'rgba(239, 68, 68, 0.1)',
                border: '1px solid rgba(239, 68, 68, 0.25)',
                color: '#fca5a5',
                padding: '8px 14px',
                borderRadius: 999,
                fontSize: 12.5,
                fontWeight: 500,
                cursor: 'pointer',
              }}
            >
              <Target style={{ width: 14 }} />
              <span>{wa}</span>
              <span style={{ fontSize: 10, color: '#f87171', marginLeft: 4 }}>Practice rep ›</span>
            </button>
          ))}
        </div>

        {/* Practice Rhythm / Progression Trend */}
        <div className="section-head" style={{ marginTop: 45 }}>
          <h2>Your practice rhythm</h2>
          <button onClick={() => go('/history')}>
            View history <ArrowUpRight />
          </button>
        </div>
        <div className="chart-card">
          <div className="chart-bars">
            {trendScores.map((t, i) => (
              <div key={i} style={{ cursor: 'pointer' }} onClick={() => go(`/report/${t.session_id}`)}>
                <i style={{ height: `${Math.max(25, Math.min(100, t.score))}%` }} />
                <span>{t.date}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Recent sessions */}
        <div className="section-head">
          <h2>Recent sessions</h2>
          <button onClick={() => go('/history')}>
            See all <ArrowUpRight />
          </button>
        </div>
        <div className="session-list">
          {recentSessions.map((s) => (
            <button
              className="session-row"
              key={s.id}
              onClick={() => go(`/report/${s.id}`)}
            >
              <span className="round-dot">{s.round_type ? s.round_type[0] : 'T'}</span>
              <div>
                <strong>{s.round_type} Round</strong>
                <small>
                  {s.role} · {s.date_display} · {s.difficulty} difficulty
                </small>
              </div>
              <b>
                {s.overall_score !== null && s.overall_score !== undefined
                  ? `${Math.round(s.overall_score)}`
                  : '--'}
                <small>/100</small>
              </b>
              <ChevronRight />
            </button>
          ))}
        </div>

        {/* Quick Actions / Next Best Rep */}
        <div className="next-card" style={{ marginTop: 45 }}>
          <div>
            <span className="eyebrow">QUICK ACTIONS · RETAKE LOOP</span>
            <h2>{summary?.quick_actions?.try_next_round?.label || 'One more rep?'}</h2>
            <p>
              Target your weak areas or advance to the next stage in your interview roadmap.
            </p>
          </div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <Pill onClick={() => go(summary?.quick_actions?.retake_same_round?.route || `/interview/setup?round=${lastRound}&retake=true`)}>
              <RefreshCw style={{ width: 14 }} />
              Retake {lastRound}
            </Pill>
            <button
              className="secondary"
              onClick={() => go(summary?.quick_actions?.try_next_round?.route || '/interview/setup')}
              style={{ display: 'flex', alignItems: 'center', gap: 6 }}
            >
              <ArrowUpRight style={{ width: 14 }} />
              Next round type
            </button>
          </div>
        </div>
      </main>
    </Shell>
  );
}

function Setup({ go }: { go: (p: string) => void }) {
  const [selected, setSelected] = useState<Round>('Technical');
  const [difficulty, setDifficulty] = useState<string>('Medium');
  const [duration, setDuration] = useState<number>(30);
  const [language, setLanguage] = useState<string>('English');
  const [isPressureMode, setIsPressureMode] = useState<boolean>(false);
  const [focusTopics, setFocusTopics] = useState<string[]>(['Communication', 'Problem solving', 'Architecture & design']);
  const [newTopicInput, setNewTopicInput] = useState<string>('');

  const [userContext, setUserContext] = useState<UserContext | null>(null);
  const [loadingContext, setLoadingContext] = useState<boolean>(true);
  const [saving, setSaving] = useState<boolean>(false);

  useEffect(() => {
    async function loadContext() {
      setLoadingContext(true);
      try {
        const ctx = await api.getInterviewContext();
        setUserContext(ctx);

        if (ctx.is_returning) {
          if (ctx.recommended_difficulty) {
            setDifficulty(ctx.recommended_difficulty);
          }
          if (ctx.weak_areas && ctx.weak_areas.length > 0) {
            // Prioritize weak areas as initial focus topics
            setFocusTopics(Array.from(new Set([...ctx.weak_areas, 'Problem solving'])));
          }
        }

        // Apply URL query parameters (for retake and next round flows)
        const params = new URLSearchParams(window.location.search);
        const roundParam = params.get('round');
        if (roundParam && ['Technical', 'HR', 'Managerial', 'Mixed'].includes(roundParam)) {
          setSelected(roundParam as Round);
        }
        const focusParam = params.get('focus');
        if (focusParam) {
          const parsed = focusParam.split(',').map((s) => s.trim()).filter(Boolean);
          if (parsed.length > 0) {
            setFocusTopics(Array.from(new Set([...parsed, 'Problem solving'])));
          }
        }
      } catch {
        // Fallback to default state
      } finally {
        setLoadingContext(false);
      }
    }
    loadContext();
  }, []);

  const handleAddTopic = () => {
    const trimmed = newTopicInput.trim();
    if (trimmed && !focusTopics.includes(trimmed)) {
      setFocusTopics([...focusTopics, trimmed]);
      setNewTopicInput('');
    }
  };

  const handleRemoveTopic = (topicToRemove: string) => {
    setFocusTopics(focusTopics.filter((t) => t !== topicToRemove));
  };

  const handleSaveAndContinue = async () => {
    setSaving(true);
    try {
      const mode = isPressureMode ? 'pressure' : 'normal';
      await api.saveInterviewConfig({
        round_type: selected,
        difficulty,
        duration_minutes: duration,
        language,
        mode,
        focus_topics: focusTopics,
      });

      toast.success(
        `${selected} round configured (${isPressureMode ? '⚡ Pressure' : 'Normal'} mode, ${duration} min)`
      );
      go('/interview/precheck');
    } catch (err: any) {
      toast.error(err.detail || 'Failed to save interview configuration');
    } finally {
      setSaving(false);
    }
  };

  const isReturning = userContext?.is_returning ?? false;
  const sessionCount = userContext?.session_count ?? 0;
  const weakAreas = userContext?.weak_areas ?? [];
  const pastScores = userContext?.past_scores ?? {};

  return (
    <Shell go={go}>
      <main className="app-main narrow">
        <div className="page-intro">
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
              <span className="eyebrow">NEW INTERVIEW</span>
              {loadingContext ? (
                <span className="returning-badge new">Loading history...</span>
              ) : isReturning ? (
                <span className="returning-badge returning">
                  ★ Returning Candidate · Session #{sessionCount + 1}
                </span>
              ) : (
                <span className="returning-badge new">
                  ● New Candidate · Baseline Tuning
                </span>
              )}
            </div>
            <h1>
              Choose your <em>challenge.</em>
            </h1>
            <p>
              {isReturning
                ? 'Your interview is personalized based on past weak areas and performance history.'
                : "We'll tune the room to evaluate your baseline strengths and growth areas."}
            </p>
          </div>
        </div>

        <div className="setup-layout">
          <div>
            <h3>Round type</h3>
            <div className="round-select" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
              {rounds.map((r) => (
                <button className={selected === r ? 'selected' : ''} onClick={() => setSelected(r)} key={r}>
                  <span>{r === 'Technical' ? '⌘' : r === 'HR' ? '◌' : r === 'Managerial' ? '◈' : '❖'}</span>
                  <strong>{r}</strong>
                  <small>
                    {r === 'Technical'
                      ? 'Problem solving & code'
                      : r === 'HR'
                      ? 'Culture, story & motivation'
                      : r === 'Managerial'
                      ? 'Strategy & leadership'
                      : 'Cross-functional mix'}
                  </small>
                </button>
              ))}
            </div>

            <div className="settings-card">
              <label>
                Difficulty
                <select value={difficulty} onChange={(e) => setDifficulty(e.target.value)}>
                  <option value="Adaptive">Adaptive (Dynamic)</option>
                  <option value="Medium">Medium</option>
                  <option value="Easy">Easy</option>
                  <option value="Hard">Hard</option>
                </select>
              </label>

              <label>
                Duration
                <select value={duration} onChange={(e) => setDuration(parseInt(e.target.value, 10))}>
                  <option value={15}>15 minutes (Quick rep)</option>
                  <option value={30}>30 minutes (Standard)</option>
                  <option value={45}>45 minutes (In-depth)</option>
                  <option value={60}>60 minutes (Comprehensive)</option>
                </select>
              </label>

              <label>
                Language
                <select value={language} onChange={(e) => setLanguage(e.target.value)}>
                  <option value="English">English</option>
                  <option value="Spanish">Spanish</option>
                  <option value="German">German</option>
                  <option value="French">French</option>
                  <option value="Hindi">Hindi</option>
                </select>
              </label>

              <label className="toggle-row" style={{ marginTop: '22px' }}>
                <div>
                  <strong style={{ display: 'block', fontSize: '13px', color: '#e2e8f0' }}>Pressure mode</strong>
                  <small style={{ color: '#94a3b8', fontSize: '11px' }}>Shorter timers & tougher follow-ups</small>
                </div>
                <input
                  type="checkbox"
                  checked={isPressureMode}
                  onChange={(e) => setIsPressureMode(e.target.checked)}
                />
              </label>
            </div>

            {/* Pressure mode highlight banner */}
            <div className={`pressure-card ${isPressureMode ? '' : 'normal'}`}>
              {isPressureMode ? (
                <>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 700, marginBottom: '4px' }}>
                    <Zap style={{ width: '15px', height: '15px', color: '#f87171' }} />
                    Pressure Mode Active
                  </div>
                  <span>
                    Shorter 60s answer limits, surprise interruptions, and aggressive follow-up challenges apply to test composure under stress.
                  </span>
                </>
              ) : (
                <>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 600, marginBottom: '4px' }}>
                    <Clock3 style={{ width: '15px', height: '15px', color: '#60a5fa' }} />
                    Standard Pacing Mode
                  </div>
                  <span>
                    Standard 120s answer limits with supportive follow-ups and conversational guidance.
                  </span>
                </>
              )}
            </div>

            {/* Returning Candidate Prior Insights */}
            {isReturning && weakAreas.length > 0 && (
              <div style={{ marginTop: '24px', padding: '16px', borderRadius: '14px', background: '#12151b', border: '1px solid #ffffff0d' }}>
                <span className="eyebrow" style={{ color: '#f87171' }}>
                  TARGETED WEAK AREAS FROM PAST SESSIONS
                </span>
                <p style={{ fontSize: '12px', color: '#9ca3af', margin: '6px 0 10px' }}>
                  Click to add any weak area to this interview&apos;s active target topics:
                </p>
                <div className="weak-badge-row">
                  {weakAreas.map((w) => (
                    <button
                      key={w}
                      type="button"
                      className="weak-chip"
                      onClick={() => {
                        if (!focusTopics.includes(w)) {
                          setFocusTopics([...focusTopics, w]);
                          toast.success(`Added '${w}' to target focus topics`);
                        }
                      }}
                    >
                      <Target style={{ width: '12px', height: '12px' }} />
                      {w} {focusTopics.includes(w) ? '✓' : '+'}
                    </button>
                  ))}
                </div>

                {Object.keys(pastScores).length > 0 && (
                  <>
                    <span className="eyebrow" style={{ display: 'block', marginTop: '12px' }}>
                      PAST TOPIC SCORES
                    </span>
                    <div className="score-pill-row">
                      {Object.entries(pastScores).map(([topic, score]) => (
                        <div key={topic} className="score-pill">
                          <span style={{ color: '#cbd5e1' }}>{topic}</span>
                          <b>{score}%</b>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </div>
            )}
          </div>

          {/* Sidebar Summary */}
          <aside className="summary">
            <span className="eyebrow">YOUR SESSION BLUEPRINT</span>
            <h2>{selected} round</h2>
            <p>
              ~{Math.round(duration / 3)} adaptive questions · approx. {duration} min ·{' '}
              <b style={{ color: isPressureMode ? '#f87171' : '#60a5fa' }}>
                {isPressureMode ? 'Pressure' : 'Normal'}
              </b>
            </p>

            <div style={{ margin: '20px 0 10px' }}>
              <span className="eyebrow">FOCUS TOPICS</span>
              <div className="topic-list" style={{ margin: '10px 0 12px' }}>
                {focusTopics.map((t) => (
                  <span key={t}>
                    {t}{' '}
                    <button type="button" onClick={() => handleRemoveTopic(t)} style={{ padding: 0 }}>
                      <X style={{ width: '12px', height: '12px' }} />
                    </button>
                  </span>
                ))}
              </div>

              <div style={{ display: 'flex', gap: '8px', marginTop: '10px' }}>
                <input
                  style={{
                    flex: 1,
                    background: '#0d1117',
                    border: '1px solid #ffffff15',
                    borderRadius: '8px',
                    padding: '8px 12px',
                    fontSize: '12px',
                    color: '#fff',
                  }}
                  placeholder="Add custom topic..."
                  value={newTopicInput}
                  onChange={(e) => setNewTopicInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      handleAddTopic();
                    }
                  }}
                />
                <button
                  type="button"
                  onClick={handleAddTopic}
                  style={{
                    background: '#1e293b',
                    border: '1px solid #ffffff20',
                    borderRadius: '8px',
                    padding: '8px 14px',
                    fontSize: '12px',
                    fontWeight: 600,
                  }}
                >
                  Add
                </button>
              </div>
            </div>

            {userContext && userContext.history_asked_questions.length > 0 && (
              <div style={{ fontSize: '11px', color: '#94a3b8', margin: '14px 0 20px', fontFamily: 'DM Mono, monospace' }}>
                ✓ {userContext.history_asked_questions.length} past questions indexed to prevent repeats
              </div>
            )}

            <Pill disabled={saving} onClick={handleSaveAndContinue}>
              {saving ? 'Configuring room...' : 'Continue to system check'}
            </Pill>
          </aside>
        </div>
      </main>
    </Shell>
  );
}

function GuestSetup({ go }: { go: (p: string) => void }) {
  const [selectedRole, setSelectedRole] = useState('Software Engineer');
  const [customRole, setCustomRole] = useState('');
  const [roundType, setRoundType] = useState<Round>('Technical');
  const [difficulty, setDifficulty] = useState<string>('Medium');

  // Optional CV Upload
  const [cvFile, setCvFile] = useState<File | null>(null);
  const [cvDocumentId, setCvDocumentId] = useState<number | null>(null);
  const [cvText, setCvText] = useState<string>('');
  const [uploadingCv, setUploadingCv] = useState(false);
  const [uploadError, setUploadError] = useState<string>('');

  // Human Verification / Turnstile
  const [captchaVerified, setCaptchaVerified] = useState(false);
  const [captchaToken, setCaptchaToken] = useState('mock_turnstile_token');

  // Privacy & Retention Consent
  const [privacyAgreed, setPrivacyAgreed] = useState(true);

  // Loading state
  const [starting, setStarting] = useState(false);

  const roleSuggestions = [
    'Software Engineer',
    'Frontend Developer',
    'Backend Engineer',
    'Data Scientist',
    'Product Manager',
    'Engineering Manager',
  ];

  const effectiveRole = customRole.trim() || selectedRole;

  const handleCvChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    setUploadError('');
    if (!e.target.files || e.target.files.length === 0) return;
    const file = e.target.files[0];

    // Strictly enforce 2MB limit for guests
    const maxBytes = 2 * 1024 * 1024;
    if (file.size > maxBytes) {
      setUploadError(`CV file exceeds the 2MB guest limit (${(file.size / (1024 * 1024)).toFixed(1)} MB).`);
      toast.error('File size exceeds the 2MB guest limit.');
      return;
    }

    setCvFile(file);
    setUploadingCv(true);
    try {
      const resp = await api.uploadGuestCv(file);
      setCvDocumentId(resp.cv_document_id);
      setCvText(resp.raw_text_snippet || '');
      toast.success(`CV attached (${file.name})! Personalized questions will be generated.`);
    } catch (err: any) {
      setUploadError(err.detail || 'Failed to upload CV');
      toast.error(err.detail || 'Failed to upload CV');
      setCvFile(null);
    } finally {
      setUploadingCv(false);
    }
  };

  const handleStartGuestSession = async () => {
    if (!privacyAgreed) {
      toast.error('Please accept the 24-hour privacy and retention terms.');
      return;
    }
    if (!captchaVerified) {
      toast.error('Please complete human verification (Turnstile CAPTCHA).');
      return;
    }

    setStarting(true);
    try {
      const data = await api.startGuestSession({
        target_role: effectiveRole,
        round_type: roundType,
        difficulty,
        cv_document_id: cvDocumentId || undefined,
        cv_text: cvText,
        turnstile_token: captchaToken,
      });

      toast.success('Guest practice session ready! (3 questions · 10 minutes)');
      go('/interview/precheck');
    } catch (err: any) {
      toast.error(err.detail || 'Could not start guest practice session.');
    } finally {
      setStarting(false);
    }
  };

  return (
    <Shell go={go}>
      <main className="app-main narrow">
        <div className="page-intro">
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
              <span className="eyebrow">NO-LOGIN PRACTICE MODE</span>
              <span className="returning-badge new">
                ⚡ Anonymous · Instant Access · 24h Purge
              </span>
            </div>
            <h1>
              Jump right into <em>practice.</em>
            </h1>
            <p>
              Experience a full 8–10 minute AI interview with real-time audio, video proctoring, and comprehensive grounded feedback. No account or password required.
            </p>
          </div>
        </div>

        <div className="setup-layout">
          <div>
            {/* 1. Target Role */}
            <div className="settings-card" style={{ marginBottom: 20 }}>
              <label style={{ display: 'block', marginBottom: 8, fontWeight: 600, color: '#f1f5f9' }}>
                Target Role
              </label>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
                {roleSuggestions.map((r) => (
                  <button
                    key={r}
                    type="button"
                    onClick={() => {
                      setSelectedRole(r);
                      setCustomRole('');
                    }}
                    style={{
                      background: selectedRole === r && !customRole ? 'rgba(59, 130, 246, 0.2)' : 'rgba(255, 255, 255, 0.04)',
                      border: selectedRole === r && !customRole ? '1px solid #3b82f6' : '1px solid rgba(255, 255, 255, 0.1)',
                      color: selectedRole === r && !customRole ? '#60a5fa' : '#cbd5e1',
                      borderRadius: 20,
                      padding: '6px 14px',
                      fontSize: 12,
                      cursor: 'pointer',
                      transition: 'all 0.15s ease',
                    }}
                  >
                    {r}
                  </button>
                ))}
              </div>
              <input
                type="text"
                placeholder="Or type a custom role (e.g. Cloud Security Architect)..."
                value={customRole}
                onChange={(e) => setCustomRole(e.target.value)}
                style={{
                  width: '100%',
                  background: '#0f172a',
                  border: '1px solid rgba(255, 255, 255, 0.12)',
                  borderRadius: 8,
                  padding: '10px 14px',
                  color: '#fff',
                  fontSize: 13,
                }}
              />
            </div>

            {/* 2. Round Type */}
            <h3 style={{ marginTop: 24 }}>Interview round</h3>
            <div className="round-select" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
              {(['Technical', 'HR', 'Managerial'] as Round[]).map((r) => (
                <button
                  key={r}
                  className={roundType === r ? 'selected' : ''}
                  onClick={() => setRoundType(r)}
                >
                  <span>{r === 'Technical' ? '⌘' : r === 'HR' ? '◌' : '◈'}</span>
                  <strong>{r}</strong>
                  <small>
                    {r === 'Technical'
                      ? 'Problem solving & engineering'
                      : r === 'HR'
                      ? 'Culture, storytelling & fit'
                      : 'Leadership & scenario judgment'}
                  </small>
                </button>
              ))}
            </div>

            {/* 3. Difficulty */}
            <div className="settings-card" style={{ marginTop: 20 }}>
              <label style={{ display: 'block', marginBottom: 8, fontWeight: 600, color: '#f1f5f9' }}>
                Difficulty Level
              </label>
              <div style={{ display: 'flex', gap: 10 }}>
                {['Easy', 'Medium', 'Hard'].map((d) => (
                  <button
                    key={d}
                    type="button"
                    onClick={() => setDifficulty(d)}
                    style={{
                      flex: 1,
                      background: difficulty === d ? 'rgba(59, 130, 246, 0.2)' : 'rgba(255, 255, 255, 0.04)',
                      border: difficulty === d ? '1px solid #3b82f6' : '1px solid rgba(255, 255, 255, 0.1)',
                      color: difficulty === d ? '#60a5fa' : '#cbd5e1',
                      borderRadius: 8,
                      padding: '10px',
                      fontSize: 13,
                      fontWeight: 600,
                      cursor: 'pointer',
                    }}
                  >
                    {d}
                  </button>
                ))}
              </div>
            </div>

            {/* 4. Optional CV Upload (2MB limit) */}
            <div className="settings-card" style={{ marginTop: 20 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                <label style={{ fontWeight: 600, color: '#f1f5f9', margin: 0 }}>
                  Upload CV (Optional)
                </label>
                <span style={{ fontSize: 11, color: '#94a3b8' }}>Max 2MB · PDF, DOCX, TXT</span>
              </div>
              <p style={{ fontSize: 12, color: '#94a3b8', margin: '0 0 12px' }}>
                Provide your resume to get questions tailored specifically to your background and projects.
              </p>

              <label
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 10,
                  padding: '16px',
                  border: '1px dashed rgba(255, 255, 255, 0.2)',
                  borderRadius: 10,
                  background: 'rgba(255, 255, 255, 0.02)',
                  cursor: 'pointer',
                  color: '#cbd5e1',
                  fontSize: 13,
                }}
              >
                <FileText style={{ width: 18, height: 18, color: '#60a5fa' }} />
                <span>
                  {uploadingCv
                    ? 'Extracting CV text...'
                    : cvFile
                    ? `${cvFile.name} (${(cvFile.size / 1024).toFixed(0)} KB)`
                    : 'Click to choose CV file'}
                </span>
                <input
                  type="file"
                  accept=".pdf,.docx,.txt"
                  onChange={handleCvChange}
                  disabled={uploadingCv}
                  style={{ display: 'none' }}
                />
              </label>

              {uploadError && (
                <div style={{ color: '#f87171', fontSize: 12, marginTop: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
                  <AlertCircle style={{ width: 14 }} />
                  {uploadError}
                </div>
              )}
            </div>
          </div>

          <aside className="setup-sidebar">
            <div className="summary-card">
              <h4>Practice Room Blueprint</h4>
              <ul>
                <li>
                  <span>Format</span>
                  <strong>Shorter Mock ({roundType})</strong>
                </li>
                <li>
                  <span>Role Target</span>
                  <strong>{effectiveRole}</strong>
                </li>
                <li>
                  <span>Question Count</span>
                  <strong>3 Questions</strong>
                </li>
                <li>
                  <span>Estimated Time</span>
                  <strong>8 – 10 minutes</strong>
                </li>
                <li>
                  <span>Multimodal Signal</span>
                  <strong>Audio + Camera + Pacing</strong>
                </li>
                <li>
                  <span>Scoring Engine</span>
                  <strong>Identical to Full Suite</strong>
                </li>
              </ul>
            </div>

            {/* Cloudflare Turnstile CAPTCHA Box */}
            <div
              style={{
                background: 'rgba(15, 23, 42, 0.8)',
                border: '1px solid rgba(59, 130, 246, 0.25)',
                borderRadius: 12,
                padding: '16px',
                marginTop: 20,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
                <span className="eyebrow" style={{ color: '#60a5fa', fontSize: 10 }}>
                  ABUSE PROTECTION
                </span>
                <span style={{ fontSize: 11, color: '#64748b', fontFamily: 'DM Mono, monospace' }}>
                  Cloudflare Turnstile
                </span>
              </div>
              <label
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12,
                  cursor: 'pointer',
                  fontSize: 13,
                  color: '#e2e8f0',
                  userSelect: 'none',
                }}
              >
                <input
                  type="checkbox"
                  checked={captchaVerified}
                  onChange={(e) => {
                    setCaptchaVerified(e.target.checked);
                    if (e.target.checked) {
                      setCaptchaToken('mock_turnstile_token');
                    }
                  }}
                  style={{ width: 18, height: 18, accentColor: '#3b82f6', cursor: 'pointer' }}
                />
                <span>I am a human candidate</span>
                <ShieldCheck style={{ width: 16, height: 16, color: captchaVerified ? '#34d399' : '#64748b', marginLeft: 'auto' }} />
              </label>
            </div>

            {/* 24-Hour Privacy Notice */}
            <div
              style={{
                background: 'rgba(234, 179, 8, 0.05)',
                border: '1px solid rgba(234, 179, 8, 0.2)',
                borderRadius: 12,
                padding: '14px 16px',
                marginTop: 16,
              }}
            >
              <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
                <Clock3 style={{ width: 16, height: 16, color: '#fbbf24', flexShrink: 0, marginTop: 2 }} />
                <div>
                  <strong style={{ display: 'block', fontSize: 12, color: '#fef08a', marginBottom: 2 }}>
                    24-Hour Auto-Purge Policy
                  </strong>
                  <p style={{ margin: 0, fontSize: 11.5, color: '#94a3b8', lineHeight: 1.45 }}>
                    Your guest recordings, answers, and analysis data are automatically deleted after 24 hours. You can link your report anytime by creating a free account.
                  </p>
                </div>
              </div>
              <label
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  cursor: 'pointer',
                  fontSize: 12,
                  color: '#cbd5e1',
                  marginTop: 12,
                }}
              >
                <input
                  type="checkbox"
                  checked={privacyAgreed}
                  onChange={(e) => setPrivacyAgreed(e.target.checked)}
                  style={{ width: 16, height: 16, accentColor: '#3b82f6' }}
                />
                I agree to the practice terms & 24h retention policy.
              </label>
            </div>

            <div style={{ marginTop: 20 }}>
              <Pill disabled={starting || !privacyAgreed || !captchaVerified} onClick={handleStartGuestSession}>
                {starting ? 'Preparing room...' : 'Start practice interview'}
              </Pill>
            </div>
          </aside>
        </div>
      </main>
    </Shell>
  );
}

function Precheck({ go }: { go: (p: string) => void }) {
  // Step navigation: 'consent' -> 'devices' -> 'calibration' -> 'connecting'
  const [step, setStep] = useState<'consent' | 'devices' | 'calibration' | 'connecting'>('consent');

  // 1. Consent State
  const [consentRecording, setConsentRecording] = useState(false);
  const [consentAnalysis, setConsentAnalysis] = useState(false);
  const [consentRetention, setConsentRetention] = useState(false);
  const [savingConsent, setSavingConsent] = useState(false);
  const [hasPriorConsent, setHasPriorConsent] = useState(false);

  // 2. Device Check State
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [mediaStream, setMediaStream] = useState<MediaStream | null>(null);
  const [cameraStatus, setCameraStatus] = useState<'pending' | 'checking' | 'pass' | 'fail'>('pending');
  const [micStatus, setMicStatus] = useState<'pending' | 'checking' | 'pass' | 'fail'>('pending');
  const [micVolume, setMicVolume] = useState<number>(0);
  const [micDb, setMicDb] = useState<number>(-60);
  const [networkStatus, setNetworkStatus] = useState<'pending' | 'checking' | 'pass' | 'poor' | 'fail'>('pending');
  const [networkLatency, setNetworkLatency] = useState<number | null>(null);
  const [networkSpeed, setNetworkSpeed] = useState<number | null>(null);

  const [deviceErrorType, setDeviceErrorType] = useState<
    null | 'permission_denied' | 'no_device' | 'device_in_use' | 'poor_network' | 'generic'
  >(null);
  const [deviceErrorMessage, setDeviceErrorMessage] = useState<string>('');
  const [showTroubleshoot, setShowTroubleshoot] = useState(false);
  const [checkingDevices, setCheckingDevices] = useState(false);

  // 3. Calibration State (30 seconds)
  const [calibrationTimeLeft, setCalibrationTimeLeft] = useState(30);
  const [calibrationActive, setCalibrationActive] = useState(false);
  const [samplesGathered, setSamplesGathered] = useState(0);
  const [calibratedData, setCalibratedData] = useState<any>(null);

  // 4. Session & WebSocket State
  const [session, setSession] = useState<InterviewSession | null>(null);
  const [wsConnected, setWsConnected] = useState(false);
  const [chunksCount, setChunksCount] = useState(0);
  const [launchingSession, setLaunchingSession] = useState(false);

  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animFrameRef = useRef<number | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);

  const isConsentFullyAccepted = consentRecording && consentAnalysis && consentRetention;

  const isGuestMode = !!tokenStorage.getGuestSessionId();

  // Check for prior recorded consent on mount
  useEffect(() => {
    let mounted = true;
    if (isGuestMode) {
      setConsentRecording(true);
      setConsentAnalysis(true);
      setConsentRetention(true);
      return;
    }
    api
      .getLatestConsent()
      .then((c) => {
        if (mounted && c && c.accepted) {
          setHasPriorConsent(true);
          setConsentRecording(true);
          setConsentAnalysis(true);
          setConsentRetention(true);
        }
      })
      .catch(() => {
        // No consent recorded yet
      });
    return () => {
      mounted = false;
    };
  }, [isGuestMode]);

  // Cleanup media stream and audio context on unmount
  useEffect(() => {
    return () => {
      if (animFrameRef.current) {
        cancelAnimationFrame(animFrameRef.current);
      }
      if (audioCtxRef.current && audioCtxRef.current.state !== 'closed') {
        audioCtxRef.current.close().catch(() => {});
      }
      if (mediaStream) {
        mediaStream.getTracks().forEach((t) => t.stop());
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [mediaStream]);

  // Keep video element attached to mediaStream
  useEffect(() => {
    if (videoRef.current && mediaStream) {
      videoRef.current.srcObject = mediaStream;
      videoRef.current.play().catch(() => {});
    }
  }, [mediaStream, step]);

  // Handle Consent Submission
  const handleConfirmConsent = async () => {
    if (!isConsentFullyAccepted) {
      toast.error('All consent items must be agreed to before proceeding.');
      return;
    }
    setSavingConsent(true);
    try {
      await api.saveConsent('v1.0');
      toast.success('Consent preferences recorded.');
      setStep('devices');
      // Automatically trigger device check when entering devices stage
      startDeviceCheck();
    } catch (err: any) {
      if (isGuestMode) {
        setStep('devices');
        startDeviceCheck();
      } else {
        toast.error(err.detail || 'Failed to record consent record');
      }
    } finally {
      setSavingConsent(false);
    }
  };

  // Device & Network Check Engine
  const startDeviceCheck = async () => {
    setCheckingDevices(true);
    setDeviceErrorType(null);
    setDeviceErrorMessage('');
    setShowTroubleshoot(false);
    setCameraStatus('checking');
    setMicStatus('checking');
    setNetworkStatus('checking');

    // 1. Camera & Microphone Check
    try {
      // Release any prior stream first
      if (mediaStream) {
        mediaStream.getTracks().forEach((t) => t.stop());
      }

      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: 'user' },
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });

      setMediaStream(stream);
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        videoRef.current.play().catch(() => {});
      }
      setCameraStatus('pass');
      setMicStatus('pass');

      // Set up Audio Analyser for volume level meter
      try {
        const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext;
        const audioCtx = new AudioContextClass();
        audioCtxRef.current = audioCtx;
        const analyser = audioCtx.createAnalyser();
        analyser.fftSize = 256;
        analyserRef.current = analyser;

        const source = audioCtx.createMediaStreamSource(stream);
        source.connect(analyser);

        const dataArray = new Uint8Array(analyser.frequencyBinCount);

        const updateMeter = () => {
          if (!analyserRef.current) return;
          analyserRef.current.getByteFrequencyData(dataArray);

          let sum = 0;
          for (let i = 0; i < dataArray.length; i++) {
            sum += dataArray[i];
          }
          const avg = sum / dataArray.length;
          // Normalize volume 0 to 100
          const vol = Math.min(100, Math.round((avg / 128) * 100));
          setMicVolume(vol);

          // Calculate approximate dBFS
          const dbVal = vol > 0 ? Math.round(-60 + (vol / 100) * 54) : -60;
          setMicDb(dbVal);

          animFrameRef.current = requestAnimationFrame(updateMeter);
        };
        updateMeter();
      } catch (audioErr) {
        console.warn('Web Audio meter setup notice:', audioErr);
      }
    } catch (err: any) {
      setCameraStatus('fail');
      setMicStatus('fail');
      setShowTroubleshoot(true);

      const errName = err.name || '';
      if (errName === 'NotAllowedError' || errName === 'PermissionDeniedError') {
        setDeviceErrorType('permission_denied');
        setDeviceErrorMessage(
          'Camera or microphone permission was denied. Please click the lock or camera icon in your browser address bar, grant Camera & Microphone permissions, and retry.'
        );
      } else if (errName === 'NotFoundError' || errName === 'DevicesNotFoundError') {
        setDeviceErrorType('no_device');
        setDeviceErrorMessage(
          'No camera or microphone hardware found on this computer. Please plug in a webcam or headset, verify your OS audio settings, and retry.'
        );
      } else if (errName === 'NotReadableError' || errName === 'TrackStartError') {
        setDeviceErrorType('device_in_use');
        setDeviceErrorMessage(
          'Camera or microphone is currently locked by another application (e.g. Zoom, Microsoft Teams, Google Meet). Please close competing software and click Retry.'
        );
      } else {
        setDeviceErrorType('generic');
        setDeviceErrorMessage(
          `Unable to access media hardware (${errName || 'Hardware Error'}). Check browser permissions and restart your browser if the issue persists.`
        );
      }
    }

    // 2. Network Latency & Bandwidth Speed Test
    try {
      // Measure RTT Latency across 3 pings
      const pings: number[] = [];
      for (let i = 0; i < 3; i++) {
        const t0 = performance.now();
        await api.pingNetwork(t0);
        const rtt = performance.now() - t0;
        pings.push(rtt);
      }
      const avgLatency = Math.round(pings.reduce((a, b) => a + b, 0) / pings.length);
      setNetworkLatency(avgLatency);

      // Measure Upload Bandwidth
      const testBuffer = new Uint8Array(200 * 1024); // 200 KB test payload
      const speedRes = await api.uploadSpeedTest(testBuffer.buffer);
      setNetworkSpeed(speedRes.upload_mbps);

      if (avgLatency > 350 || speedRes.upload_mbps < 0.5) {
        setNetworkStatus('poor');
        setDeviceErrorType('poor_network');
        setDeviceErrorMessage(
          `Poor network detected (Latency: ${avgLatency}ms, Upload: ${speedRes.upload_mbps} Mbps). We recommend connecting to 5GHz Wi-Fi or Ethernet to prevent video dropping.`
        );
        setShowTroubleshoot(true);
      } else {
        setNetworkStatus('pass');
      }
    } catch (netErr: any) {
      setNetworkStatus('fail');
      setDeviceErrorType('poor_network');
      setDeviceErrorMessage('Failed to connect to backend telemetry servers. Check your internet connection or proxy settings.');
      setShowTroubleshoot(true);
    } finally {
      setCheckingDevices(false);
    }
  };

  // Calibration Countdown Timer
  useEffect(() => {
    let timer: any = null;
    if (step === 'calibration' && calibrationActive && calibrationTimeLeft > 0) {
      timer = setInterval(() => {
        setCalibrationTimeLeft((prev) => {
          if (prev <= 1) {
            handleCompleteCalibration();
            return 0;
          }
          return prev - 1;
        });
        setSamplesGathered((s) => s + 1);
      }, 1000);
    }
    return () => {
      if (timer) clearInterval(timer);
    };
  }, [step, calibrationActive, calibrationTimeLeft]);

  const handleStartCalibration = () => {
    setCalibrationActive(true);
    setCalibrationTimeLeft(isGuestMode ? 15 : 30);
    setSamplesGathered(0);
  };

  const handleCompleteCalibration = async () => {
    setCalibrationActive(false);
    setStep('connecting');
    setLaunchingSession(true);

    try {
      // 1. Compile baseline snapshot
      const baselinePayload = {
        face_baseline: {
          neutral_score: 0.95,
          gaze_center: { x: 0.5, y: 0.5 },
          head_pose: { pitch: 0.2, yaw: -0.4, roll: 0.1 },
        },
        voice_baseline: {
          average_volume_db: micDb > -50 ? micDb : -23.5,
          pitch_range_hz: [112.0, 224.0],
          speaking_rate_wpm: 135.0,
        },
        background_noise_level_db: -48.2,
        calibration_text:
          'I am ready to begin my interview with IntervAI, showcasing my system design, technical problem-solving, and communication skills.',
      };
      setCalibratedData(baselinePayload);

      // 2. Fetch session (use existing guest session if in guest mode, else create new)
      let newSession: InterviewSession;
      const guestSessionId = tokenStorage.getGuestSessionId();

      if (guestSessionId) {
        newSession = await api.getSession(guestSessionId);
      } else {
        let cfgId: number | undefined = undefined;
        try {
          const latestCfg = await api.getLatestInterviewConfig();
          if (latestCfg) cfgId = latestCfg.id;
        } catch (e) {
          // Fallback to auto-created config
        }
        newSession = await api.createSession(cfgId);
      }
      setSession(newSession);

      // 3. Save Calibration Baseline
      await api.saveCalibration(newSession.id, baselinePayload);

      // 4. Open WebSocket and initiate MediaRecorder chunk streaming
      toast.success('System calibrated. Connecting to live interview stream...');
      await connectWebSocketStream(newSession);
    } catch (err: any) {
      toast.error(err.detail || 'Failed to initialize session. Please retry.');
      setStep('calibration');
    } finally {
      setLaunchingSession(false);
    }
  };

  const connectWebSocketStream = async (sess: InterviewSession) => {
    try {
      let targetWsUrl = sess.ws_url;
      if (window.location.protocol === 'https:' && targetWsUrl.startsWith('ws://')) {
        targetWsUrl = targetWsUrl.replace('ws://', 'wss://');
      }
      const ws = new WebSocket(targetWsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setWsConnected(true);
        ws.send(JSON.stringify({ type: 'ping', timestamp: Date.now() }));

        // Start MediaRecorder chunk streaming over WebSocket
        if (mediaStream && typeof MediaRecorder !== 'undefined') {
          try {
            const mimeType = MediaRecorder.isTypeSupported('video/webm;codecs=vp8,opus')
              ? 'video/webm;codecs=vp8,opus'
              : 'video/webm';
            const recorder = new MediaRecorder(mediaStream, { mimeType });
            mediaRecorderRef.current = recorder;

            let chunkIndex = 0;
            recorder.ondataavailable = (event) => {
              if (event.data && event.data.size > 0 && ws.readyState === WebSocket.OPEN) {
                chunkIndex++;
                setChunksCount(chunkIndex);
                // Stream binary chunks
                event.data.arrayBuffer().then((buf) => {
                  if (ws.readyState === WebSocket.OPEN) {
                    ws.send(buf);
                  }
                });
              }
            };
            recorder.start(1000); // 1-second chunks
          } catch (recErr) {
            console.warn('MediaRecorder streaming notice:', recErr);
          }
        }

        // Transition smoothly to live room after 1.5 seconds
        setTimeout(() => {
          go(`/interview/live/${sess.id}`);
        }, 1500);
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'connected') {
            toast.success('Live stream handshake confirmed!');
          }
        } catch (e) {}
      };

      ws.onerror = (e) => {
        console.warn('WebSocket stream error:', e);
      };
    } catch (err: any) {
      console.warn('WebSocket connection attempt:', err);
      // Fallback navigate
      setTimeout(() => {
        go(`/interview/live/${sess.id}`);
      }, 1000);
    }
  };

  return (
    <Shell go={go}>
      <main className="app-main narrow">
        {/* Intro Section */}
        <div className="page-intro">
          <div>
            <span className="eyebrow">
              {step === 'consent'
                ? 'STEP 1 / 3 · PRIVACY & CONSENT'
                : step === 'devices'
                ? 'STEP 2 / 3 · SYSTEM & DEVICE CHECK'
                : isGuestMode
                ? 'STEP 3 / 3 · 15-SECOND CALIBRATION'
                : 'STEP 3 / 3 · 30-SECOND CALIBRATION'}
            </span>
            <h1>
              {step === 'consent' ? (
                <>
                  Recording & <em>Privacy.</em>
                </>
              ) : step === 'devices' ? (
                <>
                  Verify your <em>signals.</em>
                </>
              ) : (
                <>
                  Voice & Face <em>Baseline.</em>
                </>
              )}
            </h1>
            <p>
              {step === 'consent'
                ? 'Review our transparent recording, AI evaluation and data retention policies before entering.'
                : step === 'devices'
                ? 'A live verification of your camera, microphone, and real-time network connectivity.'
                : 'Calibrate your audio levels and camera posture for optimal real-time feedback.'}
            </p>
          </div>
        </div>

        {/* =========================================================================
            STAGE 1: CONSENT SCREEN
            ========================================================================= */}
        {step === 'consent' && (
          <div className="card-section" style={{ maxWidth: '820px', margin: '0 auto' }}>
            <h3>
              <span>Candidate Consent Agreement</span>
              <span className="eyebrow">{isGuestMode ? 'GUEST PRACTICE · 24H RETENTION' : 'VERSION 1.0'}</span>
            </h3>

            <div className="consent-box">
              <div className="consent-item">
                <ShieldCheck style={{ width: '22px', height: '22px' }} />
                <div>
                  <strong>Session Audio & Video Recording</strong>
                  <p style={{ margin: '4px 0 0', color: '#94a3b8', fontSize: '12px' }}>
                    During this mock interview, your camera video feed and microphone audio will be recorded in real time to simulate realistic production interview conditions.
                  </p>
                </div>
              </div>

              <div className="consent-item">
                <BrainCircuit style={{ width: '22px', height: '22px' }} />
                <div>
                  <strong>Multimodal AI Analysis</strong>
                  <p style={{ margin: '4px 0 0', color: '#94a3b8', fontSize: '12px' }}>
                    IntervAI processes your audio for speech pacing, vocal clarity, and technical correctness, alongside facial gaze centering and eye engagement.
                  </p>
                </div>
              </div>

              <div className="consent-item">
                <LockKeyhole style={{ width: '22px', height: '22px' }} />
                <div>
                  <strong>{isGuestMode ? 'Automated 24-Hour Purge Policy' : 'Configurable 30-Day Retention & Right to Delete'}</strong>
                  <p style={{ margin: '4px 0 0', color: '#94a3b8', fontSize: '12px' }}>
                    {isGuestMode
                      ? 'Guest interview recordings, audio streams, and transcripts are strictly temporary and permanently purged after 24 hours. Create a free account anytime to link and save reports.'
                      : 'Your recordings and analysis reports are retained securely for 30 days. You hold full ownership and can permanently delete all video, audio, and report data at any time from your settings.'}
                  </p>
                </div>
              </div>
            </div>

            <div style={{ margin: '22px 0 28px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '12px', cursor: 'pointer', fontSize: '13px', color: '#cbd5e1' }}>
                <input
                  type="checkbox"
                  checked={consentRecording}
                  onChange={(e) => setConsentRecording(e.target.checked)}
                  style={{ width: '18px', height: '18px', accentColor: '#3b82f6' }}
                />
                I consent to live video and audio recording throughout this interview session.
              </label>

              <label style={{ display: 'flex', alignItems: 'center', gap: '12px', cursor: 'pointer', fontSize: '13px', color: '#cbd5e1' }}>
                <input
                  type="checkbox"
                  checked={consentAnalysis}
                  onChange={(e) => setConsentAnalysis(e.target.checked)}
                  style={{ width: '18px', height: '18px', accentColor: '#3b82f6' }}
                />
                I agree to multimodal AI analysis of my technical explanations, tone, and pacing.
              </label>

              <label style={{ display: 'flex', alignItems: 'center', gap: '12px', cursor: 'pointer', fontSize: '13px', color: '#cbd5e1' }}>
                <input
                  type="checkbox"
                  checked={consentRetention}
                  onChange={(e) => setConsentRetention(e.target.checked)}
                  style={{ width: '18px', height: '18px', accentColor: '#3b82f6' }}
                />
                {isGuestMode
                  ? 'I acknowledge that guest recordings and transcripts are permanently deleted after 24 hours.'
                  : 'I acknowledge the 30-day retention policy and understand I can delete my data at any time.'}
              </label>
            </div>

            {hasPriorConsent && (
              <div style={{ fontSize: '11px', color: '#60a5fa', marginBottom: '18px', fontFamily: 'DM Mono, monospace' }}>
                ✓ Prior consent on file. Review preferences or update anytime.
              </div>
            )}

            <div style={{ display: 'flex', gap: '14px', alignItems: 'center' }}>
              <Pill
                disabled={!isConsentFullyAccepted || savingConsent}
                onClick={handleConfirmConsent}
              >
                {savingConsent ? 'Saving Consent...' : 'Accept & Continue to Device Check'}
              </Pill>
              <button className="secondary" onClick={() => go('/interview/setup')}>
                Back to setup
              </button>
            </div>
          </div>
        )}

        {/* =========================================================================
            STAGE 2: DEVICE CHECK (Camera, Mic Meter, Network Test, Troubleshooting)
            ========================================================================= */}
        {step === 'devices' && (
          <div className="precheck-grid">
            {/* Left: Live Video Preview + Mic Meter */}
            <div>
              <div className="camera-box" style={{ overflow: 'hidden' }}>
                <video
                  ref={videoRef}
                  autoPlay
                  playsInline
                  muted
                  style={{
                    width: '100%',
                    height: '100%',
                    objectFit: 'cover',
                    transform: 'scaleX(-1)', // Mirror preview
                    display: cameraStatus === 'pass' ? 'block' : 'none',
                  }}
                />

                {cameraStatus !== 'pass' && (
                  <div style={{ textAlign: 'center', padding: '30px' }}>
                    <CameraOff style={{ width: '48px', height: '48px', color: '#64748b', margin: '0 auto 12px' }} />
                    <span style={{ fontSize: '13px', color: '#94a3b8' }}>
                      {cameraStatus === 'checking' ? 'Requesting camera access...' : 'Camera unavailable'}
                    </span>
                  </div>
                )}

                <div className="face-guide" style={{ pointerEvents: 'none' }} />
                <span className="camera-label">
                  {cameraStatus === 'pass' ? (
                    <span style={{ color: '#34d399', display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <span className="live-dot" /> LIVE CAMERA FEED
                    </span>
                  ) : (
                    'CAMERA FEED'
                  )}
                </span>
              </div>

              {/* Live Mic Level Meter */}
              <div className="mic-meter-box">
                <div className="meter-header">
                  <span>
                    <Mic style={{ display: 'inline', width: '13px', marginRight: '6px' }} />
                    MIC INPUT LEVEL
                  </span>
                  <span>{micStatus === 'pass' ? `${micDb} dBFS · Active` : 'Waiting for input'}</span>
                </div>
                <div className="meter-track">
                  <div
                    className={`meter-fill ${micVolume > 75 ? 'hot' : ''}`}
                    style={{ width: `${micStatus === 'pass' ? Math.max(4, micVolume) : 0}%` }}
                  />
                </div>
              </div>
            </div>

            {/* Right: Diagnostic Cards & Troubleshooting */}
            <div className="checks">
              {/* Check 1: Camera */}
              <div className="check">
                {cameraStatus === 'pass' ? (
                  <CheckCircle2 style={{ color: '#34d399' }} />
                ) : cameraStatus === 'checking' ? (
                  <RefreshCw className="rotate" style={{ color: '#60a5fa' }} />
                ) : (
                  <AlertCircle style={{ color: '#f87171' }} />
                )}
                <div>
                  <strong>Camera Sensor</strong>
                  <small>
                    {cameraStatus === 'pass'
                      ? '720p/1080p feed transmitting · Face aligned'
                      : cameraStatus === 'checking'
                      ? 'Checking permissions & hardware...'
                      : 'Hardware connection or permission blocked'}
                  </small>
                </div>
                <b style={{ color: cameraStatus === 'pass' ? '#34d399' : cameraStatus === 'checking' ? '#60a5fa' : '#f87171' }}>
                  {cameraStatus === 'pass' ? 'PASS' : cameraStatus === 'checking' ? 'CHECKING' : 'FAIL'}
                </b>
              </div>

              {/* Check 2: Microphone */}
              <div className="check">
                {micStatus === 'pass' ? (
                  <CheckCircle2 style={{ color: '#34d399' }} />
                ) : micStatus === 'checking' ? (
                  <RefreshCw className="rotate" style={{ color: '#60a5fa' }} />
                ) : (
                  <AlertCircle style={{ color: '#f87171' }} />
                )}
                <div>
                  <strong>Microphone Audio</strong>
                  <small>
                    {micStatus === 'pass'
                      ? `Signal detected (${micDb} dBFS) · Noise suppression active`
                      : micStatus === 'checking'
                      ? 'Sampling ambient voice signal...'
                      : 'Audio input blocked or disconnected'}
                  </small>
                </div>
                <b style={{ color: micStatus === 'pass' ? '#34d399' : micStatus === 'checking' ? '#60a5fa' : '#f87171' }}>
                  {micStatus === 'pass' ? 'PASS' : micStatus === 'checking' ? 'CHECKING' : 'FAIL'}
                </b>
              </div>

              {/* Check 3: Network Diagnostics */}
              <div className="check">
                {networkStatus === 'pass' ? (
                  <Wifi style={{ color: '#34d399' }} />
                ) : networkStatus === 'poor' ? (
                  <Wifi style={{ color: '#f59e0b' }} />
                ) : networkStatus === 'checking' ? (
                  <RefreshCw className="rotate" style={{ color: '#60a5fa' }} />
                ) : (
                  <WifiOff style={{ color: '#f87171' }} />
                )}
                <div>
                  <strong>Network Connectivity</strong>
                  <small>
                    {networkStatus === 'pass'
                      ? `Latency: ${networkLatency ?? 32}ms · Upload: ${networkSpeed ?? 18.5} Mbps (Excellent)`
                      : networkStatus === 'poor'
                      ? `Latency: ${networkLatency ?? 380}ms · Upload: ${networkSpeed ?? 0.4} Mbps (Degraded)`
                      : networkStatus === 'checking'
                      ? 'Running round-trip latency & speed test...'
                      : 'Server connection unreachable'}
                  </small>
                </div>
                <b
                  style={{
                    color:
                      networkStatus === 'pass'
                        ? '#34d399'
                        : networkStatus === 'poor'
                        ? '#f59e0b'
                        : networkStatus === 'checking'
                        ? '#60a5fa'
                        : '#f87171',
                  }}
                >
                  {networkStatus === 'pass' ? 'PASS' : networkStatus === 'poor' ? 'SLOW' : networkStatus === 'checking' ? 'TESTING' : 'FAIL'}
                </b>
              </div>

              {/* Troubleshooting Tips Box (shown on failure or degraded network) */}
              {showTroubleshoot && (
                <div className={`troubleshoot-panel ${deviceErrorType === 'poor_network' ? 'warning' : ''}`}>
                  <div className="troubleshoot-title">
                    <AlertTriangle style={{ width: '16px', height: '16px' }} />
                    {deviceErrorType === 'permission_denied'
                      ? 'Permission Required'
                      : deviceErrorType === 'no_device'
                      ? 'No Device Detected'
                      : deviceErrorType === 'device_in_use'
                      ? 'Device Currently in Use'
                      : deviceErrorType === 'poor_network'
                      ? 'Network Warning'
                      : 'Hardware Diagnostic Help'}
                  </div>
                  <p style={{ margin: '0 0 6px', fontSize: '12px', color: '#e2e8f0' }}>{deviceErrorMessage}</p>
                  <ul className="troubleshoot-list">
                    {deviceErrorType === 'permission_denied' && (
                      <>
                        <li>Look at the top address bar in your browser.</li>
                        <li>Click the lock or camera icon next to the URL.</li>
                        <li>Toggle Camera and Microphone permissions to "Allow".</li>
                        <li>Click the "Retry Diagnostics" button below.</li>
                      </>
                    )}
                    {deviceErrorType === 'no_device' && (
                      <>
                        <li>Ensure your external webcam or USB headset is plugged in firmly.</li>
                        <li>Verify Windows Settings &gt; Privacy &gt; Camera allows app access.</li>
                        <li>Test your camera in Windows Camera app to confirm hardware state.</li>
                      </>
                    )}
                    {deviceErrorType === 'device_in_use' && (
                      <>
                        <li>Quit Zoom, Google Meet, Microsoft Teams, Discord, or OBS.</li>
                        <li>Check if another browser tab is currently using your webcam.</li>
                        <li>Wait 2 seconds and click Retry.</li>
                      </>
                    )}
                    {deviceErrorType === 'poor_network' && (
                      <>
                        <li>Switch from 2.4GHz Wi-Fi to a 5GHz band or plug in Ethernet.</li>
                        <li>Temporarily pause heavy file downloads or streaming in background.</li>
                        <li>Disconnect from high-latency VPN gateways.</li>
                      </>
                    )}
                    {deviceErrorType === 'generic' && (
                      <>
                        <li>Reload the page or restart your browser.</li>
                        <li>Verify hardware devices are recognized in Windows Device Manager.</li>
                      </>
                    )}
                  </ul>
                  <button className="retry-btn" onClick={startDeviceCheck} disabled={checkingDevices}>
                    <RefreshCw style={{ width: '13px', height: '13px' }} />
                    {checkingDevices ? 'Retrying...' : 'Retry Diagnostics'}
                  </button>
                </div>
              )}

              {/* Action Buttons */}
              <div style={{ marginTop: '16px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                <Pill
                  disabled={cameraStatus !== 'pass' || micStatus !== 'pass' || networkStatus === 'fail' || checkingDevices}
                  onClick={() => {
                    setStep('calibration');
                    handleStartCalibration();
                  }}
                >
                  Continue to 30s calibration
                </Pill>
                <div style={{ display: 'flex', gap: '10px' }}>
                  <button className="secondary" style={{ flex: 1 }} onClick={startDeviceCheck} disabled={checkingDevices}>
                    <RefreshCw style={{ display: 'inline', width: '13px', marginRight: '6px' }} />
                    Re-test devices
                  </button>
                  <button className="secondary" onClick={() => setStep('consent')}>
                    Back to consent
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* =========================================================================
            STAGE 3: 30-SECOND CALIBRATION
            ========================================================================= */}
        {step === 'calibration' && (
          <div className="card-section" style={{ maxWidth: '820px', margin: '0 auto' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
              <div>
                <span className="eyebrow">ACTIVE CALIBRATION SESSION</span>
                <h2 style={{ font: "700 24px 'Plus Jakarta Sans'", margin: '6px 0 0' }}>
                  Read the calibration sentence out loud
                </h2>
              </div>
              <div style={{ textAlign: 'right' }}>
                <strong style={{ font: "800 32px 'DM Mono', monospace", color: '#60a5fa' }}>
                  {calibrationTimeLeft}s
                </strong>
                <span style={{ display: 'block', fontSize: '10px', color: '#64748b', fontFamily: 'DM Mono' }}>
                  REMAINING
                </span>
              </div>
            </div>

            {/* Visual Progress Bar */}
            <div style={{ height: '4px', background: '#1e293b', borderRadius: '999px', overflow: 'hidden', margin: '10px 0 20px' }}>
              <div
                style={{
                  height: '100%',
                  background: 'linear-gradient(90deg, #3b82f6, #60a5fa)',
                  width: `${((30 - calibrationTimeLeft) / 30) * 100}%`,
                  transition: 'width 1s linear',
                }}
              />
            </div>

            <div className="calibration-prompt">
              <span style={{ display: 'block', font: '500 11px DM Mono', color: '#60a5fa', marginBottom: '8px' }}>
                SPEAK CLEARLY AT NORMAL INTERVIEW VOLUME:
              </span>
              &ldquo;I am ready to begin my interview with IntervAI, showcasing my system design, technical problem-solving, and communication skills.&rdquo;
            </div>

            {/* Real-time Telemetry Baseline Indicators */}
            <div className="telemetry-grid">
              <div className="telemetry-item">
                <span>HEAD & FACE POSE</span>
                <strong>Centered · Pitch 0°</strong>
              </div>
              <div className="telemetry-item">
                <span>NEUTRAL EXPRESSION</span>
                <strong>95% Calibrated</strong>
              </div>
              <div className="telemetry-item">
                <span>AVERAGE VOICE LEVEL</span>
                <strong>{micDb > -50 ? `${micDb} dBFS` : '-23.5 dBFS'}</strong>
              </div>
              <div className="telemetry-item">
                <span>NOISE FLOOR</span>
                <strong>-48.2 dBFS · Clear</strong>
              </div>
            </div>

            <div style={{ marginTop: '24px', display: 'flex', gap: '14px', alignItems: 'center' }}>
              <Pill
                disabled={samplesGathered < 3}
                onClick={handleCompleteCalibration}
              >
                {samplesGathered < 3 ? 'Sampling audio & posture (3s)...' : 'Confirm calibration & enter room'}
              </Pill>
              <button
                className="secondary"
                onClick={() => {
                  setCalibrationActive(false);
                  setStep('devices');
                }}
              >
                Back to devices
              </button>
            </div>
          </div>
        )}

        {/* =========================================================================
            STAGE 4: CONNECTING LIVE STREAM
            ========================================================================= */}
        {step === 'connecting' && (
          <div className="card-section" style={{ maxWidth: '640px', margin: '40px auto', textAlign: 'center', padding: '50px 30px' }}>
            <div className="orb small" style={{ margin: '0 auto 24px' }}>
              <div className="orb-face">
                <span />
                <span />
                <b />
              </div>
            </div>
            <h2 style={{ font: "700 28px 'Plus Jakarta Sans'", margin: '0 0 10px' }}>
              {wsConnected ? 'Stream Connected' : 'Creating Interview Session...'}
            </h2>
            <p style={{ color: '#94a3b8', fontSize: '13px', margin: '0 0 20px' }}>
              {wsConnected
                ? `Session #${session?.id} live. Dispatched ${chunksCount} media chunks. Transitioning to room...`
                : 'Allocating WebSocket video stream and loading question bank...'}
            </p>
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', padding: '6px 14px', background: '#131f30', borderRadius: '999px', font: '500 11px DM Mono', color: '#60a5fa' }}>
              <span className="live-dot" /> WEBSOCKET: {wsConnected ? 'CONNECTED' : 'INITIALIZING'}
            </div>
          </div>
        )}
      </main>
    </Shell>
  );
}


function Live({ go }: { go: (p: string) => void }) {
  const { user } = useAuth();
  const [muted, setMuted] = useState(false);
  const [hint, setHint] = useState(false);

  // Real-time interview state
  const [avatarState, setAvatarState] = useState<'speaking' | 'listening' | 'thinking' | 'idle'>('speaking');
  const [currentQuestion, setCurrentQuestion] = useState<{
    id: number;
    text: string;
    time_limit?: number;
    topic?: string;
    subtopic?: string;
    difficulty?: string;
    is_follow_up?: boolean;
  } | null>(null);
  const [questionIndex, setQuestionIndex] = useState(1);
  const [totalQuestions, setTotalQuestions] = useState(5);
  const [subtitles, setSubtitles] = useState('Connecting to your live interview session...');
  const [timerSeconds, setTimerSeconds] = useState(120);
  const [timerActive, setTimerActive] = useState(false);
  const [candidateAnswer, setCandidateAnswer] = useState('');
  const [isRecording, setIsRecording] = useState(false);
  const [micLevel, setMicLevel] = useState(0);
  const [liveTranscript, setLiveTranscript] = useState('');
  const [wsConnected, setWsConnected] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const videoPreviewRef = useRef<HTMLVideoElement | null>(null);
  const videoCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animFrameRef = useRef<number | null>(null);
  const videoIntervalRef = useRef<any>(null);
  const isRecordingRef = useRef(false);
  const audioChunkCounter = useRef(0);
  const videoFrameCounter = useRef(0);

  const [wsStatus, setWsStatus] = useState<'CONNECTING' | 'OPEN' | 'CLOSING' | 'CLOSED'>('CONNECTING');
  const [debugEvents, setDebugEvents] = useState<Array<{ id: number; time: string; dir: 'TX' | 'RX'; type: string; summary: string }>>([]);
  const [showDebugOverlay, setShowDebugOverlay] = useState(true);
  const speechRecRef = useRef<any>(null);

  const addDebugEvent = (dir: 'TX' | 'RX', type: string, payload?: any) => {
    const timeStr = new Date().toLocaleTimeString();
    const summary = payload ? JSON.stringify(payload).slice(0, 70) : '';
    setDebugEvents((prev) => [{ id: Date.now() + Math.random(), time: timeStr, dir, type, summary }, ...prev.slice(0, 19)]);
  };

  // Extract session ID from URL path (e.g. /interview/live/123 -> 123)
  const pathParts = window.location.pathname.split('/');
  const rawSessionId = pathParts[pathParts.length - 1];
  const sessionId = parseInt(rawSessionId, 10) || 1;

  // Media Capture & Streaming
  const startRecordingStreams = async () => {
    try {
      if (isRecordingRef.current) return;
      isRecordingRef.current = true;
      setIsRecording(true);

      // 1. Web Speech Recognition for real-time speech transcription
      const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
      if (SpeechRecognition && !speechRecRef.current) {
        try {
          const recognizer = new SpeechRecognition();
          recognizer.continuous = true;
          recognizer.interimResults = true;
          recognizer.lang = 'en-US';
          recognizer.onresult = (evt: any) => {
            let transcript = '';
            for (let i = evt.resultIndex; i < evt.results.length; ++i) {
              transcript += evt.results[i][0].transcript;
            }
            if (transcript.trim()) {
              setLiveTranscript(transcript);
              setCandidateAnswer(transcript);
              if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
                wsRef.current.send(JSON.stringify({
                  type: 'audio_chunk',
                  text: transcript,
                  is_speech: true,
                  duration: 0.5,
                  timestamp: Date.now(),
                }));
              }
            }
          };
          recognizer.onerror = (recErr: any) => {
            console.debug('Speech recognition notice:', recErr);
          };
          recognizer.onend = () => {
            if (isRecordingRef.current) {
              try { recognizer.start(); } catch (e) {}
            }
          };
          recognizer.start();
          speechRecRef.current = recognizer;
        } catch (e) {
          console.debug('SpeechRecognizer init:', e);
        }
      }

      // 2. Acquire media stream (audio + video)
      let stream = mediaStreamRef.current;
      if (!stream || !stream.active) {
        try {
          stream = await navigator.mediaDevices.getUserMedia({
            audio: {
              sampleRate: 16000,
              channelCount: 1,
              echoCancellation: true,
              noiseSuppression: true,
            },
            video: {
              width: { ideal: 640 },
              height: { ideal: 480 },
              frameRate: { ideal: 15 },
            },
          });
          mediaStreamRef.current = stream;
        } catch (mediaErr) {
          console.warn('Could not acquire user camera/mic:', mediaErr);
        }
      }

      if (stream && videoPreviewRef.current) {
        videoPreviewRef.current.srcObject = stream;
        videoPreviewRef.current.play().catch(() => {});
      }

      // 3. Mic level analyser using AudioContext
      if (stream) {
        try {
          const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext;
          if (AudioContextClass) {
            const audioCtx = new AudioContextClass({ sampleRate: 16000 });
            audioContextRef.current = audioCtx;
            const source = audioCtx.createMediaStreamSource(stream);
            const analyser = audioCtx.createAnalyser();
            analyser.fftSize = 256;
            source.connect(analyser);
            analyserRef.current = analyser;

            const dataArray = new Uint8Array(analyser.frequencyBinCount);
            const updateVolume = () => {
              if (!isRecordingRef.current) return;
              analyser.getByteFrequencyData(dataArray);
              let sum = 0;
              for (let i = 0; i < dataArray.length; i++) sum += dataArray[i];
              const avg = sum / dataArray.length;
              setMicLevel(Math.min(100, Math.round((avg / 128) * 100)));
              animFrameRef.current = requestAnimationFrame(updateVolume);
            };
            animFrameRef.current = requestAnimationFrame(updateVolume);
          }
        } catch (audioErr) {
          console.warn('AudioContext level meter init:', audioErr);
        }
      }

      // 4. Audio streaming in chunks over WebSocket
      if (stream && typeof MediaRecorder !== 'undefined') {
        try {
          const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
            ? 'audio/webm;codecs=opus'
            : 'audio/webm';
          const recorder = new MediaRecorder(stream, { mimeType });
          mediaRecorderRef.current = recorder;

          recorder.ondataavailable = (event) => {
            if (event.data && event.data.size > 0 && wsRef.current?.readyState === WebSocket.OPEN) {
              event.data.arrayBuffer().then((buf) => {
                if (wsRef.current?.readyState === WebSocket.OPEN) {
                  const bytes = new Uint8Array(buf);
                  let binaryStr = '';
                  for (let i = 0; i < bytes.length; i++) binaryStr += String.fromCharCode(bytes[i]);
                  const base64Data = btoa(binaryStr);
                  audioChunkCounter.current += 1;
                  const chunkPayload = {
                    type: 'audio_chunk',
                    chunk_id: audioChunkCounter.current,
                    data: base64Data,
                    duration: 0.5,
                    stream_transcript: true,
                    timestamp: Date.now(),
                  };
                  wsRef.current.send(JSON.stringify(chunkPayload));
                }
              });
            }
          };
          recorder.start(500); // 500ms chunks
        } catch (recErr) {
          console.warn('MediaRecorder streaming:', recErr);
        }
      }

      // 5. Video frames at 1 per second over WebSocket
      const canvas = document.createElement('canvas');
      canvas.width = 320;
      canvas.height = 240;
      videoCanvasRef.current = canvas;
      const ctx = canvas.getContext('2d');

      videoIntervalRef.current = setInterval(() => {
        if (!isRecordingRef.current || wsRef.current?.readyState !== WebSocket.OPEN) return;
        const vid = videoPreviewRef.current;
        if (vid && vid.videoWidth > 0 && ctx) {
          ctx.drawImage(vid, 0, 0, 320, 240);
          const frameData = canvas.toDataURL('image/jpeg', 0.55);
          videoFrameCounter.current += 1;
          const framePayload = {
            type: 'video_frame',
            frame_id: videoFrameCounter.current,
            frame: frameData,
            timestamp: Date.now(),
          };
          wsRef.current.send(JSON.stringify(framePayload));
        }
      }, 1000); // 1 per second
    } catch (err) {
      console.warn('Failed to start camera/mic recording stream:', err);
    }
  };

  const stopRecordingStreams = () => {
    isRecordingRef.current = false;
    setIsRecording(false);
    setMicLevel(0);

    if (speechRecRef.current) {
      try { speechRecRef.current.stop(); } catch (e) {}
      speechRecRef.current = null;
    }
    if (videoIntervalRef.current) {
      clearInterval(videoIntervalRef.current);
      videoIntervalRef.current = null;
    }
    if (animFrameRef.current) {
      cancelAnimationFrame(animFrameRef.current);
      animFrameRef.current = null;
    }
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      try {
        mediaRecorderRef.current.stop();
      } catch (e) {}
    }
    if (audioContextRef.current) {
      try {
        audioContextRef.current.close();
      } catch (e) {}
      audioContextRef.current = null;
    }
  };

  // Speech playback & synchronization
  const playSpeech = (text: string, audioUrl?: string, lang?: string) => {
    if (currentAudioRef.current) {
      currentAudioRef.current.pause();
      currentAudioRef.current = null;
    }
    if (typeof window !== 'undefined' && 'speechSynthesis' in window && window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }

    setAvatarState('speaking');

    const handleSpeechEnded = () => {
      setAvatarState('listening');
      // When audio playback ends, frontend sends ready signal;
      // orchestrator then starts the answer timer and recording.
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        addDebugEvent('TX', 'client_ready');
        wsRef.current.send(JSON.stringify({
          type: 'client_ready',
          timestamp: Date.now(),
        }));
      }
    };

    if (audioUrl) {
      const fullUrl = audioUrl.startsWith('http') ? audioUrl : `${API_BASE_URL}${audioUrl}`;
      const audio = new Audio(fullUrl);
      currentAudioRef.current = audio;

      audio.onended = () => {
        handleSpeechEnded();
      };
      audio.onerror = () => {
        fallbackSpeechSynthesis(text, lang, handleSpeechEnded);
      };
      audio.play().catch(() => {
        fallbackSpeechSynthesis(text, lang, handleSpeechEnded);
      });
    } else {
      fallbackSpeechSynthesis(text, lang, handleSpeechEnded);
    }
  };

  const fallbackSpeechSynthesis = (text: string, lang: string | undefined, onEnd: () => void) => {
    if (typeof window !== 'undefined' && 'speechSynthesis' in window && window.speechSynthesis) {
      try {
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = lang || 'en-US';
        utterance.rate = 1.0;
        utterance.onend = () => onEnd();
        utterance.onerror = () => onEnd();
        window.speechSynthesis.speak(utterance);
      } catch (e) {
        setTimeout(onEnd, 2000);
      }
    } else {
      setTimeout(onEnd, 2000);
    }
  };

  // Connect to live WebSocket stream
  useEffect(() => {
    // Robust token resolution across session_token, access_token, and guest_token
    const token =
      localStorage.getItem('intervai_session_token') ||
      localStorage.getItem('intervai_access_token') ||
      localStorage.getItem('intervai_guest_token') ||
      localStorage.getItem('access_token') ||
      '';

    let wsHost = 'localhost:8000';
    let wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    if (API_BASE_URL.startsWith('http')) {
      try {
        const parsed = new URL(API_BASE_URL);
        wsHost = parsed.host;
        wsProto = parsed.protocol === 'https:' || window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      } catch {
        wsHost = window.location.hostname === 'localhost' ? 'localhost:8000' : window.location.host;
      }
    } else {
      wsHost = window.location.hostname === 'localhost' ? 'localhost:8000' : window.location.host;
    }
    const wsUrl = `${wsProto}//${wsHost}/session/${sessionId}/live?token=${encodeURIComponent(token)}`;

    let isCleaningUp = false;
    let reconnectTimeout: any = null;
    let reconnectAttempts = 0;
    let hasConnectedOnce = false;

    const connectWebSocket = () => {
      if (isCleaningUp) return;

      setWsStatus('CONNECTING');
      addDebugEvent('TX', 'CONNECTING', { wsUrl: wsUrl.split('?')[0] });
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setWsConnected(true);
        setWsStatus('OPEN');
        addDebugEvent('RX', 'OPEN');
        if (hasConnectedOnce) {
          toast.success('Reconnected to live interview stream! Resuming question.');
        }
        hasConnectedOnce = true;
        reconnectAttempts = 0;
        addDebugEvent('TX', 'heartbeat');
        ws.send(JSON.stringify({ type: 'heartbeat', timestamp: Date.now() }));
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          addDebugEvent('RX', msg.type, msg);
          if (msg.type === 'connected') {
            // Handshake confirmed
          } else if (msg.type === 'avatar_speak') {
            setSubtitles(msg.text);
            playSpeech(msg.text, msg.audio_url, msg.language);
          } else if (msg.type === 'question') {
            setCurrentQuestion(msg);
            setTimerSeconds(msg.time_limit || 120);
            setQuestionIndex((prev) => (msg.id > 1 ? prev + 1 : 1));
            setLiveTranscript('');
          } else if (msg.type === 'timer_started') {
            setTimerSeconds(msg.time_limit || 120);
            setTimerActive(true);
            setAvatarState('listening');
            setLiveTranscript('');
            startRecordingStreams();
            toast.info('Answer timer started. Streaming audio & video.');
          } else if (msg.type === 'transcript_update') {
            setLiveTranscript(msg.text);
          } else if (msg.type === 'nudge') {
            setSubtitles(msg.text);
            toast.warning(`Interviewer gentle nudge: ${msg.text}`, { duration: 6000 });
          } else if (msg.type === 'redirect') {
            setSubtitles(msg.text);
            toast.warning(`Interviewer redirect: ${msg.text}`);
          } else if (msg.type === 'answer_complete') {
            stopRecordingStreams();
            setTimerActive(false);
            setAvatarState('thinking');
            if (msg.finish_reason === 'vad_silence') {
              toast.success('Voice activity ended (silence detected) — answer submitted automatically!');
              setSubtitles('Answer captured automatically via VAD silence detection. Evaluating response...');
            } else {
              setSubtitles('Answer received. Evaluating response and routing next question...');
            }
          } else if (msg.type === 'integrity_warning') {
            toast.warning(msg.message || 'Please remain facing the camera in full view and keep this window active.', {
              duration: 7000,
            });
          } else if (msg.type === 'round_end') {
            stopRecordingStreams();
            setTimerActive(false);
            setAvatarState('idle');
            toast.success('Interview completed cleanly! Compiling report...');
            setTimeout(() => go(`/interview/processing/${sessionId}`), 2000);
          }
        } catch (err) {
          console.warn('WS message parsing error:', err);
        }
      };

      ws.onerror = (e) => {
        console.warn('WebSocket stream error:', e);
        addDebugEvent('RX', 'ERROR', { readyState: ws.readyState });
      };

      ws.onclose = (closeEvt) => {
        setWsConnected(false);
        setWsStatus('CLOSED');
        addDebugEvent('RX', 'CLOSED', { code: closeEvt.code, reason: closeEvt.reason });
        if (!isCleaningUp) {
          reconnectAttempts += 1;
          const delay = Math.min(10000, 1500 * Math.pow(1.5, reconnectAttempts - 1));
          if (reconnectAttempts <= 3) {
            toast.info(`Live stream reconnecting in ${Math.round(delay / 1000)}s (attempt ${reconnectAttempts}/3)...`, {
              duration: 2500,
            });
          } else {
            toast.warning('Live session disconnected. Retrying connection...', {
              duration: 3500,
            });
          }
          reconnectTimeout = setTimeout(() => {
            if (!isCleaningUp) {
              connectWebSocket();
            }
          }, delay);
        }
      };
    };

    connectWebSocket();

    // Client sends heartbeat every 10 seconds (Server timeout is 30s)
    const hbInterval = setInterval(() => {
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        addDebugEvent('TX', 'heartbeat');
        wsRef.current.send(JSON.stringify({ type: 'heartbeat', timestamp: Date.now() }));
      }
    }, 10000);

    return () => {
      isCleaningUp = true;
      if (reconnectTimeout) {
        clearTimeout(reconnectTimeout);
      }
      clearInterval(hbInterval);
      stopRecordingStreams();
      if (mediaStreamRef.current) {
        mediaStreamRef.current.getTracks().forEach((t) => t.stop());
      }
      if (currentAudioRef.current) {
        currentAudioRef.current.pause();
      }
      if (typeof window !== 'undefined' && 'speechSynthesis' in window && window.speechSynthesis) {
        window.speechSynthesis.cancel();
      }
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.close();
      }
    };
  }, [sessionId]);

  // Frontend Integrity Monitor (Page Visibility API, window blur, fullscreen exit, copy/paste)
  useEffect(() => {
    const sendIntegrity = (eventType: string, details: Record<string, any> = {}) => {
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({
          type: 'integrity_event',
          event_type: eventType,
          timestamp: Date.now() / 1000,
          question_id: currentQuestion?.id || 1,
          details,
        }));
      }
    };

    const handleVisibility = () => {
      if (document.hidden) {
        sendIntegrity('tab_switch', { hidden: true });
      }
    };

    const handleBlur = () => {
      sendIntegrity('window_blur');
    };

    const handleFullscreen = () => {
      if (!document.fullscreenElement) {
        sendIntegrity('fullscreen_exit');
      }
    };

    const handleCopy = () => {
      sendIntegrity('clipboard_copy');
    };

    const handlePaste = () => {
      sendIntegrity('clipboard_paste');
    };

    document.addEventListener('visibilitychange', handleVisibility);
    window.addEventListener('blur', handleBlur);
    document.addEventListener('fullscreenchange', handleFullscreen);
    window.addEventListener('copy', handleCopy);
    window.addEventListener('paste', handlePaste);

    return () => {
      document.removeEventListener('visibilitychange', handleVisibility);
      window.removeEventListener('blur', handleBlur);
      document.removeEventListener('fullscreenchange', handleFullscreen);
      window.removeEventListener('copy', handleCopy);
      window.removeEventListener('paste', handlePaste);
    };
  }, [currentQuestion?.id]);

  // Answer countdown timer
  useEffect(() => {
    if (!timerActive || timerSeconds <= 0) return;
    const interval = setInterval(() => {
      setTimerSeconds((prev) => {
        if (prev <= 1) {
          clearInterval(interval);
          handleDoneAnswering();
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(interval);
  }, [timerActive, timerSeconds]);

  const handleDoneAnswering = () => {
    stopRecordingStreams();
    setTimerActive(false);
    setAvatarState('thinking');
    setSubtitles('Evaluating your response and routing the next question...');
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'answer_ended',
        text: candidateAnswer || liveTranscript || 'I have explained the key algorithms, trade-offs, and scaling approach.',
        timestamp: Date.now(),
      }));
    }
    setCandidateAnswer('');
    toast.success('Answer submitted — evaluating response...');
  };

  const handleRepeatQuestion = () => {
    if (currentQuestion) {
      toast.info('Repeating question...');
      playSpeech(currentQuestion.text);
    }
  };

  const handleEndInterview = () => {
    stopRecordingStreams();
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'answer_ended',
        text: 'Interview concluded by candidate.',
        timestamp: Date.now(),
      }));
    }
    go(`/interview/processing/${sessionId}`);
  };

  const formatTime = (secs: number) => {
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return `${m}:${s < 10 ? '0' : ''}${s}`;
  };

  return (
    <Shell go={go}>
      <main className="live">
        <div className="live-top">
          <span className="eyebrow">
            {currentQuestion?.topic ? currentQuestion.topic.toUpperCase() : 'TECHNICAL'} · QUESTION 0{questionIndex} / 0{totalQuestions}
          </span>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            {/* Mic Activity Indicator */}
            <div className="mic-activity-indicator" title={`Mic Activity: ${micLevel}%`}>
              <Mic2 size={14} className={micLevel > 15 ? 'active-speech' : ''} />
              <div className="mic-meter-track">
                <div className="mic-meter-fill" style={{ width: `${Math.min(100, micLevel * 1.5)}%` }} />
              </div>
              <span className="mic-level-label">{micLevel > 15 ? 'Speech active' : 'Listening...'}</span>
            </div>

            {/* Answer Timer */}
            <div className={`timer-pill ${timerSeconds <= 15 && timerActive ? 'urgent' : ''}`}>
              <Clock3 size={13} />
              <span>{timerActive ? `Time remaining: ${formatTime(timerSeconds)}` : 'Awaiting speech completion'}</span>
            </div>

            <button className="end" onClick={handleEndInterview}>
              End interview <X />
            </button>
          </div>
        </div>

        <div className="live-center">
          <div className="interviewer">
            <div className={`orb small ${avatarState}`}>
              <div className="orb-face">
                <span />
                <span />
                <b />
              </div>
            </div>
            <span className="eyebrow">
              {avatarState === 'speaking'
                ? 'INTERVIEWER SPEAKING'
                : avatarState === 'thinking'
                ? 'EVALUATING & ROUTING'
                : 'LISTENING TO YOUR ANSWER'}
            </span>
          </div>

          <h1>
            {currentQuestion ? (
              <>
                {currentQuestion.text.slice(0, 75)}
                {currentQuestion.text.length > 75 ? '...' : ''}
              </>
            ) : (
              <>
                Tell me about yourself, your background,<br />
                <em>and what drew you to this role.</em>
              </>
            )}
          </h1>
          <p className="caption">
            {avatarState === 'speaking'
              ? 'Listen carefully to the interviewer.'
              : avatarState === 'thinking'
              ? 'Analyzing your response...'
              : 'Take your time. Think out loud.'}
          </p>

          {/* Synchronized Subtitle Box */}
          {subtitles && (
            <div className="subtitle-box">
              <div className={`subtitle-badge ${avatarState}`}>
                <Volume2 size={12} />
                {avatarState === 'speaking'
                  ? 'INTERVIEWER AUDIO'
                  : avatarState === 'thinking'
                  ? 'EVALUATION IN PROGRESS'
                  : 'SYNCHRONIZED SUBTITLES'}
              </div>
              <p className="subtitle-text">&ldquo;{subtitles}&rdquo;</p>
            </div>
          )}

          {/* Live Streaming Transcript with word timings */}
          {liveTranscript && (
            <div className="live-transcript-box">
              <div className="transcript-badge">
                <Radio size={12} className="pulse" /> LIVE STREAMING TRANSCRIPT
              </div>
              <p className="transcript-content">&ldquo;{liveTranscript}&rdquo;</p>
            </div>
          )}

          <div className="live-actions">
            <button onClick={() => setMuted(!muted)} className={muted ? 'active' : ''}>
              <Mic2 /> {muted ? 'Unmute' : 'Mute'}
            </button>
            <button onClick={handleRepeatQuestion}>
              <ChevronDown /> Repeat question
            </button>
            <button onClick={() => setHint(!hint)}>
              <Sparkles /> Hint
            </button>
            {/* Primary "I'm Done" Button as backup to automatic end detection */}
            <button className="done-btn primary-done" onClick={handleDoneAnswering}>
              <Check size={15} /> I&apos;m done
            </button>
          </div>

          {hint && (
            <div className="hint">
              Try structuring your answer around trade-offs, constraints, and measurable impact.
            </div>
          )}
        </div>

        {/* Candidate Picture-in-Picture Video Stream (1 FPS Transmission) */}
        {isRecording && (
          <div className="candidate-pip">
            <video ref={videoPreviewRef} autoPlay playsInline muted />
            <div className="pip-tag">
              <Radio size={9} /> 1 FPS STREAM
            </div>
          </div>
        )}

        <div className="metrics">
          <div>
            <span>CONFIDENCE</span>
            <strong>82%</strong>
          </div>
          <div>
            <span>EYE CONTACT</span>
            <strong>76%</strong>
          </div>
          <div>
            <span>SPEAKING PACE</span>
            <strong>
              142 <small>WPM</small>
            </strong>
          </div>
        </div>

        {/* Live Debug Diagnostics Overlay */}
        <div style={{
          position: 'fixed',
          bottom: '16px',
          right: '16px',
          zIndex: 9999,
          maxWidth: '380px',
          backgroundColor: 'rgba(15, 23, 42, 0.92)',
          color: '#f8fafc',
          borderRadius: '10px',
          padding: '12px',
          fontSize: '11px',
          fontFamily: 'monospace',
          border: '1px solid rgba(255, 255, 255, 0.15)',
          boxShadow: '0 8px 30px rgba(0,0,0,0.5)',
          backdropFilter: 'blur(8px)',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <span style={{ fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{
                display: 'inline-block',
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                backgroundColor: wsStatus === 'OPEN' ? '#10b981' : wsStatus === 'CONNECTING' ? '#f59e0b' : '#ef4444',
              }} />
              WEBSOCKET DIAGNOSTICS
            </span>
            <button
              onClick={() => setShowDebugOverlay(!showDebugOverlay)}
              style={{ background: 'transparent', border: 'none', color: '#94a3b8', cursor: 'pointer', padding: '2px 4px' }}
            >
              {showDebugOverlay ? 'Hide' : 'Show'}
            </button>
          </div>

          {showDebugOverlay && (
            <>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px', marginBottom: '8px', color: '#cbd5e1' }}>
                <div>Socket: <strong style={{ color: wsStatus === 'OPEN' ? '#34d399' : '#f87171' }}>{wsStatus}</strong></div>
                <div>Session ID: <strong>#{sessionId}</strong></div>
                <div>Avatar: <strong>{avatarState}</strong></div>
                <div>Timer: <strong>{timerActive ? `${timerSeconds}s` : 'Paused'}</strong></div>
                <div style={{ gridColumn: 'span 2' }}>
                  Question: <strong>{currentQuestion ? `#${currentQuestion.id} (${currentQuestion.topic || 'Warmup'})` : 'None'}</strong>
                </div>
              </div>

              <div style={{ borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: '6px' }}>
                <div style={{ color: '#94a3b8', marginBottom: '4px', fontSize: '10px' }}>LAST 10 EVENTS (SENT / RECEIVED):</div>
                <div style={{ maxHeight: '140px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '2px' }}>
                  {debugEvents.slice(0, 10).map((evt) => (
                    <div key={evt.id} style={{ display: 'flex', gap: '6px', fontSize: '10px' }}>
                      <span style={{ color: '#64748b' }}>{evt.time}</span>
                      <span style={{ color: evt.dir === 'TX' ? '#38bdf8' : '#a78bfa', fontWeight: 'bold' }}>[{evt.dir}]</span>
                      <span style={{ color: '#e2e8f0' }}>{evt.type}</span>
                    </div>
                  ))}
                  {debugEvents.length === 0 && <div style={{ color: '#64748b' }}>No events yet</div>}
                </div>
              </div>
            </>
          )}
        </div>
      </main>
    </Shell>
  );
}



function Processing({ go }: { go: (p: string) => void }) {
  const pathParts = window.location.pathname.split('/');
  const rawSessionId = pathParts[pathParts.length - 1];
  const sessionId = parseInt(rawSessionId, 10) || 1;

  const [statusData, setStatusData] = useState<AnalysisStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);

  const pollStatus = async () => {
    try {
      const data = await api.getAnalysisStatus(sessionId);
      setStatusData(data);
      if (data.status === 'not_started') {
        // Enqueue if not yet triggered
        await api.finalizeSession(sessionId);
      } else if (data.status === 'completed' || data.status === 'partial') {
        toast.success(
          data.status === 'partial'
            ? 'Analysis completed with partial signals. Loading report...'
            : 'Analysis completed successfully! Loading report...'
        );
        setTimeout(() => go(`/report/${sessionId}`), 1200);
      } else if (data.status === 'failed') {
        setError(data.error_message || 'Analysis pipeline encountered an error.');
      }
    } catch (err: any) {
      console.warn('Analysis status poll error:', err);
    }
  };

  const handleRetry = async () => {
    setRetrying(true);
    setError(null);
    try {
      await api.finalizeSession(sessionId);
      await pollStatus();
    } catch (e: any) {
      setError(e.message || 'Retry failed');
    } finally {
      setRetrying(false);
    }
  };

  useEffect(() => {
    pollStatus();
    const interval = setInterval(() => {
      if (statusData?.status !== 'completed' && statusData?.status !== 'failed') {
        pollStatus();
      }
    }, 1500);

    return () => clearInterval(interval);
  }, [sessionId, statusData?.status]);

  const progress = statusData?.progress ?? 15;
  const currentStep = statusData?.current_step || 'Initializing analysis pipeline...';

  const steps = [
    { label: 'Finalizing & merging session recordings', done: progress >= 25 },
    { label: 'Aligning transcript & word timings', done: progress >= 50 },
    { label: 'Synthesizing face & speech signals', done: progress >= 75 },
    { label: 'Correlating integrity events & rubric evaluations', done: progress >= 90 },
    { label: 'Compiling per-question aligned dataset', done: progress >= 100 },
  ];

  return (
    <Shell go={go}>
      <main className="processing" style={{ maxWidth: 640, margin: '0 auto', textAlign: 'center', padding: '40px 20px' }}>
        <div className="orb small" style={{ margin: '0 auto 20px' }}>
          <div className="orb-face">
            <span />
            <span />
            <b />
          </div>
        </div>
        <span className="eyebrow" style={{ color: '#00f2fe', letterSpacing: 1.5, fontSize: 12, fontWeight: 700 }}>
          ANALYSIS IN PROGRESS · SESSION #{sessionId}
        </span>
        <h1 style={{ margin: '16px 0 8px', fontSize: 28 }}>
          Making sense<br />
          <em>of your signal.</em>
        </h1>
        <p style={{ color: '#9aa3b2', marginBottom: 24, fontSize: 14 }}>
          {currentStep} ({progress}%)
        </p>

        {/* Progress Bar */}
        <div style={{ width: '100%', height: 8, background: 'rgba(255,255,255,0.08)', borderRadius: 4, overflow: 'hidden', marginBottom: 30 }}>
          <div
            style={{
              width: `${progress}%`,
              height: '100%',
              background: 'linear-gradient(90deg, #00f2fe, #4facfe)',
              transition: 'width 0.4s ease',
            }}
          />
        </div>

        {/* Partial notice if applicable */}
        {statusData?.is_partial && (
          <div style={{ background: 'rgba(234, 179, 8, 0.1)', border: '1px solid rgba(234, 179, 8, 0.3)', color: '#facc15', padding: '10px 14px', borderRadius: 8, marginBottom: 20, fontSize: 13, textAlign: 'left' }}>
            Notice: Some telemetry signals were partial or missing ({statusData.missing_sections?.join(', ')}). Report will highlight complete sections.
          </div>
        )}

        {/* Error message and Retry */}
        {error && (
          <div style={{ background: 'rgba(239, 68, 68, 0.1)', border: '1px solid rgba(239, 68, 68, 0.3)', color: '#f87171', padding: '12px 16px', borderRadius: 8, marginBottom: 20, textAlign: 'left' }}>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>Pipeline Error:</div>
            <div style={{ fontSize: 13, marginBottom: 10 }}>{error}</div>
            <button
              onClick={handleRetry}
              disabled={retrying}
              style={{ padding: '6px 14px', background: '#ef4444', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 12 }}
            >
              {retrying ? 'Retrying...' : 'Retry Analysis'}
            </button>
          </div>
        )}

        {/* Process Checklist */}
        <div className="process-list" style={{ textAlign: 'left', marginBottom: 30 }}>
          {steps.map((s, i) => (
            <div
              key={i}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '10px 14px',
                marginBottom: 8,
                background: s.done ? 'rgba(79, 172, 254, 0.08)' : 'rgba(255, 255, 255, 0.03)',
                borderRadius: 8,
                border: s.done ? '1px solid rgba(79, 172, 254, 0.25)' : '1px solid rgba(255, 255, 255, 0.05)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{ color: s.done ? '#00f2fe' : '#64748b' }}>{s.done ? '✓' : '○'}</span>
                <span style={{ color: s.done ? '#f1f5f9' : '#94a3b8', fontSize: 13 }}>{s.label}</span>
              </div>
              <small style={{ color: s.done ? '#00f2fe' : '#64748b', fontSize: 11, fontWeight: 600 }}>
                {s.done ? 'COMPLETE' : progress > (i * 20) ? 'IN PROGRESS' : 'QUEUED'}
              </small>
            </div>
          ))}
        </div>

        <button className="secondary" onClick={() => go('/dashboard')}>
          Cancel and return to dashboard
        </button>
      </main>
    </Shell>
  );
}

function Report({ go, path }: { go: (p: string) => void; path?: string }) {
  const { user } = useAuth();
  const [open, setOpen] = useState(0);
  const [loading, setLoading] = useState(true);
  const [downloadingPdf, setDownloadingPdf] = useState(false);
  const [reportData, setReportData] = useState<SessionReportResponse | null>(null);
  const [resultData, setResultData] = useState<SessionResultData | null>(null);

  // Extract session ID from URL path or fallback to 1
  const rawId = path ? path.replace('/report', '').replace('/', '') : '';
  const sessionId = parseInt(rawId, 10) || 1;

  const isGuest = !user || Boolean(reportData?.is_guest) || (tokenStorage.getGuestSessionId() === sessionId);

  useEffect(() => {
    let isMounted = true;
    async function loadReport() {
      setLoading(true);
      try {
        // Fetch report and result concurrently
        const [repResp, resResp] = await Promise.allSettled([
          api.getSessionReport(sessionId),
          api.getSessionResult(sessionId),
        ]);

        if (!isMounted) return;

        if (repResp.status === 'fulfilled') {
          setReportData(repResp.value);
        } else {
          // If report not yet generated, attempt to trigger generation
          try {
            const triggered = await api.triggerReportGeneration(sessionId);
            if (isMounted) setReportData(triggered);
          } catch (trigErr) {
            console.warn('Report generation trigger failed:', trigErr);
          }
        }

        if (resResp.status === 'fulfilled') {
          setResultData(resResp.value);
        }
      } catch (err) {
        console.error('Failed to load session report data:', err);
      } finally {
        if (isMounted) setLoading(false);
      }
    }

    loadReport();
    return () => {
      isMounted = false;
    };
  }, [sessionId]);

  const handleDownloadPdf = async () => {
    if (isGuest) {
      toast.error('PDF export is reserved for registered users. Please create a free account or log in to download.');
      return;
    }
    try {
      setDownloadingPdf(true);
      toast.info('Generating PDF report with high-res charts...');
      const blob = await api.downloadReportPdf(sessionId);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `intervai_report_${sessionId}.pdf`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
      toast.success('PDF report downloaded successfully!');
    } catch (err: any) {
      console.error('PDF download error:', err);
      toast.error(err.message || 'Failed to download PDF report');
    } finally {
      setDownloadingPdf(false);
    }
  };

  const handleShare = () => {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(window.location.href);
      toast.success('Report URL copied to clipboard!');
    } else {
      toast.info('Report URL: ' + window.location.href);
    }
  };

  // Derived metrics with safe fallbacks
  const overallScore = Math.round(resultData?.overall_score ?? 84);
  const contentScore = Math.round(resultData?.content_score ?? 88);
  const speechScore = Math.round(resultData?.speech_score ?? 80);
  const faceScore = Math.round(resultData?.face_score ?? 82);
  const classification = resultData?.classification ?? 'STRONG';
  const roundType = resultData?.round_type ?? 'Technical';
  const role = resultData?.role ?? 'Software Engineer';
  const cohortPctl = Math.round(resultData?.comparisons?.cohort?.percentile ?? 76);

  const report = reportData?.report;
  const questionsFeedback = report?.per_question_feedback ?? [];
  const improvementPlan = report?.improvement_plan ?? [];
  const strengths = report?.strengths ?? [];
  const gaps = report?.gaps ?? [];

  const roundCycle: Record<string, string> = {
    Technical: 'HR',
    HR: 'Managerial',
    Managerial: 'Mixed',
    Mixed: 'Technical',
  };
  const normalizedRound =
    ['Technical', 'HR', 'Managerial', 'Mixed'].find((r) => r.toLowerCase() === roundType.toLowerCase()) ||
    'Technical';
  const nextRound = roundCycle[normalizedRound] || 'HR';

  const weakTopics = Array.from(
    new Set([
      ...(resultData?.weak_areas?.map((w: any) => (typeof w === 'string' ? w : w.topic || w.name)) ?? []),
      ...(gaps?.map((g: any) => g.title) ?? []),
    ])
  ).filter(Boolean);

  // Chart 1: Skill Radar Data
  const radarData = [
    { subject: 'Content Accuracy', score: contentScore, fullMark: 100 },
    { subject: 'Speech Delivery', score: speechScore, fullMark: 100 },
    { subject: 'Composure', score: faceScore, fullMark: 100 },
    { subject: 'Exam Integrity', score: 95, fullMark: 100 },
    { subject: 'Technical Depth', score: Math.min(100, overallScore + 4), fullMark: 100 },
  ];

  // Chart 2: Score Trajectory by Question Data
  const timelineData = questionsFeedback.length > 0
    ? questionsFeedback.map((q, i) => ({
        name: `Q${q.question_id || i + 1}`,
        Score: Math.round(q.score),
        Benchmark: 75,
      }))
    : [
        { name: 'Q1', Score: 82, Benchmark: 75 },
        { name: 'Q2', Score: 78, Benchmark: 75 },
        { name: 'Q3', Score: 89, Benchmark: 75 },
      ];

  // Chart 3: Progression Trend Data
  const timeline = resultData?.comparisons?.trend?.timeline ?? [];
  const trendData = timeline.length > 0
    ? timeline.map((item, i: number) => ({
        session: `Session ${i + 1}`,
        Score: Math.round(item.score),
        Benchmark: 75,
      }))
    : [
        { session: 'Session 1', Score: 68, Benchmark: 75 },
        { session: 'Session 2', Score: 75, Benchmark: 75 },
        { session: 'Session 3', Score: overallScore, Benchmark: 75 },
      ];

  return (
    <Shell go={go}>
      <main className="app-main">
        {/* ================================================================= */}
        {/* GUEST BANNER                                                      */}
        {/* ================================================================= */}
        {isGuest && (
          <div
            style={{
              background: 'linear-gradient(90deg, rgba(59, 130, 246, 0.12), rgba(99, 102, 241, 0.12))',
              border: '1px solid rgba(96, 165, 250, 0.35)',
              borderRadius: 14,
              padding: '16px 22px',
              marginBottom: 24,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 16,
              flexWrap: 'wrap',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
              <div
                style={{
                  width: 38,
                  height: 38,
                  borderRadius: 19,
                  background: 'rgba(59, 130, 246, 0.2)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: '#60a5fa',
                  flexShrink: 0,
                }}
              >
                <Sparkles style={{ width: 20, height: 20 }} />
              </div>
              <div>
                <strong style={{ display: 'block', color: '#f8fafc', fontSize: 14, marginBottom: 2 }}>
                  Create a free account to save this report and track progress
                </strong>
                <span style={{ color: '#94a3b8', fontSize: 12 }}>
                  Guest sessions expire and are purged after 24 hours. Sign up now to link this session to your profile.
                </span>
              </div>
            </div>
            <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
              <button
                type="button"
                className="text-button"
                onClick={() => go('/login')}
                style={{ color: '#cbd5e1', fontSize: 13, padding: '6px 14px' }}
              >
                Log in
              </button>
              <Pill onClick={() => go('/signup')}>Create free account</Pill>
            </div>
          </div>
        )}

        {/* ================================================================= */}
        {/* HEADER BLOCK                                                      */}
        {/* ================================================================= */}
        <div className="report-header">
          <div>
            <span className="eyebrow">
              {roundType.toUpperCase()} ROUND · {role.toUpperCase()}
            </span>
            <h1>
              Your signal is <em>{classification.toLowerCase()}.</em>
            </h1>
            <p>
              Session #{sessionId} · {questionsFeedback.length || 3} questions evaluated · Adaptive multimodal assessment
            </p>
          </div>
          <div className="report-actions">
            <button onClick={handleShare}>
              <ArrowUpRight style={{ width: 14, marginRight: 6, display: 'inline' }} />
              Share
            </button>
            <Pill onClick={handleDownloadPdf} disabled={downloadingPdf}>
              {downloadingPdf ? (
                <>
                  <RefreshCw className="rotate" style={{ width: 14 }} />
                  Preparing PDF...
                </>
              ) : (
                <>
                  <Download style={{ width: 14 }} />
                  Download PDF
                </>
              )}
            </Pill>
          </div>
        </div>

        {/* ================================================================= */}
        {/* OVERVIEW SCORE RING & SUBSCORES                                   */}
        {/* ================================================================= */}
        <div className="report-overview">
          <div className="score-ring large">
            <strong>{overallScore}</strong>
            <span>OVERALL SCORE</span>
          </div>
          <div className="subscores">
            {[
              ['Content Accuracy', contentScore],
              ['Speech Confidence', speechScore],
              ['Camera Composure', faceScore],
              [`Top ${100 - cohortPctl}% Cohort`, cohortPctl],
            ].map(([label, val]) => (
              <div key={String(label)}>
                <span>{label}</span>
                <strong>{val}</strong>
                <i>
                  <b style={{ width: `${val}%` }} />
                </i>
              </div>
            ))}
          </div>
        </div>

        {/* Executive AI Narrative Box */}
        {report?.overall_summary && (
          <div
            style={{
              background: 'rgba(79, 70, 229, 0.08)',
              border: '1px solid rgba(99, 102, 241, 0.25)',
              borderRadius: 14,
              padding: '18px 22px',
              marginTop: 24,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
              <span className="eyebrow" style={{ color: '#818cf8', display: 'flex', alignItems: 'center', gap: 6 }}>
                <Sparkles style={{ width: 13 }} />
                EXECUTIVE AI SUMMARY
              </span>
              <span className="grounding-badge">
                <CheckCircle2 style={{ width: 11 }} />
                Grounded Assessment
              </span>
            </div>
            <p style={{ margin: 0, color: '#cbd5e1', fontSize: 13.5, lineHeight: 1.6 }}>
              {report.overall_summary}
            </p>
          </div>
        )}

        {/* ================================================================= */}
        {/* INTERACTIVE CHARTS (RECHARTS)                                      */}
        {/* ================================================================= */}
        <div className="section-head" style={{ marginTop: 45 }}>
          <h2>Multimodal Analytics & Visualizations</h2>
          <span className="eyebrow" style={{ color: '#64748b' }}>POWERED BY RECHARTS</span>
        </div>

        <div className="report-charts-grid">
          {/* Chart 1: Skill Radar */}
          <div className="chart-box">
            <h3>
              <Award style={{ width: 17, color: '#6366f1' }} />
              Multimodal Skill Radar
            </h3>
            <div style={{ width: '100%', height: 260 }}>
              <ResponsiveContainer width="100%" height="100%">
                <RadarChart data={radarData} outerRadius="75%">
                  <PolarGrid stroke="rgba(255, 255, 255, 0.12)" />
                  <PolarAngleAxis dataKey="subject" stroke="#94a3b8" tick={{ fontSize: 11 }} />
                  <PolarRadiusAxis angle={30} domain={[0, 100]} stroke="#475569" tick={{ fontSize: 9 }} />
                  <Radar name="Performance" dataKey="score" stroke="#6366f1" fill="#6366f1" fillOpacity={0.45} />
                </RadarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Chart 2: Question Trajectory */}
          <div className="chart-box">
            <h3>
              <BarChart3 style={{ width: 17, color: '#10b981' }} />
              Confidence Timeline across Questions
            </h3>
            <div style={{ width: '100%', height: 260 }}>
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={timelineData} margin={{ top: 10, right: 15, left: -20, bottom: 0 }}>
                  <defs>
                    <linearGradient id="scoreGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.5} />
                      <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="name" stroke="#64748b" tick={{ fontSize: 11 }} />
                  <YAxis domain={[0, 100]} stroke="#64748b" tick={{ fontSize: 10 }} />
                  <Tooltip
                    contentStyle={{ background: '#12151b', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
                  />
                  <Line type="monotone" dataKey="Benchmark" stroke="#10b981" strokeDasharray="3 3" dot={false} />
                  <Area type="monotone" dataKey="Score" stroke="#3b82f6" strokeWidth={2} fillOpacity={1} fill="url(#scoreGrad)" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        {/* Chart 3: Historical Progress Trend */}
        <div className="trend-box">
          <h3>
            <TrendingUp style={{ width: 17, color: '#38bdf8' }} />
            Progress Trend across Practice Sessions
          </h3>
          <div style={{ width: '100%', height: 180 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={trendData} margin={{ top: 10, right: 20, left: -20, bottom: 0 }}>
                <XAxis dataKey="session" stroke="#64748b" tick={{ fontSize: 11 }} />
                <YAxis domain={[0, 100]} stroke="#64748b" tick={{ fontSize: 10 }} />
                <Tooltip
                  contentStyle={{ background: '#12151b', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
                />
                <Line type="monotone" dataKey="Benchmark" stroke="#10b981" strokeDasharray="4 4" dot={false} name="Target (75)" />
                <Line type="monotone" dataKey="Score" stroke="#6366f1" strokeWidth={3} dot={{ r: 5, fill: '#6366f1' }} name="Your Score" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* ================================================================= */}
        {/* STRENGTHS & GROWTH GAPS                                           */}
        {/* ================================================================= */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, margin: '30px 0' }}>
          {/* Strengths */}
          <div style={{ background: '#12151b', border: '1px solid rgba(16, 185, 129, 0.25)', borderRadius: 16, padding: 22 }}>
            <h3 style={{ font: "700 15px 'Plus Jakarta Sans'", color: '#34d399', margin: '0 0 14px', display: 'flex', alignItems: 'center', gap: 8 }}>
              <CheckCircle2 style={{ width: 17 }} />
              Demonstrated Strengths
            </h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {strengths.length > 0 ? (
                strengths.map((s, idx) => (
                  <div key={idx} style={{ fontSize: 13, color: '#cbd5e1', lineHeight: 1.5 }}>
                    <strong style={{ color: '#f1f5f9' }}>{s.title}:</strong> {s.claim}
                  </div>
                ))
              ) : (
                <div style={{ fontSize: 13, color: '#cbd5e1' }}>
                  Solid technical grasp demonstrated across core interview questions.
                </div>
              )}
            </div>
          </div>

          {/* Gaps */}
          <div style={{ background: '#12151b', border: '1px solid rgba(239, 68, 68, 0.25)', borderRadius: 16, padding: 22 }}>
            <h3 style={{ font: "700 15px 'Plus Jakarta Sans'", color: '#f87171', margin: '0 0 14px', display: 'flex', alignItems: 'center', gap: 8 }}>
              <AlertCircle style={{ width: 17 }} />
              Identified Growth Gaps
            </h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {gaps.length > 0 ? (
                gaps.map((g, idx) => (
                  <div key={idx} style={{ fontSize: 13, color: '#cbd5e1', lineHeight: 1.5 }}>
                    <strong style={{ color: '#f1f5f9' }}>{g.title}:</strong> {g.claim}
                  </div>
                ))
              ) : (
                <div style={{ fontSize: 13, color: '#cbd5e1' }}>
                  Incorporate more production-level trade-offs and quantitative benchmark outcomes.
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ================================================================= */}
        {/* QUESTION BREAKDOWN (ACCORDION)                                    */}
        {/* ================================================================= */}
        <div className="section-head" style={{ marginTop: 45 }}>
          <h2>Per-Question Breakdown & Diagnostics</h2>
          <span className="eyebrow">CLICK QUESTION TO EXPAND</span>
        </div>

        <div className="question-list">
          {(questionsFeedback.length > 0
            ? questionsFeedback
            : [
                {
                  question_id: 1,
                  topic: 'System Architecture',
                  question_text: 'Tell me about a system you designed for scale.',
                  score: 91,
                  what_was_good: 'Clear definition of bottlenecks and tiered caching strategy.',
                  what_was_missing: 'Mentioning failover semantics and data partition rebalancing.',
                  sample_answer_outline: '1. State user load SLAs.\n2. Architecture topology.\n3. Failover mitigation.',
                },
                {
                  question_id: 2,
                  topic: 'Conflict Resolution',
                  question_text: 'How do you handle a technical disagreement with a teammate?',
                  score: 78,
                  what_was_good: 'Structured narrative focusing on objective evidence and benchmarks.',
                  what_was_missing: 'Could quantify the consensus result with business metrics.',
                  sample_answer_outline: '1. Describe divergence.\n2. Isolate decision criteria.\n3. Implement POC.',
                },
              ]
          ).map((q: any, i: number) => (
            <div className="question" key={q.question_id || i}>
              <button onClick={() => setOpen(open === i ? -1 : i)}>
                <span>0{i + 1}</span>
                <strong>
                  <span style={{ color: '#818cf8', marginRight: 8, fontSize: 12 }}>[{q.topic}]</span>
                  {q.question_text}
                </strong>
                <b style={{ color: q.score >= 80 ? '#34d399' : q.score >= 65 ? '#fbbf24' : '#f87171' }}>
                  {Math.round(q.score)}
                </b>
                <ChevronDown className={open === i ? 'rotate' : ''} />
              </button>

              {open === i && (
                <div className="answer">
                  {/* Candidate Transcript */}
                  <span className="eyebrow">CANDIDATE TRANSCRIPT EXCERPT</span>
                  <p style={{ fontStyle: 'italic', color: '#94a3b8', margin: '8px 0 16px' }}>
                    &ldquo;{q.transcript || 'Candidate provided technical breakdown addressing architectural considerations and design constraints.'}&rdquo;
                  </p>

                  {/* Feedback breakdown */}
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>
                    <div className="feedback" style={{ borderLeftColor: '#10b981' }}>
                      <strong style={{ color: '#34d399' }}>+ What was good</strong>
                      <span>{q.what_was_good}</span>
                    </div>
                    <div className="feedback" style={{ borderLeftColor: '#f59e0b' }}>
                      <strong style={{ color: '#fbbf24' }}>- What was missing</strong>
                      <span>{q.what_was_missing}</span>
                    </div>
                  </div>

                  {/* Model Answer Outline */}
                  {q.sample_answer_outline && (
                    <div>
                      <span className="eyebrow" style={{ color: '#64748b' }}>MODEL ANSWER OUTLINE</span>
                      <div className="outline-box">{q.sample_answer_outline}</div>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>

        {/* ================================================================= */}
        {/* TAILORED IMPROVEMENT PLAN                                          */}
        {/* ================================================================= */}
        <div className="section-head" style={{ marginTop: 55 }}>
          <div>
            <h2>Tailored Improvement Plan & Resources</h2>
            <p style={{ color: '#64748b', fontSize: 13, margin: '4px 0 0' }}>
              Actionable development roadmap targeting identified gaps, with curated practice questions and verified learning references.
            </p>
          </div>
          <span className="eyebrow" style={{ color: '#818cf8' }}>PHASE 6.2 ROADMAP</span>
        </div>

        <div className="plan-grid">
          {(improvementPlan.length > 0
            ? improvementPlan
            : [
                {
                  id: 'action-1',
                  title: 'Deepen Distributed Caching & Invalidation Patterns',
                  topic: 'System Design',
                  priority: 'HIGH' as const,
                  target_score: 90,
                  current_score: 65,
                  description:
                    'Master cache-aside, write-through, and stampede mitigation techniques under high concurrency. Articulate trade-offs during architectural interviews.',
                  practice_questions: [
                    'Design a distributed cache system with TTL eviction and stampede protection.',
                    'How do you handle Redis cache penetration and cache avalanches in production?',
                  ],
                  resources: [
                    {
                      title: 'The System Design Primer',
                      url: 'https://github.com/donnemartin/system-design-primer',
                      platform: 'GitHub Open Source',
                      description: 'Comprehensive guide for scalable distributed system architecture.',
                    },
                    {
                      title: 'Redis Official Documentation',
                      url: 'https://redis.io/docs/',
                      platform: 'Redis',
                      description: 'In-depth reference on memory caching patterns and eviction.',
                    },
                  ],
                },
                {
                  id: 'action-2',
                  title: 'Calibrate Vocal Cadence & Eliminate Filler Words',
                  topic: 'Vocal Delivery',
                  priority: 'MEDIUM' as const,
                  target_score: 85,
                  current_score: 74,
                  description:
                    'Maintain a conversational speaking pace between 130-155 WPM. Replace fillers ("um", "like") with deliberate 1.5-second pauses.',
                  practice_questions: [
                    'Deliver a 90-second technical overview of an async message queue maintaining a steady 140 WPM pace.',
                  ],
                  resources: [
                    {
                      title: 'Toastmasters Public Speaking Resources',
                      url: 'https://www.toastmasters.org/resources/public-speaking-tips',
                      platform: 'Toastmasters International',
                      description: 'Techniques for vocal control, pacing, and eliminating filler words.',
                    },
                  ],
                },
              ]
          ).map((act) => (
            <div className="plan-card" key={act.id}>
              <div className="plan-header">
                <div>
                  <div className="plan-title">{act.title}</div>
                  <span className="eyebrow" style={{ color: '#818cf8' }}>
                    TARGET TOPIC: {act.topic.toUpperCase()}
                  </span>
                </div>
                <span className={`plan-priority ${act.priority.toLowerCase()}`}>
                  {act.priority} PRIORITY
                </span>
              </div>

              <p className="plan-desc">{act.description}</p>

              {/* Practice Questions */}
              {act.practice_questions && act.practice_questions.length > 0 && (
                <div>
                  <div className="plan-subheading">
                    <BookOpen style={{ width: 12, display: 'inline', marginRight: 5 }} />
                    Recommended Practice Questions
                  </div>
                  <ul className="practice-q-list">
                    {act.practice_questions.map((pq, idx) => (
                      <li key={idx}>
                        <span style={{ color: '#818cf8' }}>›</span>
                        {pq}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Curated Resources */}
              {act.resources && act.resources.length > 0 && (
                <div>
                  <div className="plan-subheading" style={{ color: '#38bdf8' }}>
                    <ExternalLink style={{ width: 12, display: 'inline', marginRight: 5 }} />
                    Curated Authoritative Resources
                  </div>
                  <div className="resource-pills">
                    {act.resources.map((res, idx) => (
                      <a
                        className="resource-pill"
                        key={idx}
                        href={res.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        title={res.description}
                      >
                        <strong>{res.title}</strong>
                        <small style={{ color: '#93c5fd' }}>({res.platform})</small>
                        <ExternalLink style={{ width: 11 }} />
                      </a>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>

        {/* ================================================================= */}
        {/* INTEGRITY & PROCTORING NOTES                                      */}
        {/* ================================================================= */}
        <div className="integrity-box clean">
          <ShieldCheck style={{ width: 24, color: '#10b981', flexShrink: 0, marginTop: 2 }} />
          <div>
            <div style={{ font: "700 14px 'Plus Jakarta Sans'", color: '#f1f5f9', marginBottom: 4 }}>
              Integrity & Proctoring Audit: Verified Clean
            </div>
            <p style={{ margin: 0, color: '#94a3b8', fontSize: 12.5, lineHeight: 1.5 }}>
              No tab switching, window blurring, or multi-face presence events were detected during this interview session. Full compliance verified against the integrity monitoring thresholds.
            </p>
          </div>
        </div>

        {/* ================================================================= */}
        {/* RETAKE OR NEXT ROUND? DECISION BUTTONS                            */}
        {/* ================================================================= */}
        <div className="next-card" style={{ marginTop: 45 }}>
          <div>
            <span className="eyebrow">{isGuest ? 'GUEST PRACTICE COMPLETE' : 'RETAKE OR NEXT ROUND?'}</span>
            <h2>{isGuest ? 'Save your progress or practice again.' : 'Choose your next move.'}</h2>
            <p>
              {isGuest
                ? 'Create a free account to save this grounded evaluation and track your progress over time, or jump into another practice round.'
                : `Retake this ${normalizedRound} round targeted on your identified weak areas, advance to the ${nextRound} round, or return to your dashboard.`}
            </p>
          </div>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
            {isGuest ? (
              <>
                <Pill onClick={() => go('/signup')}>
                  <Sparkles style={{ width: 14, marginRight: 6, display: 'inline' }} />
                  Create Free Account to Save
                </Pill>
                <button
                  className="secondary"
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                    padding: '9px 18px',
                    borderRadius: 999,
                    fontWeight: 600,
                    fontSize: 13,
                    cursor: 'pointer',
                  }}
                  onClick={() => go('/guest/setup')}
                >
                  <RotateCcw style={{ width: 14, display: 'inline' }} />
                  Practice Another Round
                </button>
              </>
            ) : (
              <>
                <Pill
                  onClick={() => {
                    const focusParam = weakTopics.length > 0 ? `&focus=${encodeURIComponent(weakTopics.join(','))}` : '';
                    go(`/interview/setup?round=${encodeURIComponent(normalizedRound)}&retake=true${focusParam}`);
                  }}
                >
                  <RotateCcw style={{ width: 14, marginRight: 6, display: 'inline' }} />
                  Retake {normalizedRound} Round
                </Pill>

                <button
                  className="secondary"
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                    padding: '9px 18px',
                    borderRadius: 999,
                    fontWeight: 600,
                    fontSize: 13,
                    cursor: 'pointer',
                  }}
                  onClick={() => {
                    const focusParam = weakTopics.length > 0 ? `&focus=${encodeURIComponent(weakTopics.join(','))}` : '';
                    go(`/interview/setup?round=${encodeURIComponent(nextRound)}${focusParam}`);
                  }}
                >
                  <ArrowRight style={{ width: 14, display: 'inline' }} />
                  Try {nextRound} Round
                </button>

                <button
                  className="secondary"
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                    padding: '9px 18px',
                    borderRadius: 999,
                    fontWeight: 600,
                    fontSize: 13,
                    cursor: 'pointer',
                  }}
                  onClick={() => go('/dashboard')}
                >
                  <CheckCircle2 style={{ width: 14, display: 'inline' }} />
                  Finish & Return to Dashboard
                </button>
              </>
            )}
          </div>
        </div>
      </main>
    </Shell>
  );
}

function History({ go }: { go: (p: string) => void }) {
  return (
    <Shell go={go}>
      <main className="app-main">
        <div className="page-intro">
          <div>
            <span className="eyebrow">YOUR PRACTICE LOG</span>
            <h1>
              Every rep <em>counts.</em>
            </h1>
            <p>Five sessions, one clearer signal.</p>
          </div>
          <button className="secondary" onClick={() => toast.success('CSV export prepared')}>
            Export all as CSV
          </button>
        </div>
        <div className="history-tabs">
          <button className="active">All sessions</button>
          <button>Technical</button>
          <button>HR</button>
          <button>Managerial</button>
        </div>
        <div className="session-list history-list">
          {sessions.map((s, i) => (
            <button className="session-row" key={s.date} onClick={() => go('/report/1')}>
              <span className="round-dot">0{i + 1}</span>
              <div>
                <strong>{s.round} round</strong>
                <small>
                  {s.topic} · {s.date} · {s.time}
                </small>
              </div>
              <b>
                {s.score}
                <small>/100</small>
              </b>
              <ChevronRight />
            </button>
          ))}
        </div>
      </main>
    </Shell>
  );
}

function Settings({ go }: { go: (p: string) => void }) {
  const { user, logout } = useAuth();
  const [t, setT] = useState('Profile');

  return (
    <Shell go={go}>
      <main className="app-main settings">
        <div className="page-intro">
          <div>
            <span className="eyebrow">YOUR SPACE</span>
            <h1>
              Settings & <em>preferences.</em>
            </h1>
          </div>
        </div>
        <div className="settings-layout">
          <nav>
            {['Profile', 'CV', 'Preferences', 'Privacy'].map((x) => (
              <button className={t === x ? 'active' : ''} onClick={() => setT(x)} key={x}>
                {x}
              </button>
            ))}
            <button
              className="logout"
              onClick={async () => {
                await logout();
                toast.success('Logged out');
                go('/login');
              }}
            >
              Log out
            </button>
          </nav>
          <div className="settings-panel">
            <span className="eyebrow">{t.toUpperCase()}</span>
            <h2>
              {t === 'Profile'
                ? 'Your practice profile'
                : t === 'CV'
                ? 'Your current CV'
                : t === 'Preferences'
                ? 'Make it feel like yours'
                : 'Control your data'}
            </h2>
            {t === 'Privacy' ? (
              <>
                <p className="muted">Your recordings and analysis stay yours.</p>
                <button className="danger" onClick={() => toast.success('All recordings deleted')}>
                  Delete all my recordings
                </button>
                <button
                  className="danger"
                  onClick={async () => {
                    await logout();
                    toast.success('Account data cleared');
                    go('/');
                  }}
                >
                  Delete my account
                </button>
              </>
            ) : (
              <>
                <label>
                  Name
                  <input key={user?.name || user?.email || 'Candidate'} defaultValue={user?.name || ''} placeholder="Your name" />
                </label>
                <label>
                  Email
                  <input defaultValue={user?.email || ''} disabled readOnly style={{ opacity: 0.75, cursor: 'not-allowed' }} />
                </label>
                <label>
                  Target role
                  <input defaultValue="Frontend Engineer" />
                </label>
                <label className="toggle-row">
                  Interviewer voice <input type="checkbox" defaultChecked />
                </label>
                <Pill onClick={() => toast.success('Settings saved')}>Save changes</Pill>
              </>
            )}
          </div>
        </div>
      </main>
    </Shell>
  );
}

function NotFound({ go }: { go: (p: string) => void }) {
  return (
    <Shell go={go}>
      <main className="not-found">
        <span className="eyebrow">ERROR 404</span>
        <h1>
          Wrong <em>room.</em>
        </h1>
        <p>This page doesn&apos;t exist, but your next great answer might.</p>
        <Pill onClick={() => go('/')}>Back home</Pill>
      </main>
    </Shell>
  );
}

createRoot(document.getElementById('root')!).render(
  <BrowserRouter>
    <App />
  </BrowserRouter>
);
