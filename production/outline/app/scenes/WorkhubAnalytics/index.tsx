import { observer } from "mobx-react";
import { runInAction } from "mobx";
import { useEffect, useRef, useState } from "react";
import { useHistory, useLocation } from "react-router-dom";
import styled from "styled-components";
import { WorkhubButton as Button } from "~/components/WorkhubButton";
import Scene from "~/components/Scene";
import env from "~/env";
import useCurrentUser from "~/hooks/useCurrentUser";
import useCurrentTeam from "~/hooks/useCurrentTeam";
import useStores from "~/hooks/useStores";
import {
  addDays,
  calendarRange,
  hasPeriod,
  overlaps,
  peakTasks,
} from "./calendar";
import type { AnalyticsTask } from "./types";

const ownersPerPage = 5;
const percent = (value: number | null) => (value === null ? "—" : `${value}%`);
const shortDate = (key: string) =>
  `${Number(key.slice(5, 7))}/${Number(key.slice(8, 10))}`;
const filters = [
  ["all", "미완료"],
  ["total", "전체 업무"],
  ["completed", "완료"],
  ["overdue", "마감 초과"],
  ["due_soon", "마감 임박"],
  ["blocked", "장애요인"],
  ["no_due", "마감일 없음"],
];

/** A responsive, authenticated statistics scene using Outline's theme. */
export const WorkhubAnalytics = observer(function WorkhubAnalytics() {
  const { workhubAnalytics: store } = useStores(),
    user = useCurrentUser(),
    team = useCurrentTeam();
  const history = useHistory(),
    location = useLocation(),
    listRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (env.OUTLINE_ANALYTICS_ENABLED) {
      void store.initialize(user.id + ":" + team.id);
    }
  }, [store, user.id, team.id]);
  useEffect(() => {
    if (env.OUTLINE_ANALYTICS_ENABLED && store.viewer) {
      store.applyRoute(location.search);
    }
  }, [store, location.search, store.viewer?.email]);
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!document.hidden && store.viewer && store.eligible) {
        void store.load(true);
      }
    }, 20000);
    const expiry = window.setInterval(() => store.expire(), 5000);
    const handleVisibility = () => {
      if (!document.hidden && store.viewer && store.eligible) {
        void store.load(true);
      }
    };
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      window.clearInterval(timer);
      window.clearInterval(expiry);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [store]);
  const data = store.data,
    viewer = store.viewer;
  const ownerPageScope = JSON.stringify([
    store.collectionId,
    store.managed,
    store.horizon,
    user.id,
    team.id,
    data?.owners.map((person) => person.email),
  ]);
  const [ownerPagination, setOwnerPagination] = useState({
    scope: "",
    page: 1,
  });
  const ownerPageCount = Math.max(
    1,
    Math.ceil((data?.owners.length ?? 0) / ownersPerPage)
  );
  const ownerPage =
    ownerPagination.scope === ownerPageScope
      ? Math.min(ownerPagination.page, ownerPageCount)
      : 1;
  const handleOwnerPage = (direction: number) => {
    setOwnerPagination({
      scope: ownerPageScope,
      page: Math.max(1, Math.min(ownerPageCount, ownerPage + direction)),
    });
  };
  const handleRange = (
    scope: string,
    collectionId = store.collectionId,
    horizon = store.horizon
  ) => {
    const params = new URLSearchParams({ scope, horizon: String(horizon) });
    if (collectionId) {
      params.set("collectionId", collectionId);
    }
    history.push("/workhub/analytics?" + params.toString());
  };
  const handleInspect = (focus: string) => {
    store.inspectOverview(focus);
    listRef.current?.scrollIntoView({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth",
      block: "start",
    });
  };
  const handleRetry = async () => {
    if (!viewer) {
      await store.initialize(user.id + ":" + team.id, true);
    } else {
      await store.load();
    }
  };
  const overview = store.overviewSummary;
  const metrics: [string, number, string, string][] = overview
    ? [
        ["전체 업무", overview.total, "total", "전체 목록"],
        ["완료 업무", overview.completed, "completed", "완료한 업무"],
        ["미완료", overview.open, "all", "마감 초과 포함"],
        ["마감 초과", overview.overdue, "overdue", "일정 재확인"],
        [
          "마감 임박",
          overview.due_soon,
          "due_soon",
          `오늘~${store.horizon}일 후`,
        ],
      ]
    : [];
  const scopeLabel =
    data?.filter_options.projects.find((p) => p.id === store.collectionId)
      ?.name ??
    (store.managed ? "내가 관리하는 프로젝트" : "접근 가능한 전체 프로젝트");
  const stale =
    !!data &&
    (!data.sync.ok ||
      !data.sync.at ||
      Date.now() - Date.parse(data.sync.at) > 120000);
  const synced = data?.sync.at
    ? new Date(data.sync.at).toLocaleTimeString("ko-KR", {
        timeZone: "Asia/Seoul",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "확인 전";
  const name = (email: string) => store.name(email);
  const range = calendarRange(
    store.anchor || data?.as_of || "2026-10-01",
    store.calendarMode
  );
  const calendarTasks = store.calendarTasks;
  const unplanned = calendarTasks.filter((task) => !hasPeriod(task));
  const overdue = calendarTasks.filter((task) =>
    task.flags.includes("overdue")
  );
  const weekStarts = range.days
    .filter((_, i) => i % 7 === 0)
    .filter((key) => key <= range.to);
  const owners = Array.from(
    new Set(calendarTasks.map((task) => task.owner.toLowerCase()))
  ).sort((a, b) => name(a).localeCompare(name(b), "ko"));
  const handleDate = (from: string, to = from, owner?: string) => {
    store.inspect("schedule", { from, to, owner });
    listRef.current?.scrollIntoView({ block: "start" });
  };
  const handleCalendarMove = (direction: number) =>
    runInAction(() => {
      if (store.calendarMode === "week") {
        store.anchor = addDays(store.anchor, direction * 7);
      } else {
        store.anchor = new Date(
          Date.UTC(
            Number(store.anchor.slice(0, 4)),
            Number(store.anchor.slice(5, 7)) - 1 + direction,
            1
          )
        )
          .toISOString()
          .slice(0, 10);
      }
    });
  const taskLink = (task: AnalyticsTask) => (
    <a href={task.url} target="_blank" rel="noopener noreferrer">
      {task.title}
      <span aria-hidden="true"> ↗</span>
      <VisuallyHidden>새 탭에서 원문 열기</VisuallyHidden>
    </a>
  );

  return (
    <Scene title="진행 통계" centered={false}>
      <Page data-testid="outline-analytics">
        <Intro>
          <div>
            <Eyebrow>프로젝트와 업무 현황</Eyebrow>
            <h1>진행 통계</h1>
            <Muted>
              {viewer?.admin
                ? "관리 프로젝트의 진행 상황과 다음에 점검할 업무를 확인하세요."
                : "본인이 참여한 업무의 진행 상황과 일정을 확인하세요."}
            </Muted>
          </div>
          <Tools>
            <Button
              disabled={store.busy || !viewer}
              onClick={() => void store.load(true, true)}
            >
              {store.refreshing ? "원본 확인 중…" : "새로고침"}
            </Button>
          </Tools>
        </Intro>
        {!env.OUTLINE_ANALYTICS_ENABLED ? (
          <Message role="alert">진행 통계가 활성화되지 않았습니다.</Message>
        ) : (
          <>
            <Status role="status" aria-live="polite">
              <span>
                {data
                  ? `${scopeLabel} · ${viewer?.admin ? "전체 집계 / 업무 목록: " : ""}${store.owner ? name(store.owner) : "팀 전체"}`
                  : store.busy
                    ? "현황을 불러오는 중입니다…"
                    : ""}
              </span>
              <span>
                {data
                  ? `${stale ? "동기화 지연 · 마지막 확인" : "최근 동기화"} ${synced}`
                  : ""}
              </span>
            </Status>
            {(store.error || store.capabilityError) && (
              <Message role="alert">
                {data
                  ? "업데이트를 확인하지 못했습니다. 이전 수치를 표시합니다. "
                  : ""}
                {store.error || store.capabilityError}
                <Button
                  onClick={() => void handleRetry()}
                  disabled={store.busy}
                >
                  다시 확인
                </Button>
                {viewer && (
                  <Button onClick={() => handleRange("all", "")}>
                    전체 프로젝트 보기
                  </Button>
                )}
              </Message>
            )}
            {store.notice && <Message role="status">{store.notice}</Message>}
            {stale && (
              <SubtleNotice>
                원본 업데이트가 지연되고 있습니다. 아래 숫자는 마지막 동기화
                상태입니다.
              </SubtleNotice>
            )}
            {!data && store.busy && (
              <Skeleton aria-label="통계 불러오는 중">
                <div />
                <div />
                <div />
              </Skeleton>
            )}
            {data && (
              <>
                <Metrics aria-label="핵심 진행 지표">
                  <Metric
                    $primary
                    onClick={() =>
                      document
                        .getElementById("analytics-projects")
                        ?.scrollIntoView({ block: "start" })
                    }
                  >
                    <span>
                      {viewer?.admin
                        ? store.collectionId
                          ? "프로젝트 진행률"
                          : "전체 진행률"
                        : store.owner
                          ? "참여 업무 진행률"
                          : store.collectionId
                            ? "프로젝트 진행률"
                            : "전체 진행률"}
                    </span>
                    <strong data-testid="analytics-progress">
                      {percent(overview?.project_progress ?? null)}
                    </strong>
                    <small>
                      {viewer?.admin
                        ? "선택 프로젝트 범위의 전체 업무 기준"
                        : store.owner
                          ? `${name(store.owner)}의 참여 업무 기준`
                          : `${data.summary.projects_measured} / ${data.summary.projects_total}개 프로젝트 집계`}
                    </small>
                    <Track>
                      {overview?.project_progress !== null &&
                        overview?.project_progress !== undefined && (
                          <Fill
                            style={{ width: `${overview.project_progress}%` }}
                          />
                        )}
                    </Track>
                  </Metric>
                  {metrics.map(([label, value, focus, note]) => (
                    <Metric
                      key={focus}
                      $risk={focus === "overdue" && value > 0}
                      onClick={() => handleInspect(focus)}
                    >
                      <span>{label}</span>
                      <strong data-testid={`metric-${focus}`}>
                        {value}
                        <em>건</em>
                      </strong>
                      <small>
                        {note}
                        <span aria-hidden="true"> →</span>
                      </small>
                    </Metric>
                  ))}
                </Metrics>
                {!data.filter_options.projects.length && (
                  <Message>
                    {store.managed
                      ? "관리하는 프로젝트가 없습니다. 접근 가능한 전체 프로젝트를 확인하세요."
                      : "접근 가능한 연결 프로젝트가 없습니다."}
                    {store.managed && (
                      <Button onClick={() => handleRange("all", "")}>
                        전체 프로젝트 보기
                      </Button>
                    )}
                    {viewer?.admin && (
                      <External href="/workhub/projects">
                        프로젝트 관리
                      </External>
                    )}
                  </Message>
                )}
                {data.summary.total === 0 &&
                  data.filter_options.projects.length > 0 && (
                    <SubtleNotice>
                      {!viewer?.admin
                        ? "본인 참여 업무가 없습니다. 다른 프로젝트를 확인하세요."
                        : store.owner
                          ? "이 담당자의 참여 업무가 없습니다. 담당자 선택을 해제하거나 다른 프로젝트를 확인하세요."
                          : "표시할 업무가 없습니다. 프로젝트의 업무 목록에서 새 업무를 등록하세요."}
                    </SubtleNotice>
                  )}
                <Section id="analytics-projects">
                  <SectionTitle>
                    <div>
                      <h2>프로젝트 현황</h2>
                      <Muted>
                        {viewer?.admin
                          ? "담당자 선택과 무관한 프로젝트 전체 업무 기준"
                          : store.owner
                            ? "선택 담당자의 참여 업무 기준"
                            : "진행률과 마감 위험을 함께 비교하세요."}
                      </Muted>
                    </div>
                    {store.collectionId && (
                      <Button
                        onClick={() =>
                          handleRange(store.managed ? "managed" : "all", "")
                        }
                      >
                        전체 프로젝트
                      </Button>
                    )}
                  </SectionTitle>
                  <Panel>
                    <ProjectHeader>
                      <span>프로젝트 · 책임자</span>
                      <span>진행률</span>
                      <span>완료 / 전체</span>
                      <span>마감 초과</span>
                    </ProjectHeader>
                    {store.overviewProjects.map((project) => (
                      <ProjectRow
                        key={project.id}
                        aria-label={`${project.name} 통계 보기`}
                        aria-pressed={store.collectionId === project.id}
                        onClick={() =>
                          handleRange(
                            store.managed ? "managed" : "all",
                            store.collectionId === project.id ? "" : project.id
                          )
                        }
                      >
                        <ProjectName>
                          <ProjectMark>{project.name.slice(0, 1)}</ProjectMark>
                          <div>
                            <b>{project.name}</b>
                            <small>
                              책임자 ·{" "}
                              {project.manager
                                ? name(project.manager)
                                : "미지정"}
                            </small>
                          </div>
                        </ProjectName>
                        <div>
                          <b>{percent(project.average_progress)}</b>
                          <Track aria-hidden="true">
                            {project.average_progress !== null && (
                              <Fill
                                style={{
                                  width: `${project.average_progress}%`,
                                }}
                              />
                            )}
                          </Track>
                        </div>
                        <div>
                          <b>
                            {project.completed}
                            <Quiet> / {project.total}</Quiet>
                          </b>
                          <MobileLabel>완료 업무</MobileLabel>
                        </div>
                        <div>
                          <Risk $active={project.overdue > 0}>
                            {project.overdue}건
                          </Risk>
                          <MobileLabel>마감 초과</MobileLabel>
                        </div>
                      </ProjectRow>
                    ))}
                    {!store.overviewProjects.length && (
                      <Empty>표시할 프로젝트가 없습니다.</Empty>
                    )}
                  </Panel>
                </Section>
                <Workspace $personal={!viewer?.admin}>
                  <Section ref={listRef} id="analytics-tasks">
                    <SectionTitle>
                      <div>
                        <h2>
                          점검할 업무{" "}
                          <Count>{store.filteredTasks.length}</Count>
                        </h2>
                        <Muted>업무명을 누르면 Outline 원문이 열립니다.</Muted>
                      </div>
                    </SectionTitle>
                    <Panel>
                      <ListTools>
                        <FilterButtons aria-label="업무 목록 필터">
                          {filters.map(([focus, label]) => (
                            <button
                              key={focus}
                              aria-pressed={store.focus === focus}
                              onClick={() => store.inspect(focus)}
                            >
                              {label}
                            </button>
                          ))}
                        </FilterButtons>
                        <Search
                          type="search"
                          placeholder="업무 · 프로젝트 · 담당자 검색"
                          aria-label="업무 목록 검색"
                          value={store.search}
                          onChange={(event) =>
                            runInAction(() => {
                              store.search = event.target.value;
                              store.page = 1;
                            })
                          }
                        />
                      </ListTools>
                      {store.selection && store.focus === "schedule" && (
                        <SelectionLabel>
                          {shortDate(store.selection.from)}–
                          {shortDate(store.selection.to)} 일정
                          {store.selection.owner
                            ? ` · ${name(store.selection.owner)}`
                            : ""}
                          <button onClick={() => store.inspect("all")}>
                            선택 해제
                          </button>
                        </SelectionLabel>
                      )}
                      <TaskList aria-label="업무 목록" tabIndex={0}>
                        {store.filteredTasks
                          .slice((store.page - 1) * 20, store.page * 20)
                          .map((task) => (
                            <TaskRow key={task.id}>
                              <TaskHeading>
                                <div>
                                  <b>{taskLink(task)}</b>
                                  <small>
                                    {task.collectionName} · {name(task.owner)}
                                  </small>
                                </div>
                                <TaskNumbers>
                                  <b>{task.progress}</b>
                                  <Risk
                                    $active={task.flags.includes("overdue")}
                                  >
                                    {task.due
                                      ? shortDate(task.due)
                                      : "마감 미정"}
                                  </Risk>
                                  <small>
                                    {task.days_remaining === null
                                      ? "일정 확인 필요"
                                      : task.days_remaining < 0
                                        ? `${-task.days_remaining}일 초과`
                                        : task.days_remaining === 0
                                          ? "오늘 마감"
                                          : `${task.days_remaining}일 남음`}
                                  </small>
                                </TaskNumbers>
                              </TaskHeading>
                              <TaskMeta>
                                <Badge>{task.status}</Badge>
                                <span>남은 기준 {task.remaining}개</span>
                                {task.flags.includes("blocked") && (
                                  <Risk $active>장애요인</Risk>
                                )}
                              </TaskMeta>
                              <TaskDetails>
                                <summary>완료 기준과 다음 행동</summary>
                                <DetailBody>
                                  {task.criteria.map((criterion) => (
                                    <Criterion key={criterion.id}>
                                      <Badge>{criterion.state}</Badge>
                                      <span>{criterion.title}</span>
                                      <Quiet>{name(criterion.owner)}</Quiet>
                                    </Criterion>
                                  ))}
                                  {!task.criteria.length && (
                                    <Muted>등록된 완료 기준이 없습니다.</Muted>
                                  )}
                                  {task.flags.includes("blocked") && (
                                    <p>
                                      <b>장애요인</b> · {task.blocker}
                                    </p>
                                  )}
                                  <p>
                                    <b>
                                      {task.next_is_suggestion
                                        ? "점검 제안"
                                        : "다음 행동"}
                                    </b>{" "}
                                    · {task.next}
                                  </p>
                                </DetailBody>
                              </TaskDetails>
                            </TaskRow>
                          ))}
                        {!store.filteredTasks.length && (
                          <Empty>조건에 맞는 업무가 없습니다.</Empty>
                        )}
                      </TaskList>
                      {store.filteredTasks.length > 20 && (
                        <Pagination>
                          <Button
                            disabled={store.page === 1}
                            onClick={() =>
                              runInAction(() => {
                                store.page--;
                              })
                            }
                          >
                            이전
                          </Button>
                          <span>
                            {store.page} /{" "}
                            {Math.ceil(store.filteredTasks.length / 20)} 페이지
                          </span>
                          <Button
                            disabled={
                              store.page * 20 >= store.filteredTasks.length
                            }
                            onClick={() =>
                              runInAction(() => {
                                store.page++;
                              })
                            }
                          >
                            다음
                          </Button>
                        </Pagination>
                      )}
                    </Panel>
                  </Section>
                  {viewer?.admin && (
                    <Section>
                      <SectionTitle>
                        <div>
                          <h2>
                            담당자 현황 <Count>{data.owners.length}</Count>
                          </h2>
                          <Muted>
                            {data.owners_scope === "project_members"
                              ? "선택 프로젝트 구성원 전체"
                              : "현재 조회 범위의 참여자"}
                          </Muted>
                        </div>
                        {data.owners.length > ownersPerPage && (
                          <Tools role="group" aria-label="담당자 현황 페이지">
                            <Button
                              aria-label="이전 담당자 페이지"
                              aria-controls="analytics-owners"
                              disabled={ownerPage === 1}
                              onClick={() => handleOwnerPage(-1)}
                            >
                              ←
                            </Button>
                            <span aria-live="polite" aria-atomic="true">
                              {ownerPage} / {ownerPageCount}
                            </span>
                            <Button
                              aria-label="다음 담당자 페이지"
                              aria-controls="analytics-owners"
                              disabled={ownerPage === ownerPageCount}
                              onClick={() => handleOwnerPage(1)}
                            >
                              →
                            </Button>
                          </Tools>
                        )}
                      </SectionTitle>
                      <Panel id="analytics-owners">
                        {data.owners
                          .slice(
                            (ownerPage - 1) * ownersPerPage,
                            ownerPage * ownersPerPage
                          )
                          .map((person) => (
                            <OwnerRow
                              key={person.email}
                              aria-pressed={store.owner === person.email}
                              onClick={() =>
                                store.selectOwner(
                                  store.owner === person.email
                                    ? ""
                                    : person.email
                                )
                              }
                            >
                              <OwnerHead>
                                <b>{name(person.email)}</b>
                                <small>전체 {person.tasks}건</small>
                              </OwnerHead>
                              <Stack aria-hidden="true">
                                <StackPart
                                  $tone="done"
                                  style={{ flex: person.tasks_completed }}
                                />
                                <StackPart
                                  $tone="late"
                                  style={{ flex: person.tasks_overdue }}
                                />
                                <StackPart
                                  $tone="open"
                                  style={{ flex: person.tasks_pending }}
                                />
                              </Stack>
                              <OwnerLegend>
                                <span>
                                  완료 <b>{person.tasks_completed}</b>
                                </span>
                                <span>
                                  초과 <b>{person.tasks_overdue}</b>
                                </span>
                                <span title="마감 초과 제외">
                                  미완료 <b>{person.tasks_pending}</b>
                                </span>
                              </OwnerLegend>
                            </OwnerRow>
                          ))}
                        {!data.owners.length && (
                          <Empty>표시할 담당자가 없습니다.</Empty>
                        )}
                      </Panel>
                      <Footnote>
                        미완료는 초과를 제외한 건수입니다. 공동 업무는
                        참여자마다 포함됩니다.
                      </Footnote>
                    </Section>
                  )}
                </Workspace>
                <Section>
                  <SectionTitle>
                    <div>
                      <h2>{viewer?.admin ? "업무 일정" : "내 업무 일정"}</h2>
                      <Muted>
                        {viewer?.admin
                          ? "시작일부터 마감일까지의 계획 기간"
                          : "프로젝트 범위 안의 본인 참여 업무"}
                      </Muted>
                    </div>
                    <Segments>
                      <button
                        aria-pressed={store.calendarMode === "week"}
                        onClick={() =>
                          runInAction(() => {
                            store.calendarMode = "week";
                          })
                        }
                      >
                        주간
                      </button>
                      <button
                        aria-pressed={store.calendarMode === "month"}
                        onClick={() =>
                          runInAction(() => {
                            store.calendarMode = "month";
                          })
                        }
                      >
                        월간
                      </button>
                    </Segments>
                  </SectionTitle>
                  <Panel>
                    <CalendarToolbar>
                      <Tools>
                        <Button
                          aria-label="이전 일정 기간"
                          onClick={() => handleCalendarMove(-1)}
                        >
                          ‹
                        </Button>
                        <b>
                          {range.from.slice(0, 4)}년{" "}
                          {store.calendarMode === "month"
                            ? `${Number(range.from.slice(5, 7))}월`
                            : `${shortDate(range.from)}–${shortDate(range.to)}`}
                        </b>
                        <Button
                          aria-label="다음 일정 기간"
                          onClick={() => handleCalendarMove(1)}
                        >
                          ›
                        </Button>
                        <Button
                          onClick={() =>
                            runInAction(() => {
                              store.anchor = data.as_of;
                            })
                          }
                        >
                          오늘
                        </Button>
                      </Tools>
                      <Tools>
                        <TextButton
                          onClick={() => {
                            store.inspect("calendar_overdue");
                            listRef.current?.scrollIntoView({ block: "start" });
                          }}
                        >
                          마감 초과 {overdue.length}건
                        </TextButton>
                        <TextButton
                          onClick={() => {
                            store.inspect("unplanned");
                            listRef.current?.scrollIntoView({ block: "start" });
                          }}
                        >
                          기간 미설정 {unplanned.length}건
                        </TextButton>
                      </Tools>
                    </CalendarToolbar>
                    <CalendarScroll
                      tabIndex={0}
                      role="region"
                      aria-label="업무 기간 캘린더"
                    >
                      <CalendarGrid>
                        {["월", "화", "수", "목", "금", "토", "일"].map(
                          (day) => (
                            <Weekday key={day}>{day}</Weekday>
                          )
                        )}
                        {range.days.map((key) => {
                          const tasks = calendarTasks.filter((task) =>
                            overlaps(task, key, key)
                          );
                          const outside = key < range.from || key > range.to;
                          return (
                            <Day
                              key={key}
                              $outside={outside}
                              $today={key === data.as_of}
                            >
                              <DateButton
                                disabled={outside}
                                aria-label={`${key} 일정 ${tasks.length}건`}
                                aria-current={
                                  key === data.as_of ? "date" : undefined
                                }
                                onClick={() => handleDate(key)}
                              >
                                {Number(key.slice(8, 10))}
                                <small>
                                  {!outside && tasks.length
                                    ? `${tasks.length}건`
                                    : ""}
                                </small>
                              </DateButton>
                              {!outside &&
                                tasks.slice(0, 3).map((task) => (
                                  <CalendarTask
                                    key={task.id}
                                    href={task.url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    title={`${task.collectionName} · ${task.title} · ${name(task.owner)}`}
                                    $late={task.flags.includes("overdue")}
                                  >
                                    {task.title}
                                  </CalendarTask>
                                ))}
                              {!outside && tasks.length > 3 && (
                                <TextButton onClick={() => handleDate(key)}>
                                  +{tasks.length - 3}건 보기
                                </TextButton>
                              )}
                            </Day>
                          );
                        })}
                      </CalendarGrid>
                    </CalendarScroll>
                    {!!unplanned.length && (
                      <Exceptions>
                        <b>기간을 정할 업무</b>
                        <Muted>
                          시작일 또는 마감일 미설정 · 역전 일정 포함
                        </Muted>
                        {unplanned.slice(0, 5).map((task) => (
                          <Exception key={task.id}>
                            <span>
                              {taskLink(task)}
                              <small>
                                {task.collectionName} · {name(task.owner)}
                              </small>
                            </span>
                            <Quiet>
                              {task.start && task.due && task.start > task.due
                                ? "일정 순서 확인"
                                : "기간 미설정"}
                            </Quiet>
                          </Exception>
                        ))}
                        {unplanned.length > 5 && (
                          <TextButton
                            onClick={() => {
                              store.inspect("unplanned");
                              listRef.current?.scrollIntoView({
                                block: "start",
                              });
                            }}
                          >
                            전체 {unplanned.length}건 보기
                          </TextButton>
                        )}
                      </Exceptions>
                    )}
                    {viewer?.admin && owners.length > 0 && (
                      <Exceptions>
                        <b>담당자별 일정 겹침</b>
                        <Muted>
                          업무 담당자 기준 · 구간별 최대 동시 업무 수
                        </Muted>
                        <Distribution
                          role="region"
                          tabIndex={0}
                          aria-label="담당자별 일정 겹침"
                        >
                          <table>
                            <thead>
                              <tr>
                                <th>담당자</th>
                                {(store.calendarMode === "week"
                                  ? range.days
                                  : weekStarts
                                ).map((day) => (
                                  <th key={day}>
                                    {shortDate(day)}
                                    {store.calendarMode === "month"
                                      ? " 주"
                                      : ""}
                                  </th>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              {owners.map((email) => (
                                <tr key={email}>
                                  <th>{name(email)}</th>
                                  {(store.calendarMode === "week"
                                    ? range.days
                                    : weekStarts
                                  ).map((day) => {
                                    const from =
                                        day < range.from ? range.from : day,
                                      end =
                                        store.calendarMode === "week"
                                          ? day
                                          : addDays(day, 6),
                                      to = end > range.to ? range.to : end;
                                    const count = peakTasks(
                                      calendarTasks.filter(
                                        (task) =>
                                          task.owner.toLowerCase() === email
                                      ),
                                      from,
                                      to
                                    );
                                    return (
                                      <td key={day}>
                                        <OverlapButton
                                          $active={count > 0}
                                          onClick={() =>
                                            handleDate(from, to, email)
                                          }
                                          aria-label={`${name(email)} ${shortDate(from)} 일정 ${count}건`}
                                        >
                                          {count || "—"}
                                        </OverlapButton>
                                      </td>
                                    );
                                  })}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </Distribution>
                        <Footnote>
                          계획 기간이 겹치는 업무 수입니다. 실제 작업 시간이나
                          과부하를 의미하지 않습니다.
                        </Footnote>
                      </Exceptions>
                    )}
                  </Panel>
                </Section>
                <Definitions>
                  <summary>숫자는 어떻게 계산하나요?</summary>
                  <DetailBody>
                    <p>
                      프로젝트 진행률은 진행률이 입력된 업무의 평균입니다. 전체
                      진행률은 집계 가능한 프로젝트 진행률의 평균이며, 업무
                      시간이나 규모에 따른 가중치는 적용하지 않습니다. 입력된
                      진행률이 없으면 ‘—’로 표시합니다.
                    </p>
                    <p>
                      관리자의 상단 지표와 프로젝트 현황은 담당자 선택과
                      무관하게 선택 프로젝트 범위의 전체 업무를 집계합니다.
                      담당자 선택은 점검할 업무와 일정에 적용합니다. 일반
                      사용자는 본인 참여 업무만 집계합니다. 공동 업무의 상태와
                      진행률은 업무 전체 기준이며, 남은 완료 기준은 선택 담당자
                      기준입니다. 마감 확인 기간은 진행률의 계산 기간을 바꾸지
                      않습니다.
                    </p>
                    <p>
                      마감 초과는 한국 날짜의 오늘보다 마감일이 이전인 미완료
                      업무입니다. 마감 임박은 오늘부터 선택한 {data.horizon}일
                      후까지 포함합니다. 확정 전 보고 초안은 통계에 반영하지
                      않습니다.
                    </p>
                    <p>
                      완료 기준 {data.summary.criteria_done} /{" "}
                      {data.summary.criteria_total}개 · 달성률{" "}
                      {percent(data.summary.criteria_progress)} · 업무 완료율{" "}
                      {percent(data.summary.completion_rate)}
                    </p>
                    <p>
                      문서 확인 필요 {data.summary.invalid}건 · 기준 없는 업무{" "}
                      {data.summary.no_criteria}건 · 진행률 없는 업무{" "}
                      {data.summary.missing_progress}건
                    </p>
                    {data.invalid_tasks.map((task) => (
                      <p key={task.id}>
                        <a
                          href={task.url}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          {task.title} ↗
                        </a>{" "}
                        · {task.error}
                      </p>
                    ))}
                    <p>
                      {Object.entries(data.summary.states)
                        .map(([state, count]) => `${state} ${count}건`)
                        .join(" · ")}
                    </p>
                  </DetailBody>
                </Definitions>
              </>
            )}
            {viewer && (
              <Section id="analytics-project-filter" aria-label="조회 조건">
                <SectionTitle>
                  <div>
                    <h2>조회 조건</h2>
                    <Muted>
                      {viewer.admin
                        ? "프로젝트, 담당자와 마감 확인 기간을 변경하세요."
                        : "프로젝트와 마감 확인 기간을 변경하세요."}
                    </Muted>
                  </div>
                </SectionTitle>
                <ProjectControls aria-label="프로젝트 조회 조건">
                  {viewer.admin && (
                    <label>
                      프로젝트 범위
                      <select
                        aria-label="프로젝트 범위"
                        value={store.managed ? "managed" : "all"}
                        onChange={(event) =>
                          handleRange(event.target.value, "")
                        }
                      >
                        <option value="managed">내가 관리하는 프로젝트</option>
                        <option value="all">접근 가능한 전체 프로젝트</option>
                      </select>
                    </label>
                  )}
                  <label>
                    프로젝트
                    <select
                      aria-label="프로젝트"
                      value={store.collectionId}
                      onChange={(event) =>
                        handleRange(
                          store.managed ? "managed" : "all",
                          event.target.value
                        )
                      }
                    >
                      <option value="">전체 프로젝트</option>
                      {data?.filter_options.projects.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                        </option>
                      ))}
                      {store.collectionId && !data && (
                        <option value={store.collectionId}>
                          선택한 프로젝트
                        </option>
                      )}
                    </select>
                  </label>
                </ProjectControls>
                <Controls aria-label="통계 조회 조건">
                  {viewer.admin && (
                    <label>
                      담당자
                      <select
                        aria-label="담당자"
                        value={store.owner}
                        onChange={(event) =>
                          store.selectOwner(event.target.value)
                        }
                      >
                        <option value="">전체 담당자</option>
                        {Array.from(
                          new Map(
                            [
                              ...(data?.owner_options ?? []),
                              { email: viewer.email, name: viewer.name },
                            ].map((person) => [person.email, person])
                          ).values()
                        ).map((person) => (
                          <option key={person.email} value={person.email}>
                            {person.name}
                          </option>
                        ))}
                        {store.owner &&
                          !data &&
                          store.owner !== viewer.email && (
                            <option value={store.owner}>선택한 담당자</option>
                          )}
                      </select>
                    </label>
                  )}
                  {viewer.admin && (
                    <Segments aria-label="담당자 범위">
                      <button
                        aria-pressed={!store.owner}
                        onClick={() => store.selectOwner("")}
                      >
                        팀 전체
                      </button>
                      <button
                        aria-pressed={store.owner === viewer.email}
                        onClick={() => store.selectOwner(viewer.email)}
                      >
                        내 업무
                      </button>
                    </Segments>
                  )}
                  <label>
                    마감 확인 기간
                    <Segments>
                      <button
                        aria-label="7일"
                        aria-pressed={store.horizon === 7}
                        onClick={() =>
                          handleRange(
                            store.managed ? "managed" : "all",
                            store.collectionId,
                            7
                          )
                        }
                      >
                        7일
                      </button>
                      <button
                        aria-label="30일"
                        aria-pressed={store.horizon === 30}
                        onClick={() =>
                          handleRange(
                            store.managed ? "managed" : "all",
                            store.collectionId,
                            30
                          )
                        }
                      >
                        30일
                      </button>
                    </Segments>
                  </label>
                </Controls>
              </Section>
            )}
          </>
        )}
      </Page>
    </Scene>
  );
});
export default WorkhubAnalytics;

const Page = styled.main`
  max-width: 1440px;
  margin: 0 auto;
  padding: 40px 48px 64px;
  color: ${(p) => p.theme.text};
  font-variant-numeric: tabular-nums;
  h1 {
    font-size: 30px;
    line-height: 1.25;
    margin: 6px 0 10px;
    font-weight: 650;
    letter-spacing: -0.7px;
  }
  h2 {
    font-size: 18px;
    margin: 0 0 5px;
    font-weight: 600;
  }
  button,
  input,
  select {
    font: inherit;
  }
  button,
  a,
  input,
  select,
  summary {
    &:focus-visible {
      outline: 2px solid ${(p) => p.theme.accent};
      outline-offset: 3px;
    }
  }
  a {
    color: inherit;
    text-decoration: none;
    &:hover {
      color: ${(p) => p.theme.accent};
      text-decoration: underline;
    }
  }
  @media (max-width: 900px) {
    padding: 28px 24px 48px;
  }
  @media (max-width: 540px) {
    padding: 22px 16px 40px;
    h1 {
      font-size: 26px;
    }
  }
`;
const Intro = styled.div`
  display: flex;
  gap: 24px;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 28px;
  @media (max-width: 760px) {
    flex-direction: column;
    gap: 14px;
  }
`;
const Eyebrow = styled.div`
  font-size: 12px;
  color: ${(p) => p.theme.textTertiary};
  font-weight: 500;
`;
const Muted = styled.p`
  font-size: 13px;
  color: ${(p) => p.theme.textSecondary};
  margin: 0;
  line-height: 1.6;
`;
const Quiet = styled.span`
  color: ${(p) => p.theme.textSecondary};
  font-weight: 400;
`;
const Tools = styled.div`
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 13px;
`;
const External = styled.a`
  font-size: 13px;
  color: ${(p) => p.theme.textSecondary} !important;
`;
const Controls = styled.div`
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 14px;
  padding: 18px 20px;
  background: ${(p) => p.theme.backgroundSecondary};
  border-radius: 10px;
  label {
    display: flex;
    flex: 1 1 170px;
    min-width: 0;
    flex-direction: column;
    gap: 7px;
    color: ${(p) => p.theme.textSecondary};
    font-size: 12px;
  }
  label:last-child {
    flex: 0 0 auto;
  }
  select {
    width: 100%;
    min-width: 0;
    height: 34px;
    padding: 5px 26px 5px 9px;
    color: ${(p) => p.theme.text};
    border: 1px solid ${(p) => p.theme.divider};
    border-radius: 6px;
    background: ${(p) => p.theme.background};
  }
  @media (max-width: 540px) {
    gap: 12px;
    padding: 14px;
    label {
      flex-basis: 100%;
    }
  }
`;
const ProjectControls = styled(Controls)`
  margin-bottom: 14px;
  label,
  label:last-child {
    flex: 1 1 240px;
    max-width: 520px;
  }
`;
const Segments = styled.div`
  display: flex;
  width: fit-content;
  border: 1px solid ${(p) => p.theme.divider};
  background: ${(p) => p.theme.background};
  border-radius: 6px;
  padding: 2px;
  button {
    cursor: pointer;
    border: 0;
    border-radius: 4px;
    background: transparent;
    color: ${(p) => p.theme.textSecondary};
    padding: 6px 12px;
    font-size: 12px;
    white-space: nowrap;
    &[aria-pressed="true"] {
      background: ${(p) => p.theme.backgroundSecondary};
      color: ${(p) => p.theme.text};
      font-weight: 600;
    }
  }
`;
const Status = styled.div`
  display: flex;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  color: ${(p) => p.theme.textTertiary};
  font-size: 12px;
  min-height: 42px;
  padding: 12px 2px;
`;
const Metrics = styled.div`
  display: grid;
  grid-template-columns: 1.6fr repeat(5, 1fr);
  gap: 12px;
  margin: 2px 0 32px;
  @media (max-width: 1160px) {
    grid-template-columns: repeat(3, 1fr);
  }
  @media (max-width: 620px) {
    grid-template-columns: repeat(2, 1fr);
    gap: 10px;
  }
`;
const Metric = styled.button<{ $primary?: boolean; $risk?: boolean }>`
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 12px;
  min-width: 0;
  padding: 20px 18px;
  text-align: left;
  border: 1px solid ${(p) => (p.$primary ? p.theme.accent : p.theme.divider)};
  border-radius: 10px;
  background: ${(p) => p.theme.background};
  color: ${(p) => p.theme.text};
  cursor: pointer;
  span {
    font-size: 12px;
    color: ${(p) => p.theme.textSecondary};
  }
  strong {
    font-size: ${(p) => (p.$primary ? "38px" : "32px")};
    font-weight: 650;
    letter-spacing: -1px;
    line-height: 1.1;
    color: ${(p) =>
      p.$risk ? p.theme.danger : p.$primary ? p.theme.accent : p.theme.text};
    white-space: nowrap;
  }
  em {
    font-size: 12px;
    font-weight: 400;
    font-style: normal;
    color: ${(p) => p.theme.textSecondary};
    margin-left: 5px;
    letter-spacing: 0;
  }
  small {
    font-size: 11px;
    color: ${(p) => p.theme.textTertiary};
  }
  &:hover {
    background: ${(p) => p.theme.backgroundSecondary};
  }
  @media (max-width: 620px) {
    padding: 17px 14px;
  }
`;
const Track = styled.div`
  height: 5px;
  width: 100%;
  background: ${(p) => p.theme.backgroundSecondary};
  border-radius: 5px;
  overflow: hidden;
  margin-top: 7px;
`;
const Fill = styled.div`
  height: 100%;
  border-radius: inherit;
  background: ${(p) => p.theme.accent};
`;
const Section = styled.section`
  min-width: 0;
  margin: 0 0 30px;
  scroll-margin-top: 70px;
`;
const SectionTitle = styled.div`
  display: flex;
  gap: 12px;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
  flex-wrap: wrap;
`;
const Panel = styled.div`
  border: 1px solid ${(p) => p.theme.divider};
  border-radius: 10px;
  overflow: hidden;
  background: ${(p) => p.theme.background};
`;
const ProjectHeader = styled.div`
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(100px, 1fr) 0.7fr 0.7fr;
  gap: 24px;
  padding: 12px 20px;
  background: ${(p) => p.theme.backgroundSecondary};
  color: ${(p) => p.theme.textTertiary};
  font-size: 11px;
  @media (max-width: 620px) {
    display: none;
  }
`;
const ProjectRow = styled.button`
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(100px, 1fr) 0.7fr 0.7fr;
  gap: 24px;
  width: 100%;
  align-items: center;
  padding: 18px 20px;
  text-align: left;
  color: ${(p) => p.theme.text};
  background: transparent;
  border: 0;
  border-top: 1px solid ${(p) => p.theme.divider};
  cursor: pointer;
  b {
    font-weight: 550;
    font-size: 14px;
  }
  &:hover,
  &[aria-pressed="true"] {
    background: ${(p) => p.theme.backgroundSecondary};
  }
  @media (max-width: 620px) {
    grid-template-columns: 1fr 1fr;
    gap: 14px;
    padding: 16px;
    > div:first-child {
      grid-column: 1 / -1;
    }
  }
`;
const ProjectName = styled.div`
  display: flex;
  gap: 12px;
  min-width: 0;
  align-items: center;
  b {
    display: block;
    overflow-wrap: anywhere;
  }
  small {
    display: block;
    color: ${(p) => p.theme.textTertiary};
    font-size: 11px;
    margin-top: 5px;
  }
`;
const ProjectMark = styled.span`
  flex: 0 0 32px;
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  font-size: 13px;
  color: ${(p) => p.theme.accent};
  background: ${(p) => p.theme.backgroundSecondary};
  border: 1px solid ${(p) => p.theme.divider};
  border-radius: 7px;
`;
const MobileLabel = styled.small`
  display: none;
  color: ${(p) => p.theme.textTertiary};
  font-size: 11px;
  margin-top: 4px;
  @media (max-width: 620px) {
    display: block;
  }
`;
const Risk = styled.span<{ $active?: boolean }>`
  color: ${(p) => (p.$active ? p.theme.danger : p.theme.textSecondary)};
  font-weight: ${(p) => (p.$active ? 550 : 400)};
  font-size: 12px;
`;
const Workspace = styled.div<{ $personal: boolean }>`
  display: grid;
  grid-template-columns: ${(p) =>
    p.$personal ? "minmax(0, 1fr)" : "minmax(0, 1.8fr) minmax(260px, 1fr)"};
  gap: 24px;
  @media (max-width: 1000px) {
    grid-template-columns: minmax(0, 1fr);
    gap: 0;
  }
`;
const Count = styled.span`
  font-size: 12px;
  color: ${(p) => p.theme.textTertiary};
  font-weight: 400;
  margin-left: 6px;
`;
const ListTools = styled.div`
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  border-bottom: 1px solid ${(p) => p.theme.divider};
`;
const FilterButtons = styled.div`
  display: flex;
  gap: 5px;
  flex-wrap: wrap;
  button {
    color: ${(p) => p.theme.textSecondary};
    background: transparent;
    border: 1px solid transparent;
    border-radius: 5px;
    padding: 5px 8px;
    cursor: pointer;
    font-size: 12px;
    &[aria-pressed="true"] {
      background: ${(p) => p.theme.backgroundSecondary};
      color: ${(p) => p.theme.text};
      border-color: ${(p) => p.theme.divider};
      font-weight: 550;
    }
  }
`;
const Search = styled.input`
  padding: 9px 11px;
  border: 1px solid ${(p) => p.theme.divider};
  border-radius: 6px;
  width: 100%;
  min-width: 0;
  background: ${(p) => p.theme.background};
  color: ${(p) => p.theme.text};
  font-size: 13px !important;
`;
const TaskList = styled.div`
  max-height: 620px;
  overflow-y: auto;
  overscroll-behavior: contain;
  &:focus-visible {
    outline: 2px solid ${(p) => p.theme.accent};
    outline-offset: -2px;
  }
`;
const TaskRow = styled.article`
  padding: 17px 18px;
  border-bottom: 1px solid ${(p) => p.theme.divider};
  &:last-child {
    border-bottom: 0;
  }
`;
const TaskHeading = styled.div`
  display: flex;
  justify-content: space-between;
  gap: 16px;
  b {
    font-size: 14px;
    font-weight: 550;
    overflow-wrap: anywhere;
  }
  small {
    display: block;
    font-size: 11px;
    color: ${(p) => p.theme.textTertiary};
    margin-top: 6px;
  }
`;
const TaskNumbers = styled.div`
  flex-shrink: 0;
  text-align: right;
  > span {
    display: block;
    margin-top: 6px;
  }
`;
const TaskMeta = styled.div`
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
  font-size: 11px;
  color: ${(p) => p.theme.textSecondary};
  flex-wrap: wrap;
`;
const Badge = styled.span`
  display: inline-block;
  background: ${(p) => p.theme.backgroundSecondary};
  color: ${(p) => p.theme.textSecondary};
  border-radius: 4px;
  padding: 3px 7px;
  font-size: 11px;
  white-space: nowrap;
`;
const TaskDetails = styled.details`
  margin-top: 12px;
  summary {
    font-size: 11px;
    color: ${(p) => p.theme.textTertiary};
    cursor: pointer;
  }
`;
const DetailBody = styled.div`
  font-size: 12px;
  line-height: 1.8;
  padding-top: 10px;
  color: ${(p) => p.theme.textSecondary};
  p {
    margin: 8px 0;
    overflow-wrap: anywhere;
  }
`;
const Criterion = styled.div`
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 5px 0;
  > span:nth-child(2) {
    flex: 1 1 150px;
  }
`;
const OwnerRow = styled.button`
  display: block;
  width: 100%;
  padding: 18px;
  text-align: left;
  border: 0;
  border-bottom: 1px solid ${(p) => p.theme.divider};
  color: ${(p) => p.theme.text};
  background: transparent;
  cursor: pointer;
  &:last-child {
    border-bottom: 0;
  }
  &:hover,
  &[aria-pressed="true"] {
    background: ${(p) => p.theme.backgroundSecondary};
  }
`;
const OwnerHead = styled.div`
  display: flex;
  justify-content: space-between;
  gap: 8px;
  b {
    font-weight: 550;
    font-size: 13px;
  }
  small {
    font-size: 11px;
    color: ${(p) => p.theme.textTertiary};
  }
`;
const Stack = styled.div`
  display: flex;
  gap: 2px;
  height: 5px;
  overflow: hidden;
  border-radius: 5px;
  margin: 13px 0 10px;
  background: ${(p) => p.theme.backgroundSecondary};
`;
const StackPart = styled.span<{ $tone: string }>`
  min-width: 0;
  background: ${(p) =>
    p.$tone === "late"
      ? p.theme.danger
      : p.$tone === "done"
        ? p.theme.accent
        : p.theme.divider};
`;
const OwnerLegend = styled.div`
  display: flex;
  justify-content: space-between;
  gap: 6px;
  font-size: 11px;
  color: ${(p) => p.theme.textSecondary};
  b {
    font-weight: 550;
    margin-left: 3px;
    color: ${(p) => p.theme.text};
  }
`;
const Footnote = styled.p`
  font-size: 11px;
  line-height: 1.6;
  color: ${(p) => p.theme.textTertiary};
  margin: 10px 0 0;
`;
const CalendarToolbar = styled.div`
  display: flex;
  justify-content: space-between;
  gap: 14px;
  padding: 18px;
  flex-wrap: wrap;
  b {
    font-size: 14px;
    font-weight: 550;
  }
`;
const CalendarScroll = styled.div`
  overflow-x: auto;
`;
const CalendarGrid = styled.div`
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  min-width: 650px;
  border-top: 1px solid ${(p) => p.theme.divider};
`;
const Weekday = styled.div`
  text-align: center;
  padding: 10px;
  color: ${(p) => p.theme.textTertiary};
  font-size: 11px;
  background: ${(p) => p.theme.backgroundSecondary};
`;
const Day = styled.div<{ $outside: boolean; $today: boolean }>`
  min-height: 114px;
  padding: 8px;
  border-top: 1px solid ${(p) => p.theme.divider};
  border-right: 1px solid ${(p) => p.theme.divider};
  background: ${(p) =>
    p.$outside ? p.theme.backgroundSecondary : p.theme.background};
  box-shadow: ${(p) => (p.$today ? `inset 0 2px ${p.theme.accent}` : "none")};
  min-width: 0;
`;
const DateButton = styled.button`
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
  padding: 2px 3px 7px;
  color: ${(p) => p.theme.text};
  background: transparent;
  border: 0;
  cursor: pointer;
  font-size: 12px;
  small {
    color: ${(p) => p.theme.textTertiary};
    font-size: 10px;
  }
  &:disabled {
    color: ${(p) => p.theme.textTertiary};
    cursor: default;
  }
  &[aria-current="date"] {
    color: ${(p) => p.theme.accent};
    font-weight: 600;
  }
`;
const CalendarTask = styled.a<{ $late: boolean }>`
  display: block;
  border-left: 2px solid ${(p) => (p.$late ? p.theme.danger : p.theme.accent)};
  background: ${(p) => p.theme.backgroundSecondary};
  padding: 4px 6px;
  border-radius: 3px;
  font-size: 11px;
  margin-bottom: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
`;
const TextButton = styled.button`
  border: 0;
  padding: 3px 0;
  background: transparent;
  color: ${(p) => p.theme.textSecondary};
  font-size: 11px !important;
  cursor: pointer;
  &:hover {
    color: ${(p) => p.theme.accent};
  }
`;
const Exceptions = styled.div`
  padding: 18px;
  border-top: 1px solid ${(p) => p.theme.divider};
  > b {
    display: block;
    font-size: 13px;
    margin-bottom: 5px;
    font-weight: 550;
  }
`;
const Exception = styled.div`
  display: flex;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 12px;
  padding: 11px 0;
  border-bottom: 1px solid ${(p) => p.theme.divider};
  small {
    display: block;
    color: ${(p) => p.theme.textTertiary};
    font-size: 11px;
    margin-top: 3px;
  }
`;
const Distribution = styled.div`
  overflow-x: auto;
  margin-top: 14px;
  table {
    width: 100%;
    border-collapse: collapse;
    min-width: 600px;
    font-size: 11px;
  }
  th {
    font-weight: 500;
    padding: 9px;
    color: ${(p) => p.theme.textSecondary};
    text-align: left;
  }
  td {
    text-align: center;
    padding: 3px;
    border-top: 1px solid ${(p) => p.theme.divider};
  }
`;
const OverlapButton = styled.button<{ $active: boolean }>`
  width: 100%;
  padding: 7px;
  border: 0;
  border-radius: 4px;
  color: ${(p) => (p.$active ? p.theme.accent : p.theme.textTertiary)};
  background: ${(p) =>
    p.$active ? p.theme.backgroundSecondary : "transparent"};
  cursor: pointer;
`;
const Definitions = styled.details`
  border-top: 1px solid ${(p) => p.theme.divider};
  padding-top: 18px;
  margin-bottom: 30px;
  summary {
    cursor: pointer;
    color: ${(p) => p.theme.textSecondary};
    font-size: 13px;
  }
`;
const Message = styled.div`
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  border: 1px solid ${(p) => p.theme.divider};
  padding: 16px;
  border-radius: 8px;
  margin-bottom: 18px;
  font-size: 13px;
  line-height: 1.6;
`;
const SubtleNotice = styled.p`
  background: ${(p) => p.theme.backgroundSecondary};
  border-radius: 6px;
  padding: 12px 16px;
  font-size: 12px;
  color: ${(p) => p.theme.textSecondary};
  margin: 0 0 20px;
`;
const Empty = styled.div`
  padding: 32px 18px;
  text-align: center;
  font-size: 13px;
  color: ${(p) => p.theme.textTertiary};
`;
const Pagination = styled.div`
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 18px;
  padding: 14px;
  font-size: 12px;
  color: ${(p) => p.theme.textSecondary};
`;
const SelectionLabel = styled.div`
  padding: 10px 18px;
  background: ${(p) => p.theme.backgroundSecondary};
  font-size: 12px;
  button {
    margin-left: 12px;
    background: transparent;
    border: 0;
    cursor: pointer;
    color: ${(p) => p.theme.accent};
  }
`;
const Skeleton = styled.div`
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  div {
    height: 130px;
    border-radius: 10px;
    background: ${(p) => p.theme.backgroundSecondary};
  }
`;
const VisuallyHidden = styled.span`
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
`;
