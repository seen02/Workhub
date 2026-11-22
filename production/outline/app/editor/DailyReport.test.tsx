import i18next from "i18next";
import { createRef } from "react";
import ReactDOM from "react-dom";
import { act } from "react-dom/test-utils";
import { ThemeProvider } from "styled-components";
import { TextSelection } from "prosemirror-state";
import { undo } from "prosemirror-history";
import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import { richExtensions } from "@shared/editor/nodes";
import { Action, toggleFoldPluginKey } from "@shared/editor/nodes/ToggleBlock";
import { editorReportRanges } from "@shared/editor/lib/dailyReport";
import * as reportRanges from "@shared/editor/lib/dailyReport";
import light from "@shared/styles/theme";
import type { ProsemirrorData } from "@shared/types";
import { client } from "~/utils/ApiClient";
import { DailyReportStore } from "~/stores/DailyReportStore";
import {
  DailyReportExtension,
  deleteEditorReport,
  wrapEditorReport,
} from "./extensions/DailyReport";
import { Editor } from "./index";

vi.mock("~/components/Lightbox", () => ({ default: () => null }));
vi.mock("~/utils/ApiClient", () => ({ client: { post: vi.fn() } }));

const extensions = [
  ...richExtensions.filter((extension) =>
    [
      "Doc",
      "Paragraph",
      "Text",
      "Heading",
      "HardBreak",
      "ToggleBlock",
      "History",
      "Table",
      "TableCell",
      "TableHeader",
      "TableRow",
    ].includes(extension.name)
  ),
  DailyReportExtension,
];
const p = (text: string): ProsemirrorData => ({
  type: "paragraph",
  content: text ? [{ type: "text", text }] : [],
});
const table: ProsemirrorData = {
  type: "table",
  content: [
    ["작업자", "계속 되는 작업", "당일 완료 예정 작업", "참고"],
    ["김지웅", "[ ] 테스트", "", ""],
    ["정수민", "[ ] 영상 제작", "", ""],
  ].map((cells) => ({
    type: "tr",
    content: cells.map((text) => ({ type: "td", content: [p(text)] })),
  })),
};
const heading: ProsemirrorData = {
  type: "heading",
  attrs: { level: 1 },
  content: [{ type: "text", text: "2026.10.23. 금" }],
};
let host: HTMLDivElement;

beforeAll(async () => {
  await i18next.init({ lng: "en", fallbackLng: "en", resources: {} });
});
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: vi.fn(),
  });
});
afterEach(() => {
  act(() => {
    ReactDOM.unmountComponentAtNode(host);
  });
  host.remove();
  vi.restoreAllMocks();
});

function mount(
  toggle = true,
  enabled = true,
  readOnly = false,
  content?: ProsemirrorData[]
) {
  const ref = createRef<Editor>();
  const action = vi.fn();
  const render = (reportEnabled = enabled) =>
    act(() => {
      ReactDOM.render(
        <ThemeProvider theme={light}>
          <Editor
            ref={ref}
            theme={light}
            defaultValue={{
              type: "doc",
              content:
                content ??
                (toggle
                  ? [
                      {
                        type: "container_toggle",
                        attrs: { id: "report-native-test" },
                        content: [heading, table],
                      },
                    ]
                  : [heading, table]),
            }}
            placeholder=""
            embeds={[]}
            extensions={extensions}
            onClickLink={vi.fn()}
            dailyReportEnabled={reportEnabled}
            onDailyReportAction={action}
            canUpdate={!readOnly}
            readOnly={readOnly}
          />
        </ThemeProvider>,
        host
      );
    });
  render();
  if (!ref.current) {
    throw new Error("Editor not mounted");
  }
  // jsdom has no text geometry; exercise selection/history without native scrolling.
  ref.current.view.setProps({ handleScrollToSelection: () => true });
  return { editor: ref.current, action, render };
}

describe("daily reports in the native editor", () => {
  it("does not recognize report ranges at all while the tools are disabled", () => {
    const scan = vi.spyOn(reportRanges, "editorReportRanges");
    const { editor } = mount(true, false);
    act(() => editor.view.dispatch(editor.view.state.tr.insertText("메모", 2)));
    expect(scan).not.toHaveBeenCalled();
    expect(host.querySelector(".daily-report-table-tools")).toBeNull();
  });
  it("removes menus and active filters immediately when disabled and restores tools without changing the document", () => {
    const { editor, render } = mount();
    const original = editor.value(false);
    const select = host.querySelector<HTMLSelectElement>(
      'select[aria-label="표 작업자 필터"]'
    );
    if (!select) {
      throw new Error("Missing filter");
    }
    act(() => {
      select.value = "김지웅";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(host.querySelectorAll(".daily-report-hidden-row")).toHaveLength(1);
    render(false);
    expect(host.querySelector(".daily-report-heading-tools")).toBeNull();
    expect(host.querySelector(".daily-report-table-tools")).toBeNull();
    expect(host.querySelectorAll(".daily-report-hidden-row")).toHaveLength(0);
    expect(editor.value(false)).toEqual(original);
    render(true);
    expect(host.querySelector(".daily-report-heading-tools")).not.toBeNull();
    expect(host.querySelector(".daily-report-table-tools")).not.toBeNull();
    expect(editor.value(false)).toEqual(original);
  });
  it("deletes a filtered native date, including every row, and restores it with one undo", () => {
    const { editor } = mount();
    const original = editor.value(false);
    const select = host.querySelector<HTMLSelectElement>(
      'select[aria-label="표 작업자 필터"]'
    );
    if (!select) {
      throw new Error("Missing filter");
    }
    act(() => {
      select.value = "김지웅";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    const item = host.querySelector<HTMLButtonElement>(".daily-report-delete");
    expect(item?.textContent).toBe("이 날짜 보고 삭제");
    act(() => item?.click());
    expect(editorReportRanges(editor.view.state.doc)).toHaveLength(0);
    expect(editor.view.state.doc.textContent).toBe("");
    expect(editor.view.state.doc.firstChild?.type.name).toBe("paragraph");
    act(() => {
      expect(undo(editor.view.state, editor.view.dispatch)).toBe(true);
    });
    expect(editor.value(false)).toEqual(original);
  });
  it("deletes the latest plain section while preserving common content and the next day", () => {
    const nextHeading = {
      ...heading,
      content: [{ type: "text", text: "2026.10.26. 월" }],
    };
    const { editor } = mount(false, true, false, [
      p("공통 안내"),
      heading,
      table,
      nextHeading,
      table,
    ]);
    // The widget is retained while the report body changes; use live positions at click time.
    const item = host.querySelector<HTMLButtonElement>(".daily-report-delete");
    const range = editorReportRanges(editor.view.state.doc)[0];
    act(() =>
      editor.view.dispatch(
        editor.view.state.tr.insert(
          range.to,
          editor.schema.nodes.paragraph.create(
            {},
            editor.schema.text("방금 추가한 메모")
          )
        )
      )
    );
    const beforeDelete = editor.value(false);
    act(() => item?.click());
    expect(
      editorReportRanges(editor.view.state.doc).map((day) => day.section.date)
    ).toEqual(["2026-10-26"]);
    expect(editor.view.state.doc.textContent).toContain("공통 안내");
    expect(editor.view.state.doc.textContent).not.toContain("방금 추가한 메모");
    expect(editor.view.state.doc.firstChild?.textContent).toBe("공통 안내");
    expect(editor.view.state.doc.child(2).type.name).toBe("table");
    act(() => {
      expect(undo(editor.view.state, editor.view.dispatch)).toBe(true);
    });
    expect(editor.value(false)).toEqual(beforeDelete);
  });
  it("deletes only the clicked nested report even when two sections have the same date", () => {
    const first = {
      type: "container_toggle",
      attrs: { id: "first-date" },
      content: [heading, table],
    };
    const { editor } = mount(true, true, false, [
      first,
      {
        type: "container_toggle",
        attrs: { id: "month" },
        content: [
          p("월간 보고"),
          { ...first, attrs: { id: "second-date" } },
          p("월간 메모"),
        ],
      },
    ]);
    const originalFirst = editor.view.state.doc.firstChild?.toJSON();
    const range = editorReportRanges(editor.view.state.doc)[1];
    act(() => {
      expect(deleteEditorReport(editor.view, range.headingPos)).toBe(true);
    });
    expect(editorReportRanges(editor.view.state.doc)).toHaveLength(1);
    expect(editor.view.state.doc.firstChild?.toJSON()).toEqual(originalFirst);
    expect(editor.view.state.doc.child(1).attrs.id).toBe("month");
    expect(editor.view.state.doc.child(1).textContent).toBe(
      "월간 보고월간 메모"
    );
  });
  it("compares persisted content with real editor nodes, including null-prototype attributes", async () => {
    const { editor } = mount();
    const data = {
      id: "report",
      revision: 1,
      today: "2026-10-26",
      canUpdate: true,
      canCreateChild: true,
      common: [],
      days: [],
      content: editor.view.state.doc.toJSON(),
    };
    vi.mocked(client.post).mockResolvedValueOnce({ data });
    const store = new DailyReportStore("report", "test");
    await expect(store.synchronize(editor)).resolves.toEqual(data);
    expect(store.busy).toBe(false);
    expect(client.post).toHaveBeenLastCalledWith("/dailyReports.info", {
      id: "report",
    });
  });
  it("waits for pending native editor changes instead of offering an older snapshot", async () => {
    const { editor } = mount();
    const content = editor.view.state.doc.toJSON();
    const data = {
      id: "report",
      revision: 2,
      today: "2026-10-26",
      canUpdate: true,
      canCreateChild: true,
      common: [],
      days: [],
      content,
    };
    vi.mocked(client.post)
      .mockResolvedValueOnce({
        data: {
          ...data,
          revision: 1,
          content: { type: "doc", content: [p("old")] },
        },
      })
      .mockResolvedValueOnce({ data });
    const store = new DailyReportStore("report", "test");
    await expect(store.synchronize(editor)).resolves.toEqual(data);
    expect(store.data?.revision).toBe(2);
  });
  it("uses the existing toggle and keeps content unchanged when unfolding", () => {
    const { editor } = mount();
    const original = editor.value(false);
    expect(
      host.querySelector('[aria-label="2026-10-23 보고 메뉴"]')
    ).not.toBeNull();
    expect(
      host.querySelector('select[aria-label="표 작업자 필터"]')
    ).not.toBeNull();
    act(() =>
      editor.view.dispatch(
        editor.view.state.tr.setMeta(toggleFoldPluginKey, {
          type: Action.UNFOLD,
          at: 0,
        })
      )
    );
    expect(editor.value(false)).toEqual(original);
  });
  it("filters display only and reveals a row when the caret enters it", () => {
    const { editor } = mount();
    const original = editor.value(false);
    const select = host.querySelector<HTMLSelectElement>(
      'select[aria-label="표 작업자 필터"]'
    );
    if (!select) {
      throw new Error("Missing filter");
    }
    act(() => {
      select.value = "김지웅";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(host.querySelectorAll(".daily-report-hidden-row")).toHaveLength(1);
    expect(editor.value(false)).toEqual(original);
    const range = editorReportRanges(editor.view.state.doc)[0].tables[0];
    const position =
      range.pos +
      1 +
      range.node.child(0).nodeSize +
      range.node.child(1).nodeSize +
      3;
    act(() =>
      editor.view.dispatch(
        editor.view.state.tr.setSelection(
          TextSelection.near(editor.view.state.doc.resolve(position))
        )
      )
    );
    expect(host.querySelectorAll(".daily-report-hidden-row")).toHaveLength(0);
    expect(editor.value(false)).toEqual(original);
  });
  it("wraps a plain heading and its table using the existing native toggle schema", () => {
    const { editor } = mount(false);
    act(() => {
      expect(wrapEditorReport(editor.view, "2026-10-23")).toBe(true);
    });
    expect(editor.view.state.doc.firstChild?.type.name).toBe(
      "container_toggle"
    );
    expect(editor.view.state.doc.firstChild?.child(1).textContent).toContain(
      "정수민"
    );
    expect(wrapEditorReport(editor.view, "2026-10-23")).toBe(false);
  });
  it("opens a date-scoped action without modifying the document", () => {
    const { editor, action } = mount();
    const original = editor.value(false);
    const item = Array.from(
      host.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')
    ).find((element) => element.textContent === "하위 문서로 이동");
    act(() => item?.click());
    expect(action).toHaveBeenCalledWith("extract", "2026-10-23");
    expect(editor.value(false)).toEqual(original);
  });
  it("does not add tools to unrelated or disabled document contexts", () => {
    mount(true, false);
    expect(host.querySelector(".daily-report-heading-tools")).toBeNull();
    expect(host.querySelector(".daily-report-table-tools")).toBeNull();
  });
  it("allows readers to filter but prevents conversion and mutations", () => {
    const { editor } = mount(false, true, true);
    expect(host.querySelector(".daily-report-heading-tools")).toBeNull();
    expect(
      host.querySelector('select[aria-label="표 작업자 필터"]')
    ).not.toBeNull();
    expect(wrapEditorReport(editor.view, "2026-10-23")).toBe(false);
    expect(
      deleteEditorReport(
        editor.view,
        editorReportRanges(editor.view.state.doc)[0].headingPos
      )
    ).toBe(false);
  });
});
