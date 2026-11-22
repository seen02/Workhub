import { BarChart3, Bell, Bot, BriefcaseBusiness, FilePenLine, HelpCircle, History, Menu, Settings, Sparkles, X } from "lucide-react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { useState } from "react";
import { AUTH_MODE, getDemoIdentity, setDemoIdentity } from "./api";
import DashboardPage from "./pages/DashboardPage";
import ReportPage from "./pages/ReportPage";
import HistoryPage from "./pages/HistoryPage";
import "./history.css";
import "./phase3.css";

const navItems = [
  { to: "/dashboard", label: "운영 대시보드", icon: BarChart3 },
  { to: "/report", label: "업무보고 작성", icon: FilePenLine },
  { to: "/history", label: "업무보고 이력", icon: History }
];

export default function App() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [identityValue, setIdentityValue] = useState(() => {
    const identity = getDemoIdentity();
    return identity.role === "manager" ? "manager" : `employee:${identity.employeeId}`;
  });
  const isManager = identityValue === "manager";
  const changeIdentity = (value: string) => { setDemoIdentity(value); setIdentityValue(value); window.location.assign(value === "manager" ? "/dashboard" : "/report"); };

  return (
    <div className="min-h-screen bg-[#F4F7FA] text-ink">
      <aside className={`sidebar ${mobileOpen ? "sidebar-open" : ""}`}>
        <div className="brand">
          <div className="brand-mark"><Sparkles size={19} strokeWidth={2.3} /></div>
          <div><strong>flowmate</strong><span>WORK INTELLIGENCE</span></div>
          <button className="mobile-close" onClick={() => setMobileOpen(false)} aria-label="메뉴 닫기"><X size={20} /></button>
        </div>
        {AUTH_MODE === "demo" ? <div className="workspace-chip role-chip"><div className="workspace-avatar">B</div><div><span>발표용 권한 전환</span><select aria-label="발표용 권한" value={identityValue} onChange={event => changeIdentity(event.target.value)}><option value="manager">관리자</option><option value="employee:1">김진성 · 직원</option><option value="employee:2">이서연 · 직원</option><option value="employee:3">박민수 · 직원</option><option value="employee:4">최지훈 · 직원</option><option value="employee:5">정수빈 · 직원</option></select></div></div> : <div className="workspace-chip"><div className="workspace-avatar">S</div><div><span>인증 방식</span><strong>사내 SSO</strong></div></div>}
        <nav className="primary-nav" aria-label="주요 메뉴">
          <p>WORKSPACE</p>
          {navItems.filter(item => isManager || item.to !== "/dashboard").map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} onClick={() => setMobileOpen(false)} className={({ isActive }) => isActive ? "active" : ""}>
              <Icon size={19} /><span>{label}</span>
            </NavLink>
          ))}
          <p className="nav-section">MANAGEMENT</p>
          <span className="nav-placeholder"><BriefcaseBusiness size={19} /> 프로젝트</span>
          <span className="nav-placeholder"><Bot size={19} /> AI 분석 기록</span>
        </nav>
        <div className="sidebar-bottom">
          <span><HelpCircle size={18} /> 도움말</span>
          <span><Settings size={18} /> 설정</span>
          <div className="profile"><div>{isManager ? "관" : "직"}</div><p><strong>{isManager ? "관리자" : "직원 데모"}</strong><span>{isManager ? "전체 데이터 권한" : "본인 보고만 조회"}</span></p><span className="online-dot" /></div>
        </div>
      </aside>

      {mobileOpen && <button className="sidebar-backdrop" onClick={() => setMobileOpen(false)} aria-label="메뉴 닫기" />}
      <main className="app-main">
        <div className="mobile-header">
          <button onClick={() => setMobileOpen(true)} aria-label="메뉴 열기"><Menu /></button>
          <span>flowmate</span>
          <button aria-label="알림"><Bell size={20} /></button>
        </div>
        <Routes>
          <Route path="/dashboard" element={isManager ? <DashboardPage /> : <Navigate to="/report" replace />} />
          <Route path="/report" element={<ReportPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </main>
    </div>
  );
}
