import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import styled from "styled-components";
import { v4 as uuid } from "uuid";
import { errToString } from "@shared/utils/error";
import { client as api } from "~/utils/ApiClient";
import { WorkhubButton as Button } from "~/components/WorkhubButton";
import useStores from "~/hooks/useStores";
import history from "~/utils/history";
import { NotFoundError } from "~/utils/errors";
import { toast } from "sonner";
import { CollectionPermission } from "@shared/types";
import { s } from "@shared/styles";
import {
  ProjectPermissionNotice,
  WorkhubNotice,
} from "~/components/WorkhubNotice";

interface Person {
  id: string;
  name: string;
  email: string;
}
interface ProjectInfo {
  collectionPermission?: string | null;
  linked: boolean;
  revision: number;
  project: {
    id: string;
    name: string;
    manager: string;
    managerSubject: string | null;
  };
  permissions: {
    manage: boolean;
    updateManager: boolean;
    deleteTaskList: boolean;
  };
  syncStatus: string;
  pendingRequestId: string | null;
  pendingOperation: {
    requestId: string;
    action: string;
    expectedParentId: string | null;
    deleteTaskList: boolean;
  } | null;
  workhubUrl: string;
  parent?: { id: string; title: string; url: string } | null;
}
interface Props {
  collectionId: string;
  embedded?: boolean;
  autoConnect?: boolean;
}
interface Mutation {
  collectionId: string;
  requestId: string;
  expectedRevision: number;
  managerSubject?: string | null;
  deleteTaskList?: boolean;
  expectedParentId?: string | null;
}

/** Project management in the authenticated Outline UI. */
export function WorkhubProject({
  collectionId,
  embedded = false,
  autoConnect = false,
}: Props) {
  const { dialogs } = useStores();
  const [info, setInfo] = useState<ProjectInfo>();
  const [people, setPeople] = useState<Person[]>([]);
  const [manager, setManager] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const pending = useRef<{ method: string; body: Mutation }>();
  const autoAttempted = useRef(false);
  const autoNotified = useRef(false);
  const notifyAutoConnection = useCallback(() => {
    if (autoNotified.current) {
      return;
    }
    autoNotified.current = true;
    const key = `workhub-project-group-notice:${collectionId}`;
    try {
      if (localStorage.getItem(key)) {
        return;
      }
      localStorage.setItem(key, "shown");
    } catch {
      // The component guard also prevents duplicates when browser storage is unavailable.
    }
    toast.success(
      "프로젝트로 연결하기 위해 ‘Connect_as_a_project’ 그룹에게 편집 권한을 부여했습니다.",
      { id: key, duration: 9000 }
    );
  }, [collectionId]);
  const storageKey = `workhub-project-request:${collectionId}`;
  const load = useCallback(async () => {
    const response: { data: ProjectInfo } = await api.post(
      "/workhub.projectInfo",
      { collectionId }
    );
    if (response.data.permissions.updateManager) {
      const candidates: { data: { people: Person[] } } = await api.post(
        "/workhub.projectManagers",
        { collectionId }
      );
      setPeople(candidates.data.people);
      const capabilities: { data: { subject: string } } = await api.post(
        "/workhub.capabilities"
      );
      setManager(
        response.data.linked
          ? response.data.project.managerSubject ||
              candidates.data.people.find(
                (p) => p.email === response.data.project.manager
              )?.id ||
              ""
          : candidates.data.people.find(
              (p) => p.id === capabilities.data.subject
            )?.id || ""
      );
    } else {
      setPeople([]);
      setManager("");
    }
    setInfo(response.data);
  }, [collectionId]);
  useEffect(() => {
    try {
      const saved: { method: string; body: Mutation } | null = JSON.parse(
        sessionStorage.getItem(storageKey) || "null"
      );
      if (
        saved &&
        ["projectLink", "projectManagerUpdate", "projectUnlink"].includes(
          saved.method
        ) &&
        saved.body.collectionId === collectionId
      ) {
        pending.current = saved;
        setNotice(
          "완료를 확인하지 못한 요청이 있습니다. 같은 요청 재시도로 결과를 확인하세요."
        );
      }
    } catch {
      sessionStorage.removeItem(storageKey);
    }
    void load().catch((e) => setError(errToString(e)));
  }, [load, collectionId, storageKey]);
  const handleRefresh = async () => {
    setBusy(true);
    setError("");
    try {
      await load();
    } catch (e) {
      setError(errToString(e));
    } finally {
      setBusy(false);
    }
  };
  const handleMutation = useCallback(
    async (method: string) => {
      if (!info || busy) {
        return;
      }
      setBusy(true);
      setError("");
      setNotice("");
      try {
        if (!pending.current) {
          const body: Mutation = {
            collectionId,
            requestId: uuid(),
            expectedRevision: info.revision,
          };
          if (method === "projectUnlink") {
            body.deleteTaskList = deleting;
            body.expectedParentId = deleting ? info.parent?.id || null : null;
          } else {
            body.managerSubject = manager || null;
          }
          pending.current = { method, body };
          sessionStorage.setItem(storageKey, JSON.stringify(pending.current));
        }
        await api.post(`/workhub.${pending.current.method}`, {
          ...pending.current.body,
        });
        if (pending.current.method === "projectLink") {
          notifyAutoConnection();
        }
        pending.current = undefined;
        sessionStorage.removeItem(storageKey);
        setConfirm(false);
        setDeleting(false);
        setNotice(
          method === "projectUnlink"
            ? "프로젝트 연결을 해제했습니다."
            : "프로젝트 설정을 저장했습니다."
        );
        await load();
      } catch (e) {
        const message = errToString(e);
        const missingGroupAccess =
          message ===
          "API 키 계정에 이 컬렉션의 문서 조회·생성·수정 권한이 없어 프로젝트로 연결할 수 없습니다.";
        setError(
          missingGroupAccess
            ? "프로젝트 연결을 위해 ‘Connect_as_a_project’ 그룹에 편집 권한을 부여하세요."
            : message
        );
        let showLinkError = pending.current?.method === "projectLink";
        // A durable request is retained on uncertain network results. Check before abandoning it.
        if (pending.current) {
          try {
            const status: { data: { operationStatus: string } } =
              await api.post("/workhub.projectOperation", {
                collectionId,
                requestId: pending.current.body.requestId,
              });
            if (status.data.operationStatus === "completed") {
              if (pending.current.method === "projectLink") {
                notifyAutoConnection();
              }
              showLinkError = false;
              pending.current = undefined;
              sessionStorage.removeItem(storageKey);
              setConfirm(false);
              setDeleting(false);
              await load();
              setError("");
              setNotice("요청이 완료되었습니다.");
            }
          } catch (lookup) {
            if (lookup instanceof NotFoundError) {
              pending.current = undefined;
              sessionStorage.removeItem(storageKey);
            }
          }
        }
        if (showLinkError) {
          dialogs.openModal({
            title: "프로젝트 연결 실패",
            content: (
              <div>
                {!missingGroupAccess && <p role="alert">{message}</p>}
                {missingGroupAccess && (
                  <>
                    <p role="alert">
                      프로젝트로 관리하려면 ‘Connect_as_a_project’ 그룹에게 이
                      컬렉션의 편집 권한을 부여해야 합니다. 다음과 같이 그룹을
                      추가하세요.
                    </p>
                    <ol>
                      <li>
                        이 창을 닫고 사이드바에서 해당 컬렉션 옆의 ⋯ 을 누르고
                        권한을 여세요.
                      </li>
                      <li>
                        ‘Connect_as_a_project’ 그룹을 검색해서 + 버튼을 누른 뒤,
                        권한을 보기 전용에서 편집 가능으로 변경하고 추가 버튼을
                        누르세요.
                      </li>
                      <li>
                        변경이 반영되면 프로젝트 관리 설정에서 프로젝트 등록을
                        다시 시도하세요.
                      </li>
                    </ol>
                    <p>
                      모든 구성원의 권한은 변경할 필요가 없으며, 이 방식을 통해
                      비공개 컬렉션도 프로젝트로 연결할 수 있습니다.
                      ‘Connect_as_a_project’ 그룹에는 ‘Admin’ 계정이 포함되어
                      있습니다. Admin 계정이 해당 프로젝트를 편집할 수 있게
                      됩니다.
                    </p>
                  </>
                )}
              </div>
            ),
          });
        }
      } finally {
        setBusy(false);
      }
    },
    [
      info,
      busy,
      collectionId,
      deleting,
      manager,
      storageKey,
      load,
      dialogs,
      notifyAutoConnection,
    ]
  );
  useEffect(() => {
    if (!autoConnect || !info || busy || autoAttempted.current) {
      return;
    }
    autoAttempted.current = true;
    if (info.linked) {
      notifyAutoConnection();
    } else if (
      info.permissions.manage &&
      !info.pendingOperation &&
      !pending.current
    ) {
      void handleMutation("projectLink");
    }
  }, [autoConnect, info, busy, handleMutation, notifyAutoConnection]);
  const handlePreview = async () => {
    setBusy(true);
    setError("");
    try {
      const response: { data: ProjectInfo } = await api.post(
        "/workhub.projectUnlinkPreview",
        { collectionId }
      );
      setInfo(response.data);
      setConfirm(true);
      setDeleting(false);
    } catch (e) {
      setError(errToString(e));
    } finally {
      setBusy(false);
    }
  };
  const handleResume = async () => {
    if (!info?.pendingOperation || busy) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.post("/workhub.projectResume", {
        collectionId,
        requestId: info.pendingOperation.requestId,
        expectedParentId: info.pendingOperation.expectedParentId,
        deleteTaskList: info.pendingOperation.deleteTaskList,
      });
      if (info.pendingOperation.action === "link") {
        notifyAutoConnection();
      }
      pending.current = undefined;
      sessionStorage.removeItem(storageKey);
      setConfirm(false);
      setDeleting(false);
      setNotice("진행 중이던 요청을 완료했습니다.");
      await load();
    } catch (e) {
      setError(errToString(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Panel data-testid="workhub-project" $embedded={embedded}>
      {!embedded && <h2>프로젝트 관리 설정</h2>}
      {error && <p role="alert">{error}</p>}
      {autoConnect && error && !info?.linked && (
        <p role="status">
          컬렉션은 생성되었고 ‘Connect_as_a_project’ 그룹의 편집 권한은
          유지됩니다. 프로젝트 연결은 아직 확인되지 않았습니다. 상태를 다시
          확인한 뒤 같은 요청으로 재시도하세요. 컬렉션을 다시 만들 필요는
          없습니다.
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      {!info ? (
        <>
          <p>프로젝트 상태를 확인하고 있습니다.</p>
          <Button intent="secondary" disabled={busy} onClick={handleRefresh}>
            다시 확인
          </Button>
        </>
      ) : (
        <>
          <h3>{info.project.name}</h3>
          <p>{info.linked ? "프로젝트 연결됨" : "연결되지 않음"}</p>
          {info.syncStatus !== "synced" && (
            <p>업무·검색 정보를 반영 중입니다. 잠시 후 다시 확인하세요.</p>
          )}
          {!info.permissions.manage ? (
            <p>
              프로젝트 연결·해제는 업무 관리자 또는 해당 컬렉션 관리 권한이 있는
              사용자가 할 수 있습니다.
            </p>
          ) : info.pendingOperation ? (
            <>
              <p role="status">
                완료되지 않은{" "}
                {info.pendingOperation.action === "unlink"
                  ? "연결 해제"
                  : "프로젝트 변경"}{" "}
                요청이 있습니다.
              </p>
              <p>
                {info.pendingOperation.deleteTaskList
                  ? "업무 목록과 하위 문서를 휴지통으로 이동하는 요청입니다. 저장된 요청의 처리 결과를 확인하고 이어서 완료합니다."
                  : "저장된 요청의 처리 결과를 확인하고 이어서 완료합니다."}
              </p>
              <Button disabled={busy} onClick={handleResume}>
                진행 중 요청 확인·완료
              </Button>
            </>
          ) : info.pendingRequestId ? (
            <p role="status">
              업무 관리자의 확인이 필요한 프로젝트 변경 요청이 진행 중입니다.
              업무 관리자에게 처리 완료를 요청하세요.
            </p>
          ) : confirm ? (
            <>
              <h3>프로젝트 연결 해제</h3>
              <WorkhubNotice title="주의 · 프로젝트 연결을 해제합니다">
                <p>
                  업무 칸반, 수정이 사라집니다. 또한 진행 통계에서 해당
                  프로젝트가 사라집니다.
                </p>
                <p>
                  컬렉션과 문서·첨부파일은 유지됩니다. 생성 시 자동으로 부여한
                  ‘Connect_as_a_project’ 그룹의 편집 권한은 회수합니다.
                </p>
                <p>같은 컬렉션을 나중에 다시 연결할 수 있습니다.</p>
              </WorkhubNotice>
              {info.permissions.updateManager && (
                <details>
                  <summary>고급 옵션</summary>
                  <label>
                    <input
                      type="checkbox"
                      data-testid="workhub-delete"
                      checked={deleting}
                      disabled={
                        busy ||
                        !!pending.current ||
                        !info.parent ||
                        !info.permissions.deleteTaskList
                      }
                      onChange={(e) => setDeleting(e.target.checked)}
                    />{" "}
                    업무 목록과 그 아래 모든 문서를 휴지통으로 이동
                  </label>
                  <p>
                    {info.parent
                      ? `대상: ${info.parent.title}. 하위 문서도 함께 이동하며 컬렉션과 업무 목록 밖의 문서는 유지됩니다.`
                      : "삭제할 업무 목록을 확인할 수 없습니다."}
                  </p>
                  {!info.permissions.deleteTaskList && (
                    <p>
                      문서 삭제 권한을 확인할 수 없어 연결만 해제할 수 있습니다.
                    </p>
                  )}
                </details>
              )}
              <Actions>
                <Button
                  intent="cancel"
                  disabled={busy || !!pending.current}
                  onClick={() => setConfirm(false)}
                >
                  취소
                </Button>
                <Button
                  intent="danger"
                  data-testid="workhub-unlink-submit"
                  disabled={busy}
                  onClick={() => handleMutation("projectUnlink")}
                >
                  {busy
                    ? "처리 중…"
                    : deleting
                      ? "문서 휴지통 이동 후 연결 해제"
                      : "연결 해제"}
                </Button>
              </Actions>
            </>
          ) : (
            <>
              {info.permissions.updateManager ? (
                <>
                  <label>
                    프로젝트 책임자
                    <select
                      aria-label="프로젝트 책임자"
                      value={manager}
                      disabled={busy || !!pending.current}
                      onChange={(e) => setManager(e.target.value)}
                    >
                      <option value="">미지정</option>
                      {people.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name} · {p.email}
                        </option>
                      ))}
                    </select>
                  </label>
                  <p>
                    해당 컬렉션에 접근할 수 있는 활성 업무 관리자를 선택하세요.
                  </p>
                </>
              ) : (
                <p>
                  프로젝트 책임자: {info.project.manager || "미지정"}. 책임자
                  지정·변경은 업무 관리자가 할 수 있습니다.
                </p>
              )}
              {!info.linked &&
                info.collectionPermission !==
                  CollectionPermission.ReadWrite && <ProjectPermissionNotice />}
              <Actions>
                {!info.linked && embedded && (
                  <Button
                    intent="cancel"
                    disabled={busy || !!pending.current}
                    onClick={() => dialogs.closeAllModals()}
                  >
                    취소
                  </Button>
                )}
                {(!info.linked ||
                  info.permissions.updateManager ||
                  !!pending.current) && (
                  <Button
                    intent="confirm"
                    data-testid="workhub-link"
                    disabled={busy}
                    onClick={() =>
                      handleMutation(
                        pending.current?.method ||
                          (info.linked ? "projectManagerUpdate" : "projectLink")
                      )
                    }
                  >
                    {busy
                      ? "처리 중…"
                      : pending.current
                        ? "같은 요청 재시도"
                        : info.linked
                          ? "책임자 저장"
                          : "프로젝트 등록"}
                  </Button>
                )}
                {info.linked && (
                  <Button
                    intent="danger"
                    data-testid="workhub-unlink"
                    disabled={busy || !!pending.current}
                    onClick={handlePreview}
                  >
                    연결 해제…
                  </Button>
                )}
              </Actions>
            </>
          )}
          <Actions>
            <Button intent="secondary" disabled={busy} onClick={handleRefresh}>
              상태 새로고침
            </Button>
            <a href={info.workhubUrl} target="_blank" rel="noreferrer">
              Workhub 열기 ↗
            </a>
          </Actions>
        </>
      )}
    </Panel>
  );
}

/** Direct links from Workhub remain usable after refreshing the page. */
export function WorkhubProjectPage() {
  const { collectionId } = useParams<{ collectionId?: string }>();
  const { collections } = useStores();
  if (collectionId) {
    return <WorkhubProject collectionId={collectionId} />;
  }
  return (
    <Panel>
      <h2>Workhub 프로젝트 관리</h2>
      <p>컬렉션을 선택해 프로젝트 등록·책임자 변경·연결 해제를 진행하세요.</p>
      {collections.orderedData.map((c) => (
        <p key={c.id}>
          <Button onClick={() => history.push(`/workhub/projects/${c.id}`)}>
            {c.name}
          </Button>
        </p>
      ))}
      <p>새 컬렉션은 Outline 사이드바의 컬렉션 추가에서 만들 수 있습니다.</p>
    </Panel>
  );
}
const Panel = styled.section<{ $embedded?: boolean }>`
  padding: ${(props) => (props.$embedded ? "0" : "24px")};
  max-width: 700px;
  margin: 0 auto;
  width: 100%;
  box-sizing: border-box;
  overflow-wrap: anywhere;
  p {
    line-height: 1.6;
  }
  select {
    display: block;
    width: 100%;
    padding: 10px;
    margin-top: 8px;
  }
  details {
    margin: 20px 0;
  }
  summary {
    cursor: pointer;
    margin-bottom: 12px;
  }
  > p[role="alert"] {
    color: ${s("danger")};
  }
`;
const Actions = styled.div`
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: center;
  margin-top: 20px;
`;
