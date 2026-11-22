import { useCallback, useEffect, useMemo } from "react";
import type { RefObject } from "react";
import { useHistory } from "react-router-dom";
import { toast } from "sonner";
import type { DailyReportAction } from "@shared/utils/dailyReport";
import { dailyReportToolsEnabled } from "@shared/utils/dailyReport";
import useCurrentTeam from "~/hooks/useCurrentTeam";
import type Document from "~/models/Document";
import type { Editor } from "~/editor";
import { revealEditorReport } from "~/editor/extensions/DailyReport";
import { DailyReportStore } from "~/stores/DailyReportStore";
import { DailyReportDialog } from "./DailyReports";

/** Connects native editor actions to synchronized, server-authorized report operations. */
export function useDailyReportActions(
  document: Document | undefined,
  editorRef: RefObject<Editor>,
  enabled: boolean,
  canUpdate: boolean
) {
  const history = useHistory();
  const team = useCurrentTeam({ rejectOnEmpty: false });
  const store = useMemo(
    () => new DailyReportStore(document?.id ?? "", "native-editor"),
    [document?.id]
  );
  const eligible =
    !!document &&
    enabled &&
    dailyReportToolsEnabled(team?.preferences, document.preferences) &&
    !document.isDraft &&
    !document.isArchived &&
    !document.isDeleted &&
    !!document.collectionId;
  useEffect(() => {
    if (!eligible) {
      store.dispose();
    }
    return () => store.dispose();
  }, [store, eligible]);

  const handleAction = useCallback(
    async (action: DailyReportAction, date?: string) => {
      const editor = editorRef.current;
      if (!eligible || !canUpdate || !editor || store.busy || store.saving) {
        return;
      }
      const loading = toast.loading("편집 내용 저장을 확인하는 중…");
      try {
        const snapshot = await store.synchronize(editor);
        if (!editor.props.dailyReportEnabled) {
          return;
        }
        if (!snapshot.canUpdate) {
          throw new Error("문서 편집 권한이 필요합니다.");
        }
        const today = snapshot.days.find((day) => day.date === snapshot.today);
        if (action === "create" && today) {
          if (today.movedUrl) {
            history.push(today.movedUrl);
          } else {
            revealEditorReport(editor.view, snapshot.today);
          }
          toast.info("오늘 보고가 이미 있어 기존 보고를 열었습니다.");
          return;
        }
        if (action !== "extract" && !store.sources.length) {
          throw new Error(
            "오늘보다 이전 날짜의 제목과 작업자 표가 필요합니다."
          );
        }
        store.open(action, date);
        if (
          action === "carry" &&
          date &&
          store.sources.some((source) => source.date === date)
        ) {
          store.changeSource(date);
        }
      } catch (error) {
        toast.error(
          error instanceof Error
            ? error.message
            : "보고 작업을 열지 못했습니다."
        );
      } finally {
        toast.dismiss(loading);
      }
    },
    [eligible, canUpdate, editorRef, store, history]
  );

  const handleSubmit = useCallback(async () => {
    if (!editorRef.current?.props.dailyReportEnabled) {
      return;
    }
    const result = await store.submit();
    if (!result) {
      return;
    }
    toast.success(store.notice, {
      action: { label: "문서 열기", onClick: () => history.push(result.url) },
    });
    const editor = editorRef.current;
    if (editor) {
      try {
        await store.synchronize(editor);
        revealEditorReport(editor.view, result.date);
      } catch {
        /* The saved operation succeeded; the standard collaboration connection will catch up. */
      }
    }
  }, [editorRef, store, history]);

  return {
    enabled: eligible,
    onAction: eligible && canUpdate ? handleAction : undefined,
    dialog: eligible ? (
      <DailyReportDialog store={store} onSubmit={() => void handleSubmit()} />
    ) : null,
  };
}
