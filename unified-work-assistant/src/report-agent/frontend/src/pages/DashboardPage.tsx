import {
  Activity, AlertTriangle, ArrowRight, Bot, CheckCircle2, Clock3, RefreshCw,
  Send, Sparkles, TrendingUp, UserCheck, UsersRound
} from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { DashboardData } from "../types";

const STATUS_LABEL: Record<string, string> = {
  NOT_STARTED: "시작 전",
  IN_PROGRESS: "진행 중",
  DONE: "완료",
  DELAYED: "지연"
};

function todayLabel() {
  return new Intl.DateTimeFormat("ko-KR", {
    year: "numeric", month: "long", day: "numeric", weekday: "short"
  }).format(new Date());
}

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("오늘의 업무 데이터에서 궁금한 내용을 물어보세요.");
  const [asking, setAsking] = useState(false);

  const load = async () => {
    setLoading(true);
    setError("");
    try { setData(await api.getDashboard()); }
    catch (err) { setError(err instanceof Error ? err.message : "대시보드를 불러오지 못했습니다."); }
    finally { setLoading(false); }
  };

  useEffect(() => { void load(); }, []);

  const ask = async (event: FormEvent) => {
    event.preventDefault();
    if (!question.trim() || asking) return;
    setAsking(true);
    try {
      const result = await api.chat(question);
      setAnswer(result.answer);
      setQuestion("");
    } catch (err) {
      setAnswer(err instanceof Error ? err.message : "답변을 생성하지 못했습니다.");
    } finally { setAsking(false); }
  };

  if (loading) return <DashboardSkeleton />;
  if (error || !data) return (
    <div className="center-state"><AlertTriangle /><h2>데이터를 불러오지 못했습니다</h2><p>{error}</p><button onClick={load}><RefreshCw size={17} /> 다시 시도</button></div>
  );

  const { kpis } = data;
  const kpiCards = [
    { label: "오늘 보고 인원", value: `${kpis.reported_today}`, unit: `/ ${kpis.total_employees}명`, icon: UserCheck, tone: "blue", note: "팀 보고 현황" },
    { label: "평균 진행률", value: `${kpis.average_progress}%`, unit: "", icon: TrendingUp, tone: "teal", note: "전체 업무 평균" },
    { label: "지연 업무", value: `${kpis.delayed_count}`, unit: "건", icon: AlertTriangle, tone: "orange", note: "확인이 필요해요" },
    { label: "계획 달성 업무", value: `${kpis.expected_completion_rate}%`, unit: "", icon: CheckCircle2, tone: "navy", note: "계획 대비 정상" }
  ];

  return (
    <div className="page dashboard-page">
      <header className="page-header">
        <div><span className="eyebrow">DAILY OPERATIONS</span><h1>오늘의 업무 현황</h1><p>{todayLabel()} · 마지막 업데이트 {new Date(data.generated_at).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" })}</p></div>
        <div className="header-actions"><button className="icon-button" onClick={load} aria-label="새로고침"><RefreshCw size={18} /></button><Link to="/report" className="primary-button"><span>업무보고 작성</span><ArrowRight size={17} /></Link></div>
      </header>

      <section className="kpi-grid" aria-label="핵심 지표">
        {kpiCards.map(({ label, value, unit, icon: Icon, tone, note }) => (
          <article className="kpi-card" key={label}>
            <div className={`kpi-icon ${tone}`}><Icon size={20} /></div>
            <div className="kpi-content"><span>{label}</span><strong>{value}<small>{unit}</small></strong><p>{note}</p></div>
          </article>
        ))}
      </section>

      <section className="panel trend-panel">
        <div className="panel-heading"><div><span className="section-kicker">PROGRESS TREND</span><h2>보고 기준 진행 변화</h2></div><span className="muted-label"><Activity size={14} /> 최근 {data.trend.length}일</span></div>
        <div className="trend-chart" aria-label="날짜별 평균 진행률">
          {data.trend.map(point => <div className="trend-column" key={point.date}><strong>{point.average_progress}%</strong><div><span style={{ height: `${Math.max(point.average_progress, 4)}%` }} /></div><small>{new Date(`${point.date}T00:00:00`).toLocaleDateString("ko-KR", { month: "numeric", day: "numeric" })}</small><i>{point.report_count}건</i></div>)}
        </div>
      </section>

      <div className="dashboard-grid">
        <section className="panel project-panel">
          <div className="panel-heading"><div><span className="section-kicker">PORTFOLIO</span><h2>프로젝트 진행률</h2></div><span className="muted-label">계획 대비</span></div>
          <div className="project-list">
            {data.projects.map((project) => (
              <div className="project-row" key={project.id}>
                <div className="project-meta"><div><strong>{project.name}</strong>{project.status === "DELAYED" && <span className="status-badge delayed">지연</span>}</div><span>{project.progress === null ? "확인 필요" : `${project.progress}%`}</span></div>
                <div className="progress-track"><div className={project.status === "DELAYED" ? "progress-fill delayed" : "progress-fill"} style={{ width: `${project.progress ?? 0}%` }} /><i style={{ left: `${Math.min(project.expected_progress, 99)}%` }} title={`계획 ${project.expected_progress}%`} /></div>
                <div className="progress-caption"><span>0</span><span>계획 {project.expected_progress}%</span><span>100</span></div>
              </div>
            ))}
          </div>
        </section>

        <section className="panel summary-panel">
          <div className="summary-top"><div className="ai-orb"><Sparkles size={21} /></div><div><span className="section-kicker">AI BRIEFING</span><h2>오늘의 요약</h2></div></div>
          <p className="summary-copy">{data.summary}</p>
          <div className="summary-stat"><UsersRound size={17} /><span>팀 참여율</span><strong>{Math.round(kpis.reported_today / kpis.total_employees * 100)}%</strong></div>
        </section>
      </div>

      <section className="panel employee-panel">
        <div className="panel-heading"><div><span className="section-kicker">TEAM PULSE</span><h2>직원별 진행현황</h2></div><span className="muted-label">{data.employees.length}명</span></div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>직원</th><th>담당 업무</th><th>진행률</th><th>금일 투입</th><th>다음 작업</th><th>상태</th></tr></thead>
            <tbody>
              {data.employees.map((employee) => (
                <tr key={employee.id}>
                  <td><div className="employee-cell"><div className="avatar">{employee.name.slice(-2)}</div><div><strong>{employee.name}</strong><span>{employee.team}</span></div></div></td>
                  <td><strong className="task-title">{employee.task}</strong><span className="project-name">{employee.project}</span></td>
                  <td><div className="mini-progress"><div><span style={{ width: `${employee.progress ?? 0}%` }} /></div><strong>{employee.progress === null ? "확인 필요" : `${employee.progress}%`}</strong></div></td>
                  <td><span className="duration"><Clock3 size={15} /> {employee.duration_hours}h</span></td>
                  <td>{employee.next_action}</td>
                  <td><span className={`status-badge ${employee.status.toLowerCase()}`}>{STATUS_LABEL[employee.status] || employee.status}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div className="bottom-grid">
        <section className="panel risk-panel">
          <div className="panel-heading"><div><span className="section-kicker danger">RISK SIGNAL</span><h2>리스크 알림</h2></div><span className="risk-count">{data.risks.length}</span></div>
          <div className="risk-list">
            {data.risks.slice(0, 3).map((risk) => (
              <article key={risk.task_id}>
                <div className="risk-icon"><AlertTriangle size={18} /></div>
                <div><div className="risk-title"><strong>{risk.project}</strong><span>{risk.owner}</span></div><p>{risk.task}</p><ul>{risk.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul></div>
              </article>
            ))}
          </div>
        </section>

        <section className="panel chat-panel">
          <div className="panel-heading"><div className="chat-heading"><div className="bot-icon"><Bot size={20} /></div><div><span className="section-kicker">DATA ASSISTANT</span><h2>AI 업무 비서</h2></div></div><span className="live-badge"><i /> DB 연결됨</span></div>
          <div className="chat-answer">{answer.split("\n").map((line, index) => <p key={index}>{line}</p>)}</div>
          <div className="suggestions">
            {["오늘 지연된 업무 알려줘", "김진성 오늘 뭐했어?"].map(item => <button key={item} onClick={() => setQuestion(item)}>{item}</button>)}
          </div>
          <form className="chat-form" onSubmit={ask}><input value={question} onChange={event => setQuestion(event.target.value)} placeholder="업무 데이터에 질문해보세요" aria-label="AI 업무 비서 질문" /><button disabled={!question.trim() || asking} aria-label="질문 보내기"><Send size={18} /></button></form>
        </section>
      </div>
    </div>
  );
}

function DashboardSkeleton() {
  return <div className="page"><header className="page-header"><div><div className="skeleton tiny" /><div className="skeleton title" /><div className="skeleton line" /></div></header><div className="kpi-grid">{[1,2,3,4].map(item => <div className="kpi-card skeleton-card" key={item} />)}</div><div className="dashboard-grid"><div className="panel skeleton-panel" /><div className="panel skeleton-panel" /></div></div>;
}
