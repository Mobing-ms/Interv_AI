export interface User {
  id: number;
  name: string;
  email: string;
  auth_provider: string;
  is_verified: boolean;
  onboarding_status?: string;
  created_at: string;
}

export interface AuthResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: User;
}

export interface EducationProfile {
  id?: number;
  user_id?: number;
  degree: string;
  branch: string;
  college: string;
  graduation_year: number;
  cgpa?: number | null;
  cgpa_scale?: number | null;
  created_at?: string;
  updated_at?: string;
}

export interface TargetProfile {
  id?: number;
  user_id?: number;
  target_role: string;
  company_type: string;
  experience_level: string;
  job_description?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface TargetSuggestions {
  suggestions: string[];
  company_types: string[];
  experience_levels: string[];
}

export interface OnboardingStatus {
  onboarding_status: string;
  current_step: number;
  education_done: boolean;
  target_done: boolean;
  cv_done: boolean;
  profile_confirmed: boolean;
}

export interface CVUploadResponse {
  id: number;
  file_key: string;
  filename: string;
  status: string;
  created_at: string;
}

export interface CVStatusResponse {
  id: number;
  status: 'uploaded' | 'extracting' | 'extracted' | 'failed';
  filename: string;
  file_size: number;
  text_length?: number | null;
  raw_text?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  created_at: string;
  extracted_at?: string | null;
}

export interface StructuredCV {
  personal: {
    name?: string | null;
    email?: string | null;
    phone?: string | null;
    links: string[];
  };
  education: Array<{
    degree?: string | null;
    branch?: string | null;
    college?: string | null;
    year?: number | string | null;
    cgpa?: number | string | null;
  }>;
  skills: {
    languages: string[];
    frameworks: string[];
    tools: string[];
    domains: string[];
    soft: string[];
  };
  projects: Array<{
    title: string;
    description?: string | null;
    tech_stack: string[];
    role?: string | null;
    outcomes?: string | null;
  }>;
  internships_experience: Array<{
    company: string;
    role: string;
    duration?: string | null;
    responsibilities: string[];
  }>;
  certifications: string[];
  achievements: string[];
}

export interface CrossCheckFlag {
  type: 'MISMATCH' | 'MISSING_SECTION';
  field: string;
  cv_value?: string | null;
  form_value?: string | null;
  severity: 'HIGH' | 'MEDIUM' | 'LOW';
  message: string;
}

export interface CVParsedResponse {
  id: number;
  status: string;
  structured_data: StructuredCV;
  cross_check_flags: CrossCheckFlag[];
  parsed_at?: string | null;
}


export class ApiError extends Error {
  status?: number;
  detail: string;
  isNetworkError: boolean;
  errorCode?: string;

  constructor(detail: string, status?: number, isNetworkError: boolean = false, errorCode?: string) {
    super(detail);
    this.name = 'ApiError';
    this.detail = detail;
    this.status = status;
    this.isNetworkError = isNetworkError;
    this.errorCode = errorCode;
  }
}

export const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';


export const tokenStorage = {
  getAccessToken: (): string | null => localStorage.getItem('intervai_access_token'),
  getRefreshToken: (): string | null => localStorage.getItem('intervai_refresh_token'),
  setTokens: (accessToken: string, refreshToken: string) => {
    localStorage.setItem('intervai_access_token', accessToken);
    localStorage.setItem('intervai_refresh_token', refreshToken);
  },
  clearTokens: () => {
    localStorage.removeItem('intervai_access_token');
    localStorage.removeItem('intervai_refresh_token');
  },
};

async function request<T>(endpoint: string, options: RequestInit = {}, retryOn401 = true): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;
  const headers = new Headers(options.headers || {});

  // Only set application/json if body is not FormData
  if (!headers.has('Content-Type') && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  const token = tokenStorage.getAccessToken();
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  let response: Response;
  try {
    response = await fetch(url, { ...options, headers });
  } catch {
    throw new ApiError('Unable to connect to server. Please check your network.', undefined, true);
  }

  // Handle token refresh on 401
  if (response.status === 401 && retryOn401 && endpoint !== '/auth/login' && endpoint !== '/auth/refresh') {
    const refreshToken = tokenStorage.getRefreshToken();
    if (refreshToken) {
      try {
        const refreshResponse = await fetch(`${API_BASE_URL}/auth/refresh`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: refreshToken }),
        });

        if (refreshResponse.ok) {
          const data: AuthResponse = await refreshResponse.json();
          tokenStorage.setTokens(data.access_token, data.refresh_token);
          headers.set('Authorization', `Bearer ${data.access_token}`);
          return request<T>(endpoint, { ...options, headers }, false);
        } else {
          tokenStorage.clearTokens();
        }
      } catch {
        tokenStorage.clearTokens();
      }
    }
  }

  if (!response.ok) {
    let detail = 'An unexpected error occurred';
    let errorCode: string | undefined;
    try {
      const errorJson = await response.json();
      if (errorJson.error_code) {
        errorCode = errorJson.error_code;
      }
      if (typeof errorJson.detail === 'string') {
        detail = errorJson.detail;
      } else if (errorJson.message) {
        detail = errorJson.message;
      } else if (Array.isArray(errorJson.detail)) {
        detail = errorJson.detail.map((d: { msg?: string }) => d.msg).join(', ');
      }
    } catch {
      detail = response.statusText || detail;
    }
    throw new ApiError(detail, response.status, false, errorCode);
  }

  return response.json();
}

export const api = {
  async signup(name: string, email: string, password: string): Promise<AuthResponse> {
    const data = await request<AuthResponse>('/auth/signup', {
      method: 'POST',
      body: JSON.stringify({ name, email, password }),
    });
    tokenStorage.setTokens(data.access_token, data.refresh_token);
    return data;
  },

  async login(email: string, password: string): Promise<AuthResponse> {
    const data = await request<AuthResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    tokenStorage.setTokens(data.access_token, data.refresh_token);
    return data;
  },

  async googleAuth(payload: { credential?: string; token?: string; id_token?: string; email?: string; name?: string }): Promise<AuthResponse> {
    const data = await request<AuthResponse>('/auth/google', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    tokenStorage.setTokens(data.access_token, data.refresh_token);
    return data;
  },

  async getMe(): Promise<User> {
    return request<User>('/auth/me', { method: 'GET' });
  },

  async refresh(): Promise<AuthResponse> {
    const refreshToken = tokenStorage.getRefreshToken();
    if (!refreshToken) {
      throw new ApiError('No refresh token available', 401);
    }
    const data = await request<AuthResponse>('/auth/refresh', {
      method: 'POST',
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    tokenStorage.setTokens(data.access_token, data.refresh_token);
    return data;
  },

  async logout(): Promise<void> {
    try {
      await request<{ message: string }>('/auth/logout', { method: 'POST' });
    } catch {
      // Continue cleanup even if server logout fails
    } finally {
      tokenStorage.clearTokens();
    }
  },

  async requestOtp(email: string): Promise<{ message: string }> {
    return request<{ message: string }>('/auth/otp/request', {
      method: 'POST',
      body: JSON.stringify({ email }),
    });
  },

  async verifyOtp(email: string, otp: string): Promise<{ message: string }> {
    return request<{ message: string }>('/auth/otp/verify', {
      method: 'POST',
      body: JSON.stringify({ email, otp }),
    });
  },

  // --- Phase 1.2 Profile & Onboarding ---

  async getEducationProfile(): Promise<EducationProfile> {
    return request<EducationProfile>('/profile/education', { method: 'GET' });
  },

  async saveEducationProfile(data: {
    degree: string;
    branch: string;
    college: string;
    graduation_year: number;
    cgpa?: number | null;
    cgpa_scale?: number | null;
  }): Promise<EducationProfile> {
    return request<EducationProfile>('/profile/education', {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },

  async getTargetProfile(): Promise<TargetProfile> {
    return request<TargetProfile>('/profile/target', { method: 'GET' });
  },

  async saveTargetProfile(data: {
    target_role: string;
    company_type: string;
    experience_level: string;
    job_description?: string | null;
  }): Promise<TargetProfile> {
    return request<TargetProfile>('/profile/target', {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },

  async getTargetSuggestions(): Promise<TargetSuggestions> {
    return request<TargetSuggestions>('/profile/target/suggestions', { method: 'GET' });
  },

  async getOnboardingStatus(): Promise<OnboardingStatus> {
    return request<OnboardingStatus>('/profile/status', { method: 'GET' });
  },

  // --- Phase 1.3 CV Upload & Extraction ---

  async uploadCV(file: File): Promise<CVUploadResponse> {
    const formData = new FormData();
    formData.append('file', file);
    return request<CVUploadResponse>('/cv/upload', {
      method: 'POST',
      body: formData,
    });
  },

  async getCVStatus(cvId: number): Promise<CVStatusResponse> {
    return request<CVStatusResponse>(`/cv/${cvId}/status`, { method: 'GET' });
  },

  async getLatestCV(): Promise<CVStatusResponse> {
    return request<CVStatusResponse>('/cv/latest', { method: 'GET' });
  },

  // --- Phase 1.4 CV Structuring & Cross-Check ---

  async parseCV(cvId: number): Promise<CVParsedResponse> {
    return request<CVParsedResponse>(`/cv/${cvId}/parse`, { method: 'POST' });
  },

  async getParsedCV(cvId: number): Promise<CVParsedResponse> {
    return request<CVParsedResponse>(`/cv/${cvId}/parsed`, { method: 'GET' });
  },

  async getLatestParsedCV(): Promise<CVParsedResponse> {
    return request<CVParsedResponse>('/cv/latest/parsed', { method: 'GET' });
  },

  // --- Phase 1.5 Canonical Profile ---

  async confirmProfile(payload: {
    structured_data: StructuredCV;
    unresolved_flags?: CrossCheckFlag[];
    cv_document_id?: number | null;
  }): Promise<ConfirmedProfile> {
    return request<ConfirmedProfile>('/profile/confirm', {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  },

  async getCanonicalProfile(): Promise<ConfirmedProfile> {
    return request<ConfirmedProfile>('/profile', { method: 'GET' });
  },

  async getProfileVersions(): Promise<Array<{ id: number; version: number; confirmed_at: string }>> {
    return request<Array<{ id: number; version: number; confirmed_at: string }>>('/profile/versions', {
      method: 'GET',
    });
  },

  // --- Phase 2.1 Interview Setup & Memory Context ---

  async getInterviewContext(): Promise<UserContext> {
    return request<UserContext>('/interview/context', { method: 'GET' });
  },

  async saveInterviewConfig(payload: InterviewConfigCreate): Promise<InterviewConfig> {
    return request<InterviewConfig>('/interview/config', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async getLatestInterviewConfig(): Promise<InterviewConfig> {
    return request<InterviewConfig>('/interview/config/latest', { method: 'GET' });
  },

  async seedInterviewHistory(): Promise<UserContext> {
    return request<UserContext>('/interview/seed-history', { method: 'POST' });
  },

  async generateInterviewBlueprint(payload?: InterviewBlueprintRequest): Promise<InterviewBlueprint> {
    return request<InterviewBlueprint>('/interview/blueprint', {
      method: 'POST',
      body: payload ? JSON.stringify(payload) : undefined,
    });
  },

  // --- Phase 2.3 Question Pool Generation & Bank ---

  async generateQuestionPool(
    interviewId: number,
    options?: { force_regenerate?: boolean; similarity_threshold?: number; multiplier?: number }
  ): Promise<QuestionPoolResponse> {
    return request<QuestionPoolResponse>(`/interview/${interviewId}/questions/generate`, {
      method: 'POST',
      body: options ? JSON.stringify(options) : undefined,
    });
  },

  async getQuestionPool(interviewId: number): Promise<QuestionPoolResponse> {
    return request<QuestionPoolResponse>(`/interview/${interviewId}/questions`, { method: 'GET' });
  },

  // --- Phase 3.1 Pre-Interview Check, Consent, Calibration & Session ---

  async saveConsent(version: string = 'v1.0'): Promise<ConsentRecord> {
    return request<ConsentRecord>('/session/consent', {
      method: 'POST',
      body: JSON.stringify({ version, accepted: true }),
    });
  },

  async getLatestConsent(): Promise<ConsentRecord> {
    return request<ConsentRecord>('/session/consent', { method: 'GET' });
  },

  async pingNetwork(clientTs?: number): Promise<NetworkPingResponse> {
    const url = clientTs !== undefined ? `/session/ping?client_ts=${clientTs}` : '/session/ping';
    return request<NetworkPingResponse>(url, { method: 'GET' });
  },

  async uploadSpeedTest(payload: Blob | ArrayBuffer): Promise<NetworkSpeedTestResponse> {
    const token = localStorage.getItem('access_token');
    const headers: Record<string, string> = {
      'Content-Type': 'application/octet-stream',
    };
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    const res = await fetch(`${API_BASE_URL}/session/speed-test`, {
      method: 'POST',
      headers,
      body: payload,
    });
    if (!res.ok) {
      throw new Error(`Speed test failed with status ${res.status}`);
    }
    return res.json();
  },

  async createSession(interviewId?: number): Promise<InterviewSession> {
    return request<InterviewSession>('/session', {
      method: 'POST',
      body: JSON.stringify({ interview_id: interviewId }),
    });
  },

  async getSession(sessionId: number): Promise<InterviewSession> {
    return request<InterviewSession>(`/session/${sessionId}`, { method: 'GET' });
  },

  async saveCalibration(
    sessionId: number,
    payload: {
      face_baseline?: Record<string, any>;
      voice_baseline?: Record<string, any>;
      background_noise_level_db?: number;
      calibration_text?: string;
    }
  ): Promise<SessionCalibration> {
    return request<SessionCalibration>(`/session/${sessionId}/calibration`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async getCalibration(sessionId: number): Promise<SessionCalibration> {
    return request<SessionCalibration>(`/session/${sessionId}/calibration`, { method: 'GET' });
  },

  getAudioUrl(cacheKey: string): string {
    return `${API_BASE_URL}/session/tts/audio/${cacheKey}`;
  },

  async synthesizeSpeech(text: string, language?: string): Promise<{ audio_url: string; cache_key: string; language: string }> {
    return request('/session/tts/synthesize', {
      method: 'POST',
      body: JSON.stringify({ text, language }),
    });
  },
};


export interface ConfirmedProfile {
  id: number;
  user_id: number;
  version: number;
  structured_data: StructuredCV;
  cv_document_id?: number | null;
  confirmed_at: string;
  created_at: string;
}

export interface AskedQuestionItem {
  id: number;
  question_hash: string;
  topic: string;
  question_text?: string | null;
  asked_at: string;
  score?: number | null;
}

export interface UserContext {
  is_returning: boolean;
  session_count: number;
  last_session_at?: string | null;
  past_scores: Record<string, number>;
  weak_areas: string[];
  history_asked_questions: AskedQuestionItem[];
  baseline_weights: Record<string, number>;
  recommended_difficulty: string;
  recommended_round: string;
  recommended_duration: number;
  mode_presets: Record<string, any>;
}

export interface InterviewConfigCreate {
  round_type: string;
  difficulty: string;
  duration_minutes: number;
  language?: string;
  mode?: string;
  focus_topics?: string[];
}

export interface InterviewConfig {
  id: number;
  user_id: number;
  round_type: string;
  difficulty: string;
  duration_minutes: number;
  language: string;
  mode: string;
  focus_topics: string[];
  answer_timer_seconds: number;
  pressure_rules: Record<string, any>;
  created_at: string;
}

export interface BlueprintTopic {
  name: string;
  category: string;
  weight: number;
  allocated_questions: number;
  is_weak_area: boolean;
  description?: string | null;
}

export interface TimeBreakdown {
  warm_up_seconds: number;
  questions_total_seconds: number;
  closing_seconds: number;
  total_allocated_seconds: number;
  total_duration_seconds: number;
  time_per_question_seconds: number;
}

export interface InterviewBlueprint {
  round_type: string;
  difficulty: string;
  duration_minutes: number;
  mode: string;
  total_question_count: number;
  time_per_question_seconds: number;
  follow_up_limit_per_topic: number;
  difficulty_curve: string[];
  topics: BlueprintTopic[];
  warm_up_questions: string[];
  closing_questions: string[];
  time_breakdown: TimeBreakdown;
  mixed_ratio?: Record<string, number> | null;
}

export interface InterviewBlueprintRequest {
  config_id?: number;
  round_type?: string;
  difficulty?: string;
  duration_minutes?: number;
  language?: string;
  mode?: string;
  focus_topics?: string[];
  mixed_ratio?: Record<string, number>;
}

export interface QuestionBankItem {
  id: number;
  interview_id: number;
  question_hash: string;
  text: string;
  topic: string;
  subtopic?: string | null;
  difficulty: string;
  question_type: string;
  expected_keywords: string[];
  ideal_answer_points: string[];
  max_time_seconds: number;
  cv_reference?: string | null;
  is_weak_area: boolean;
  rank_score: number;
  is_reserve_followup: boolean;
  followup_templates?: string[];
  created_at: string;
}

export interface QuestionPoolResponse {
  interview_id: number;
  total_generated: number;
  deduped_count: number;
  questions: QuestionBankItem[];
  reserve_followups: QuestionBankItem[];
  blueprint_summary: Record<string, any>;
}

export interface ConsentRecord {
  id: number;
  user_id: number;
  version: string;
  retention_days: number;
  accepted: boolean;
  can_delete: boolean;
  accepted_at: string;
}

export interface NetworkPingResponse {
  server_time: string;
  client_timestamp?: number | null;
  status: string;
}

export interface NetworkSpeedTestResponse {
  bytes_received: number;
  duration_ms: number;
  upload_mbps: number;
  status: string;
}

export interface SessionCalibration {
  id: number;
  session_id: number;
  user_id: number;
  face_baseline: {
    neutral_score?: number;
    gaze_center?: { x: number; y: number };
    head_pose?: { pitch: number; yaw: number; roll: number };
  };
  voice_baseline: {
    average_volume_db?: number;
    pitch_range_hz?: number[];
    speaking_rate_wpm?: number;
  };
  background_noise_level_db: number;
  calibration_text?: string | null;
  calibrated_at: string;
}

export interface InterviewSession {
  id: number;
  user_id: number;
  interview_id: number;
  status: string;
  session_token: string;
  started_at: string;
  ended_at?: string | null;
  ws_url: string;
  calibration?: SessionCalibration | null;
}




