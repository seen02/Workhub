import { observer } from "mobx-react";
import { useEffect, useRef } from "react";
import styled from "styled-components";
import { s } from "@shared/styles";
import type { DailyReportStore } from "~/stores/DailyReportStore";
import { WorkhubButton } from "~/components/WorkhubButton";

interface Props {
  store: DailyReportStore;
  onSubmit: () => void;
}

/** Renders only the existing operation dialog; the document stays in its native editor. */
export const DailyReportDialog = observer(function DailyReportDialog(
  props: Props
) {
  return props.store.modal ? <ReportDialog {...props} /> : null;
});

/** A review dialog for selecting unfinished work or moving one complete day. */
const ReportDialog = observer(function ReportDialog({
  store,
  onSubmit,
}: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  useEffect(() => {
    returnFocus.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    dialog.current?.showModal();
    return () => {
      returnFocus.current?.focus();
    };
  }, []);
  const extracting = store.modal === "extract";
  return (
    <Dialog
      ref={dialog}
      aria-labelledby="report-dialog-title"
      onCancel={(event) => {
        event.preventDefault();
        if (!store.saving) {
          store.modal = undefined;
        }
      }}
    >
      <h2 id="report-dialog-title">
        {extracting
          ? "날짜별 보고를 하위 문서로 이동"
          : store.modal === "create"
            ? "오늘 보고 만들기"
            : "미완료 업무 선택 이월"}
      </h2>
      {extracting ? (
        <p>
          {store.extractDate}의 제목과 표 전체를 하위 문서로 옮깁니다. 부모
          문서에는 날짜 제목과 링크가 남습니다.
        </p>
      ) : (
        <>
          <p>
            선택한 미완료 업무를 오늘 보고의 ‘계속 되는 작업’에 넣습니다. 완료
            항목과 참고 의견은 가져오지 않습니다.
          </p>
          <label>
            이전 보고{" "}
            <Select
              aria-label="이월할 이전 보고"
              value={store.sourceDate}
              disabled={store.saving}
              onChange={(event) => store.changeSource(event.target.value)}
            >
              {store.sources.map((day) => (
                <option key={day.date} value={day.date}>
                  {day.title}
                </option>
              ))}
            </Select>
          </label>
          <SelectionTools>
            <button
              type="button"
              disabled={store.saving}
              onClick={() => store.select(undefined, true)}
            >
              전체 선택
            </button>
            <button
              type="button"
              disabled={store.saving}
              onClick={() => store.select()}
            >
              선택 해제
            </button>
            <span>
              {store.selected.size}개 선택 / {store.source?.items.length ?? 0}개
              미완료
            </span>
          </SelectionTools>
          <Candidates>
            {store.source?.items.map((item) => (
              <Candidate key={item.id}>
                <input
                  type="checkbox"
                  disabled={store.saving}
                  checked={store.selected.has(item.id)}
                  onChange={() => store.select(item.id)}
                />
                <span>
                  <strong>{item.worker}</strong>
                  <small>{item.column}</small>
                  <span>{item.text}</span>
                </span>
              </Candidate>
            ))}
            {!store.source?.items.length && (
              <p>
                이월할 미완료 체크 항목이 없습니다. 빈 양식으로 오늘 보고를 만들
                수 있습니다.
              </p>
            )}
          </Candidates>
          {store.modal === "create" && (
            <p>
              <small>
                선택 없이 만들면 작업자와 표 양식만 가져옵니다. 오늘 보고가
                있으면 기존 보고를 엽니다.
              </small>
            </p>
          )}
        </>
      )}
      {store.error && <Message role="alert">{store.error}</Message>}
      <DialogActions>
        <WorkhubButton
          intent="cancel"
          disabled={store.saving}
          onClick={() => {
            store.modal = undefined;
          }}
        >
          취소
        </WorkhubButton>
        <WorkhubButton
          disabled={
            store.saving ||
            (!extracting && !store.source) ||
            (store.modal === "carry" && !store.selected.size)
          }
          onClick={onSubmit}
        >
          {store.saving
            ? "저장 중…"
            : extracting
              ? "하위 문서로 이동"
              : store.modal === "create"
                ? "오늘 보고 만들기"
                : `${store.selected.size}개 업무 이월`}
        </WorkhubButton>
      </DialogActions>
    </Dialog>
  );
});

const Select = styled.select`
  background: ${s("background")};
  color: ${s("text")};
  border: 1px solid ${s("divider")};
  border-radius: 6px;
  padding: 7px 10px;
  max-width: 100%;
`;
const Message = styled.p`
  font-size: 14px;
  padding: 12px 16px;
  border: 1px solid ${s("divider")};
  border-left: 3px solid ${s("accent")};
  border-radius: 6px;
`;
const Dialog = styled.dialog`
  width: min(720px, calc(100vw - 32px));
  max-height: 85vh;
  overflow: auto;
  box-sizing: border-box;
  padding: 26px;
  border: 1px solid ${s("divider")};
  border-radius: 14px;
  background: ${s("background")};
  color: ${s("text")};
  box-shadow: 0 20px 80px #0003;
  ::backdrop {
    background: #0006;
  }
  h2 {
    margin: 0 0 12px;
    font-size: 21px;
  }
  p {
    font-size: 14px;
    line-height: 1.6;
  }
  label {
    font-size: 14px;
  }
  select {
    margin-left: 10px;
  }
`;
const SelectionTools = styled.div`
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  margin: 16px 0 10px;
  font-size: 13px;
  button {
    background: transparent;
    color: ${s("accent")};
    border: 0;
    padding: 4px;
    cursor: pointer;
  }
  span {
    margin-left: auto;
    color: ${s("textSecondary")};
  }
`;
const Candidates = styled.div`
  max-height: 42vh;
  overflow: auto;
  border: 1px solid ${s("divider")};
  border-radius: 8px;
`;
const Candidate = styled.label`
  display: flex;
  gap: 12px;
  padding: 12px 14px;
  border-bottom: 1px solid ${s("divider")};
  cursor: pointer;
  input {
    margin-top: 5px;
  }
  > span {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  small {
    color: ${s("textSecondary")};
    font-size: 11px;
  }
  span span {
    white-space: pre-wrap;
    font-size: 13px;
    line-height: 1.5;
  }
`;
const DialogActions = styled.div`
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 20px;
`;
