import { action, computed, observable, runInAction } from "mobx";
import { Node } from "prosemirror-model";
import type { DailyReportSnapshot } from "@shared/utils/dailyReport";
import type { Editor } from "~/editor";
import { reportWorkers } from "@shared/utils/dailyReport";
import { client } from "~/utils/ApiClient";

interface MutationResult {
  date: string;
  url: string;
  existing?: boolean;
  added: number;
}

/** Document-scoped report controls and optimistic-concurrency-aware mutations. */
export class DailyReportStore {
  @observable.ref data: DailyReportSnapshot | undefined;
  @observable busy = false;
  @observable saving = false;
  @observable error = "";
  @observable notice = "";
  @observable modal: "create" | "carry" | "extract" | undefined;
  @observable sourceDate = "";
  @observable extractDate = "";
  @observable.ref selected = new Set<string>();
  private generation = 0;

  constructor(
    readonly id: string,
    readonly viewerId: string
  ) {}

  /** Lists workers across inline and accessible child reports. */
  @computed get workers() {
    return reportWorkers(this.data?.days ?? []);
  }

  /** Lists previous reports that can provide a reusable table and unfinished work. */
  @computed get sources() {
    return (this.data?.days ?? [])
      .filter(
        (day) =>
          day.date < (this.data?.today ?? "") &&
          day.blocks.some((node) => node.type === "table")
      )
      .sort((a, b) => b.date.localeCompare(a.date));
  }

  /** Returns the chosen previous-day snapshot. */
  @computed get source() {
    return this.sources.find((day) => day.date === this.sourceDate);
  }

  /** Loads fresh authorized data; late responses after disposal are ignored. */
  async refresh() {
    if (this.busy) {
      return;
    }
    const generation = this.generation;
    runInAction(() => {
      this.busy = true;
      this.error = "";
    });
    try {
      const response = await client.post<{ data: DailyReportSnapshot }>(
        "/dailyReports.info",
        { id: this.id }
      );
      if (generation !== this.generation) {
        return;
      }
      runInAction(() => {
        this.data = response.data;
      });
    } catch (error) {
      if (generation === this.generation) {
        runInAction(() => {
          this.error =
            error instanceof Error
              ? error.message
              : "보고를 불러오지 못했습니다.";
          this.data = undefined;
        });
      }
    } finally {
      if (generation === this.generation) {
        runInAction(() => {
          this.busy = false;
        });
      }
    }
  }

  /** Waits for the exact live editor content to be persisted before offering a mutation. */
  async synchronize(editor: Editor): Promise<DailyReportSnapshot> {
    const generation = this.generation;
    runInAction(() => {
      this.busy = true;
      this.error = "";
    });
    try {
      for (let attempt = 0; attempt < 48; attempt++) {
        const response = await client.post<{ data: DailyReportSnapshot }>(
          "/dailyReports.info",
          { id: this.id }
        );
        if (generation !== this.generation || editor.view.isDestroyed) {
          throw new Error("문서를 닫았습니다.");
        }
        const saved = response.data.content;
        if (
          saved &&
          Node.fromJSON(editor.schema, saved).eq(editor.view.state.doc)
        ) {
          runInAction(() => {
            this.data = response.data;
          });
          return response.data;
        }
        await new Promise((resolve) => setTimeout(resolve, 250));
      }
      throw new Error(
        "편집 내용이 아직 저장되지 않았습니다. 연결 상태를 확인한 뒤 다시 실행하세요."
      );
    } finally {
      if (generation === this.generation) {
        runInAction(() => {
          this.busy = false;
        });
      }
    }
  }

  /** Opens a bounded review dialog without changing any document. */
  @action open(modal: "create" | "carry" | "extract", date = "") {
    this.modal = modal;
    this.extractDate = date;
    this.sourceDate = this.sources[0]?.date ?? "";
    this.selected = new Set();
    this.error = "";
  }

  /** Changes the source and clears selections that belonged to another snapshot. */
  @action changeSource(date: string) {
    this.sourceDate = date;
    this.selected = new Set();
  }

  /** Selects or unselects one candidate, or all candidates. */
  @action select(id?: string, all = false) {
    const next = new Set(this.selected);
    if (id) {
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
    } else {
      next.clear();
      if (all) {
        this.source?.items.forEach((item) => next.add(item.id));
      }
    }
    this.selected = next;
  }

  /** Executes one atomic operation and reloads the authoritative result. */
  async submit(): Promise<MutationResult | undefined> {
    if (this.saving || !this.data || !this.modal) {
      return undefined;
    }
    const actionName = this.modal;
    runInAction(() => {
      this.saving = true;
      this.error = "";
      this.notice = "";
    });
    try {
      const response = await client.post<{ data: MutationResult }>(
        "/dailyReports.mutate",
        {
          id: this.id,
          revision: this.data.revision,
          action: actionName,
          ...(actionName === "extract"
            ? { date: this.extractDate }
            : {
                sourceDate: this.sourceDate,
                sourceRevision: this.source?.sourceRevision,
                itemIds: [...this.selected],
              }),
        },
        { retry: false }
      );
      runInAction(() => {
        this.modal = undefined;
        this.notice =
          actionName === "extract"
            ? "날짜별 보고를 하위 문서로 옮겼습니다. 원래 자리에 링크를 남겼습니다."
            : actionName === "carry"
              ? `${response.data.added}개 업무를 이월했습니다. 이미 있는 항목은 제외했습니다.`
              : response.data.existing
                ? "오늘 보고가 이미 있어 기존 보고를 열었습니다."
                : `오늘 보고를 만들었습니다.${response.data.added ? ` 미완료 업무 ${response.data.added}개를 이월했습니다.` : ""}`;
      });
      await this.refresh();
      return response.data;
    } catch (error) {
      runInAction(() => {
        this.error =
          error instanceof Error
            ? error.message
            : "저장하지 못했습니다. 새로고침 후 다시 시도하세요.";
      });
      return undefined;
    } finally {
      runInAction(() => {
        this.saving = false;
      });
    }
  }

  /** Invalidates in-flight reads and clears document data. */
  @action dispose() {
    this.generation++;
    this.data = undefined;
    this.modal = undefined;
    this.selected = new Set();
  }
}
