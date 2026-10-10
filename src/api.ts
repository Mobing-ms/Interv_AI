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

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

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


