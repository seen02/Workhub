"use strict";
const $ = id => document.getElementById(id);
let session = null;

function notify(text, error = false) {
  $("notice").textContent = text;
  $("notice").className = error ? "error" : "";
}

async function request(path, options = {}) {
  const response = await fetch("/api/review" + path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(session ? {"X-Rocket-User": session.user_id, "X-Rocket-Token": session.token} : {}),
      ...options.headers,
    },
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "요청을 처리하지 못했습니다.");
  return data;
}

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function sourceLink(url, label = "원문 보기") {
  const link = el("a", label, "source-link");
  link.href = url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

function formatTime(value) {
  return new Date(value).toLocaleString("ko-KR", {month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit"});
}

function fillSelect(id, options, placeholder, selected) {
  const select = $(id);
  select.replaceChildren(new Option(placeholder, ""));
  for (const option of options) {
    const value = typeof option === "string" ? option : option.key;
    const label = typeof option === "string" ? option : option.name;
    select.add(new Option(label, value, false, value === selected));
  }
  select.value = selected || "";
}

function renderFilters(data) {
  $("date-from").value = data.filters.date_from || "";
  $("date-to").value = data.filters.date_to || "";
  fillSelect("project-filter", data.filter_options.projects, "전체 프로젝트", data.filters.project);
  fillSelect("employee-filter", data.filter_options.employees, "전체 직원", data.filters.employee);
  fillSelect("status-filter", data.filter_options.statuses, "전체 상태", data.filters.status);
}

function renderTrends(points) {
  const chart = $("trends");
  chart.replaceChildren();
  if (!points.length) {
    chart.append(el("p", "선택한 기간에 진행률 데이터가 없습니다.", "empty"));
    return;
  }
  for (const point of points) {
    const column = el("article", undefined, "trend-column");
    const value = point.average_progress;
    column.title = `${point.date} · 보고 ${point.report_count}건 · 업무 ${point.task_count}건`;
    column.append(el("strong", value === null ? "–" : `${value}%`));
    const bar = el("div", undefined, "trend-bar");
    const fill = el("span");
    fill.style.height = `${value === null ? 0 : Math.max(value, 3)}%`;
    bar.append(fill);
    column.append(bar, el("small", point.date.slice(5)));
    chart.append(column);
  }
}

function render(data) {
  $("basis").textContent = `${data.basis} · ${formatTime(data.generated_at)} 갱신`;
  renderFilters(data);
  $("kpis").replaceChildren();
  const cards = [
    [data.filters.date_from || data.filters.date_to ? "조회 기간 보고" : "오늘 보고",
      `${data.filters.date_from || data.filters.date_to ? data.scope_reporter_count : data.kpis.reported_today}명`],
    ["확정 보고 직원", `${data.kpis.employee_count}명`],
    ["현재 업무", `${data.kpis.task_count}건`],
    ["기재 진행률 평균", data.kpis.average_progress === null ? "확인 필요" : `${data.kpis.average_progress}%`],
  ];
  for (const [label, value] of cards) {
    const card = el("article", undefined, "kpi");
    card.append(el("span", label), el("strong", value));
    $("kpis").append(card);
  }
  renderTrends(data.trends || []);

  $("projects").replaceChildren();
  if (!data.projects.length) $("projects").append(el("p", "확정된 프로젝트 보고가 없습니다.", "empty"));
  for (const project of data.projects) {
    const row = el("article", undefined, "project-row");
    const heading = el("div", undefined, "row-head");
    heading.append(el("strong", project.name), el("span", project.progress === null ? "확인 필요" : `${project.progress}%`));
    const track = el("div", undefined, "track");
    const fill = el("span");
    fill.style.width = `${project.progress || 0}%`;
    track.append(fill);
    const detail = el("p", `완료 ${project.done_count} · 진행 중 ${project.in_progress_count} · 예정 ${project.planned_count} · 지연 ${project.delayed_count}`);
    row.append(heading, track, detail);
    if (project.sources[0]) row.append(sourceLink(project.sources[0], "근거 원문"));
    $("projects").append(row);
  }

  $("risk-count").textContent = `${data.risks.length}건`;
  $("risks").replaceChildren();
  if (!data.risks.length) $("risks").append(el("p", "명시된 지연 또는 이슈가 없습니다.", "empty success"));
  for (const risk of data.risks) {
    const card = el("article", undefined, "risk-row");
    card.append(el("strong", risk.task), el("span", `${risk.project} · ${risk.owner}`), el("p", risk.reason), sourceLink(risk.source_url));
    $("risks").append(card);
  }

  $("employees").replaceChildren();
  for (const employee of data.employees) {
    const row = document.createElement("tr");
    const values = [employee.username, formatTime(employee.reported_at), `${employee.task_count}건`, `${employee.active_count}건`, employee.average_progress === null ? "확인 필요" : `${employee.average_progress}%`];
    values.forEach(value => row.append(el("td", value)));
    const source = document.createElement("td");
    source.append(sourceLink(employee.source_url));
    row.append(source);
    $("employees").append(row);
  }

  $("reports").replaceChildren();
  for (const report of data.recent_reports.slice(0, 8)) {
    const card = el("article", undefined, "report-card");
    const top = el("div", undefined, "row-head");
    top.append(el("strong", report.author), el("span", formatTime(report.reported_at)));
    card.append(top);
    for (const item of report.items.slice(0, 4)) {
      const progress = item.status === "IN_PROGRESS" && item.progress !== null ? ` ${item.progress}%` : "";
      card.append(el("p", `${item.task} · ${item.status_label}${progress}`));
    }
    card.append(sourceLink(report.source_url, "Rocket.Chat 원문 열기"));
    $("reports").append(card);
  }
}

async function openDashboard() {
  const params = new URLSearchParams();
  const values = {
    date_from: $("date-from").value,
    date_to: $("date-to").value,
    project: $("project-filter").value,
    employee: $("employee-filter").value,
    status: $("status-filter").value,
  };
  Object.entries(values).forEach(([key, value]) => { if (value) params.set(key, value); });
  const data = await request("/manager/dashboard" + (params.size ? `?${params}` : ""));
  $("login-panel").hidden = true;
  $("dashboard").hidden = false;
  $("refresh").hidden = false;
  $("logout").hidden = false;
  notify("");
  render(data);
}

async function restore() {
  const params = new URLSearchParams(location.search);
  const access = params.get("access");
  try {
    if (access) {
      session = await request("/manager-link-login", {method: "POST", body: JSON.stringify({token: access})});
      sessionStorage.setItem("managerDashboardSession", JSON.stringify(session));
      history.replaceState(null, "", location.pathname);
    } else {
      const saved = sessionStorage.getItem("managerDashboardSession");
      if (saved) session = JSON.parse(saved);
    }
    if (session) await openDashboard();
  } catch (error) {
    session = null;
    sessionStorage.removeItem("managerDashboardSession");
    notify(error.message, true);
  }
}

$("login").addEventListener("submit", event => {
  event.preventDefault();
  notify("로그인 중입니다.");
  request("/manager-login", {method: "POST", body: JSON.stringify({username: $("username").value, password: $("password").value})})
    .then(value => { session = value; sessionStorage.setItem("managerDashboardSession", JSON.stringify(value)); return openDashboard(); })
    .catch(error => notify(error.message, true))
    .finally(() => { $("password").value = ""; });
});
$("refresh").addEventListener("click", () => openDashboard().catch(error => notify(error.message, true)));
$("filters").addEventListener("submit", event => {
  event.preventDefault();
  notify("조회 중입니다.");
  openDashboard().catch(error => notify(error.message, true));
});
$("filter-reset").addEventListener("click", () => {
  for (const id of ["date-from", "date-to", "project-filter", "employee-filter", "status-filter"]) $(id).value = "";
  openDashboard().catch(error => notify(error.message, true));
});
$("logout").addEventListener("click", () => { sessionStorage.removeItem("managerDashboardSession"); location.reload(); });
restore();
