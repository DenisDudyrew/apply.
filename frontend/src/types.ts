export type Preferences = {
  limit: number;
  skip_questionnaires: boolean;
  skip_foreign_vacancies: boolean;
  gentle: boolean;
};
export type Vacancy = {
  title: string;
  company: string;
  url: string;
  id?: string;
};
export type HistoryRow = {
  vacancy_id: string;
  title: string;
  company: string;
  url: string;
  status: string;
  note: string;
  updated: string;
};
export type PageData<T> = {
  items: T[];
  total: number;
  page: number;
  size: number;
};
export type Run = {
  limit?: number;
  captcha_attempt?: number;
  total?: number;
  sent?: number;
  skipped?: number;
  already?: number;
  attention?: number;
  processed?: number;
  current?: Vacancy | null;
  pause_until?: number | null;
  started_at?: number;
  finished_at?: number | null;
};
export type AppState = {
  revision: number;
  desktop?: boolean;
  running: boolean;
  waiting: boolean;
  phase: string;
  operation: string | null;
  message: string;
  logs: string[];
  image: string;
  prompt_kind: string;
  prompt_id: string | null;
  manual_captcha: boolean;
  auth: { authenticated: boolean; name: string };
  preferences: Preferences;
  run: Run;
  resume: { title: string; url: string };
  queries: string[];
  summary: {
    sent: number;
    skipped: number;
    already: number;
    attention: number;
    today_sent: number;
  } | null;
  history: PageData<HistoryRow>;
  history_error: string | null;
  candidate_count: number;
  profiles?: {
    selected: string | null;
    items: {
      id: string;
      name: string;
      resume_id: string;
      resume_title: string;
      queries: string[];
      search_mode: string;
      letter_mode: string;
      letter_text: string;
    }[];
  };
  resumes?: { id: string; title: string }[];
  queue?: {
    id: string;
    state: string;
    sent: number;
    remaining: number;
    attention: number;
    total: number;
    max_count: number;
  } | null;
};
export type ActionData = { action: string; [key: string]: unknown };
