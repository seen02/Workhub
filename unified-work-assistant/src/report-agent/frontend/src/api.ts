import type { DashboardData, EmployeeOption, LlmStatus, ParseResult, ParsedReport, ProjectOption, ReportDetail, ReportListItem, ReportResult } from "./types";

const API_URL = import.meta.env.VITE_API_URL || "/api";
export const AUTH_MODE = import.meta.env.VITE_AUTH_MODE || "demo";

export type DemoIdentity = { role: "manager" } | { role: "employee"; employeeId: number };

export function getDemoIdentity(): DemoIdentity {
  const value = localStorage.getItem("flowmate_demo_identity") || "manager";
  if (value.startsWith("employee:")) return { role: "employee", employeeId: Number(value.split(":")[1]) };
  return { role: "manager" };
}

export function setDemoIdentity(value: string) {
  localStorage.setItem("flowmate_demo_identity", value);
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const identity = getDemoIdentity();
  const accessToken = AUTH_MODE === "jwt" ? sessionStorage.getItem("flowmate_access_token") : null;
  const response = await fetch(`${API_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(AUTH_MODE === "demo" ? { "X-Demo-Role": identity.role } : {}),
      ...(AUTH_MODE === "demo" && identity.role === "employee" ? { "X-Demo-Employee-Id": String(identity.employeeId) } : {}),
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...options?.headers
    },
    credentials: "include",
    ...options
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || "요청을 처리하지 못했습니다.");
  }
  return response.json() as Promise<T>;
}

export const api = {
  getDashboard: () => request<DashboardData>("/dashboard"),
  getEmployees: () => request<EmployeeOption[]>("/employees"),
  getProjects: () => request<ProjectOption[]>("/projects"),
  getLlmStatus: () => request<LlmStatus>("/system/llm"),
  getAuthSession: () => request<{ mode: string; role: string; employee_id: number | null }>("/auth/session"),
  parseReport: (payload: { employee_id: number; project_id: number; raw_message: string }) =>
    request<ParseResult>("/reports/parse", { method: "POST", body: JSON.stringify(payload) }),
  submitReport: (payload: { employee_id: number; project_id: number; raw_message: string; parsed: ParsedReport }) =>
    request<ReportResult>("/reports", { method: "POST", body: JSON.stringify(payload) }),
  getReports: (filters: Record<string, string>) => {
    const params = new URLSearchParams(Object.entries(filters).filter(([, value]) => value));
    return request<{ items: ReportListItem[]; total: number }>(`/reports?${params}`);
  },
  getReport: (id: number) => request<ReportDetail>(`/reports/${id}`),
  updateReport: (id: number, payload: { task: string; status: ParsedReport["status"]; progress: number | null; duration_hours: number | null; issue: string | null; next_action: string | null; edit_reason: string }) =>
    request<ReportDetail>(`/reports/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  chat: (message: string) =>
    request<{ answer: string; sources: string[] }>("/chat", {
      method: "POST",
      body: JSON.stringify({ message })
    })
};
