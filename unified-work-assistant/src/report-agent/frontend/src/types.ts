export interface EmployeeOption {
  id: number;
  name: string;
  team: string;
}

export interface ProjectOption {
  id: number;
  name: string;
  status: string;
  expected_progress: number;
}

export interface ParsedReport {
  employee: string;
  task: string;
  start_time: string | null;
  end_time: string | null;
  duration_hours: number | null;
  status: "NOT_STARTED" | "IN_PROGRESS" | "DONE" | "DELAYED";
  progress: number | null;
  issue: string | null;
  next_action: string | null;
  confidence: number;
}

export interface ReportResult {
  id: number;
  parsed: ParsedReport;
  created_at: string;
}

export interface ParseResult {
  parsed: ParsedReport;
  provider: string;
  fallback_used: boolean;
  elapsed_ms: number;
}

export interface ReportListItem {
  id: number;
  employee_id: number;
  employee: string;
  project_id: number;
  project: string;
  task: string;
  progress: number | null;
  status: ParsedReport["status"];
  next_action: string | null;
  created_at: string;
  updated_at: string;
}

export interface ReportRevision {
  id: number;
  changed_by: string;
  before: ParsedReport;
  after: ParsedReport;
  reason: string;
  created_at: string;
}

export interface ReportDetail extends ReportListItem {
  source_url?: string | null;
  review_url?: string | null;
  raw_message: string;
  parsed: ParsedReport;
  duration_hours: number | null;
  issue: string | null;
  revisions: ReportRevision[];
}

export interface LlmStatus {
  provider: string;
  model: string;
  ready: boolean;
  detail: string;
}

export interface DashboardData {
  generated_at: string;
  kpis: {
    reported_today: number;
    total_employees: number;
    average_progress: number;
    delayed_count: number;
    expected_completion_rate: number;
  };
  projects: Array<{
    id: number;
    name: string;
    progress: number | null;
    expected_progress: number;
    status: string;
  }>;
  employees: Array<{
    id: number;
    name: string;
    team: string;
    task: string;
    project: string;
    progress: number | null;
    duration_hours: number;
    next_action: string;
    status: string;
    reported: boolean;
  }>;
  summary: string;
  risks: Array<{
    task_id: number;
    project: string;
    task: string;
    owner: string;
    severity: string;
    reasons: string[];
  }>;
  trend: Array<{
    date: string;
    average_progress: number;
    report_count: number;
  }>;
}
