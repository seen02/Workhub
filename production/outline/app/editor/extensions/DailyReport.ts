import { Plugin, PluginKey, Selection } from "prosemirror-state";
import { closeHistory } from "prosemirror-history";
import type { Node } from "prosemirror-model";
import { Decoration, DecorationSet } from "prosemirror-view";
import type { EditorView } from "prosemirror-view";
import { v4 as uuidv4 } from "uuid";
import Extension from "@shared/editor/lib/Extension";
import {
  dailyReportSettingsMeta,
  editorReportRanges,
} from "@shared/editor/lib/dailyReport";
import type { EditorReportRange } from "@shared/editor/lib/dailyReport";
import {
  Action,
  toggleFoldPluginKey,
  toggleStorageKey,
} from "@shared/editor/nodes/ToggleBlock";
import Storage from "@shared/utils/Storage";
import { reportText } from "@shared/utils/dailyReport";

interface ReportFilterState {
  filters: ReadonlyMap<string, string>;
  decorations: DecorationSet;
}
interface FilterAction {
  key: string;
  worker: string;
}

/** View-only table filters: never stored in the document or serialized into Markdown. */
export const dailyReportFilterKey = new PluginKey<ReportFilterState>(
  "dailyReportFilter"
);

/** Deletes the clicked date's current section in one undoable editor transaction.
 *
 * @param view the live editor view.
 * @param headingPos the clicked heading's current position, distinguishing duplicate dates.
 * @returns whether the editable report section was deleted.
 */
export function deleteEditorReport(
  view: EditorView,
  headingPos: number
): boolean {
  if (!view.editable || view.isDestroyed) {
    return false;
  }
  const range = editorReportRanges(view.state.doc).find(
    (item) => item.headingPos === headingPos
  );
  if (!range) {
    return false;
  }
  const tr = closeHistory(view.state.tr.delete(range.from, range.to));
  tr.setSelection(
    Selection.near(tr.doc.resolve(Math.min(range.from, tr.doc.content.size)))
  );
  view.dispatch(tr.scrollIntoView());
  view.focus();
  return true;
}

/** Converts one ordinary date section into the editor's existing native toggle block. */
export function wrapEditorReport(view: EditorView, date: string): boolean {
  const range = editorReportRanges(view.state.doc).find(
    (item) => item.section.date === date
  );
  if (!range || range.section.toggle || !view.editable) {
    return false;
  }
  const type = view.state.schema.nodes.container_toggle;
  if (!type) {
    return false;
  }
  const id = uuidv4();
  Storage.set(toggleStorageKey(id), { fold: false });
  const content = view.state.doc.slice(range.from, range.to).content;
  view.dispatch(
    view.state.tr.replaceWith(
      range.from,
      range.to,
      type.create({ id }, content)
    )
  );
  return true;
}

/** Opens the existing toggle and scrolls to a date without editing its content. */
export function revealEditorReport(view: EditorView, date: string): void {
  const range = editorReportRanges(view.state.doc).find(
    (item) => item.section.date === date
  );
  if (!range) {
    return;
  }
  let tr = view.state.tr;
  if (range.section.toggle) {
    tr = tr.setMeta(toggleFoldPluginKey, {
      type: Action.UNFOLD,
      at: range.from,
    });
  }
  // An outer native toggle may also contain the report.
  const resolved = view.state.doc.resolve(range.headingPos);
  for (let depth = 1; depth <= resolved.depth; depth++) {
    if (resolved.node(depth).type.name === "container_toggle") {
      tr = tr.setMeta(toggleFoldPluginKey, {
        type: Action.UNFOLD,
        at: resolved.before(depth),
      });
      view.dispatch(tr);
      tr = view.state.tr;
    }
  }
  view.dispatch(tr);
  requestAnimationFrame(() => {
    const element = view.nodeDOM(range.headingPos);
    if (element instanceof HTMLElement) {
      element.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  });
}

/** Attaches report actions and per-table author filters to the ordinary editor. */
export class DailyReportExtension extends Extension {
  get name() {
    return "daily-report-tools";
  }
  get allowInReadOnly() {
    return true;
  }

  get plugins() {
    const editor = this.editor;
    const menu = (range: EditorReportRange) => (view: EditorView) => {
      const wrapper = document.createElement("span");
      wrapper.className = "daily-report-heading-tools";
      wrapper.contentEditable = "false";
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "⋯";
      button.setAttribute("aria-label", `${range.section.date} 보고 메뉴`);
      button.setAttribute("aria-haspopup", "menu");
      button.setAttribute("aria-expanded", "false");
      const panel = document.createElement("span");
      panel.className = "daily-report-menu-panel";
      panel.setAttribute("role", "menu");
      panel.setAttribute("aria-label", `${range.section.date} 업무보고 작업`);
      panel.hidden = true;
      const close = () => {
        panel.hidden = true;
        button.setAttribute("aria-expanded", "false");
      };
      button.addEventListener("mousedown", (event) => event.preventDefault());
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        view.dom
          .querySelectorAll<HTMLElement>(".daily-report-menu-panel")
          .forEach((other) => {
            if (other !== panel) {
              other.hidden = true;
              other.previousElementSibling?.setAttribute(
                "aria-expanded",
                "false"
              );
            }
          });
        panel.hidden = !panel.hidden;
        button.setAttribute("aria-expanded", String(!panel.hidden));
        if (!panel.hidden) {
          panel.style.transform = "";
          const bounds = panel.getBoundingClientRect();
          const viewportWidth =
            panel.ownerDocument.documentElement.clientWidth ||
            window.innerWidth;
          const offset =
            bounds.left < 12
              ? 12 - bounds.left
              : bounds.right > viewportWidth - 12
                ? viewportWidth - 12 - bounds.right
                : 0;
          if (offset) {
            panel.style.transform = `translateX(${offset}px)`;
          }
        }
      });
      wrapper.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
          close();
          button.focus();
          event.stopPropagation();
        }
      });
      const add = (
        label: string,
        callback: () => void,
        destructive = false
      ) => {
        const item = document.createElement("button");
        item.type = "button";
        item.setAttribute("role", "menuitem");
        item.textContent = label;
        if (destructive) {
          const separator = document.createElement("span");
          separator.className = "daily-report-menu-separator";
          separator.setAttribute("role", "separator");
          panel.appendChild(separator);
          item.className = "daily-report-delete";
        }
        item.addEventListener("mousedown", (event) => event.preventDefault());
        item.addEventListener("click", (event) => {
          event.preventDefault();
          event.stopPropagation();
          close();
          callback();
        });
        panel.appendChild(item);
      };
      if (!range.section.toggle && !editor.props.readOnly) {
        add("토글 제목으로 묶기", () => {
          wrapEditorReport(view, range.section.date);
        });
      }
      add("오늘 보고 추가", () => editor.props.onDailyReportAction?.("create"));
      add("미완료 업무 이월", () =>
        editor.props.onDailyReportAction?.("carry", range.section.date)
      );
      add("하위 문서로 이동", () =>
        editor.props.onDailyReportAction?.("extract", range.section.date)
      );
      add(
        "이 날짜 보고 삭제",
        () => {
          deleteEditorReport(view, range.headingPos);
        },
        true
      );
      wrapper.append(button, panel);
      return wrapper;
    };
    const filter =
      (table: EditorReportRange["tables"][number], worker: string) =>
      (view: EditorView) => {
        const toolbar = document.createElement("div");
        toolbar.className = "daily-report-table-tools";
        toolbar.contentEditable = "false";
        const label = document.createElement("label");
        label.textContent = "작업자 ";
        const select = document.createElement("select");
        select.setAttribute("aria-label", "표 작업자 필터");
        const workers = new Set<string>();
        table.node.forEach((row, _offset, index) => {
          if (index > 0 && row.firstChild?.textContent.trim()) {
            workers.add(row.firstChild.textContent.trim());
          }
        });
        for (const name of ["", ...workers]) {
          const option = document.createElement("option");
          option.value = name;
          option.textContent = name || "전체";
          select.appendChild(option);
        }
        select.value = worker;
        select.addEventListener("change", () =>
          view.dispatch(
            view.state.tr.setMeta(dailyReportFilterKey, {
              key: table.key,
              worker: select.value,
            } satisfies FilterAction)
          )
        );
        label.appendChild(select);
        toolbar.appendChild(label);
        return toolbar;
      };
    const build = (
      doc: Node,
      filters: ReadonlyMap<string, string>,
      ranges?: EditorReportRange[]
    ) => {
      if (!editor.props.dailyReportEnabled) {
        return DecorationSet.empty;
      }
      const decorations: Decoration[] = [];
      for (const range of ranges ?? editorReportRanges(doc)) {
        if (
          !range.tables.length &&
          !range.section.blocks.some((node) =>
            reportText(node).startsWith("📄 ")
          )
        ) {
          continue;
        }
        const heading = doc.nodeAt(range.headingPos);
        if (
          heading &&
          editor.props.onDailyReportAction &&
          editor.props.canUpdate &&
          !editor.props.readOnly
        ) {
          decorations.push(
            Decoration.widget(
              range.headingPos + heading.nodeSize - 1,
              menu(range),
              {
                side: 1,
                key: `report-menu:${range.headingPos}:${range.section.date}:${!!range.section.toggle}`,
                ignoreSelection: true,
                stopEvent: () => true,
              }
            )
          );
        }
        for (const table of range.tables) {
          const worker = filters.get(table.key) ?? "";
          decorations.push(
            Decoration.widget(table.pos, filter(table, worker), {
              side: -1,
              key: `report-filter:${table.key}:${worker}:${table.node.textContent}`,
              ignoreSelection: true,
              stopEvent: () => true,
            })
          );
          if (worker) {
            table.node.forEach((row, offset, index) => {
              if (index > 0 && row.firstChild?.textContent.trim() !== worker) {
                decorations.push(
                  Decoration.node(
                    table.pos + 1 + offset,
                    table.pos + 1 + offset + row.nodeSize,
                    {
                      class: "daily-report-hidden-row",
                      style: "display: none;",
                    },
                    { tableKey: table.key }
                  )
                );
              }
            });
          }
        }
      }
      return DecorationSet.create(doc, decorations);
    };
    return [
      new Plugin<ReportFilterState>({
        key: dailyReportFilterKey,
        state: {
          init: (_, state) => ({
            filters: new Map(),
            decorations: build(state.doc, new Map()),
          }),
          apply(tr, previous) {
            if (!editor.props.dailyReportEnabled) {
              return previous.filters.size ||
                previous.decorations !== DecorationSet.empty
                ? { filters: new Map(), decorations: DecorationSet.empty }
                : previous;
            }
            const action: FilterAction | undefined =
              tr.getMeta(dailyReportFilterKey);
            if (
              !tr.docChanged &&
              !action &&
              !tr.getMeta(dailyReportSettingsMeta)
            ) {
              return previous;
            }
            const filters = new Map(previous.filters);
            if (action) {
              filters.set(action.key, action.worker);
            }
            const ranges = editorReportRanges(tr.doc);
            const validKeys = new Set(
              ranges.flatMap((range) => range.tables.map((table) => table.key))
            );
            filters.forEach((_, key) => {
              if (!validKeys.has(key)) {
                filters.delete(key);
              }
            });
            return { filters, decorations: build(tr.doc, filters, ranges) };
          },
        },
        props: {
          decorations: (state) =>
            dailyReportFilterKey.getState(state)?.decorations,
          handleDOMEvents: {
            focus: (view) => {
              const hidden = dailyReportFilterKey
                .getState(view.state)
                ?.decorations.find(
                  view.state.selection.from,
                  view.state.selection.to
                )
                .find(
                  (decoration) =>
                    decoration.spec.tableKey &&
                    view.state.selection.from > decoration.from &&
                    view.state.selection.from < decoration.to
                );
              if (hidden) {
                view.dispatch(
                  view.state.tr.setMeta(dailyReportFilterKey, {
                    key: hidden.spec.tableKey,
                    worker: "",
                  } satisfies FilterAction)
                );
              }
              return false;
            },
          },
        },
        appendTransaction(transactions, _, state) {
          if (!transactions.some((tr) => tr.selectionSet || tr.docChanged)) {
            return null;
          }
          const plugin = dailyReportFilterKey.getState(state);
          if (!plugin) {
            return null;
          }
          const hidden = plugin.decorations
            .find(state.selection.from, state.selection.to)
            .find(
              (decoration) =>
                decoration.spec.tableKey &&
                state.selection.from > decoration.from &&
                state.selection.from < decoration.to
            );
          return hidden
            ? state.tr.setMeta(dailyReportFilterKey, {
                key: hidden.spec.tableKey,
                worker: "",
              } satisfies FilterAction)
            : null;
        },
        view(view) {
          const handleOutside = (event: MouseEvent) => {
            if (!editor.props.dailyReportEnabled) {
              return;
            }
            if (
              event.target instanceof Element &&
              event.target.closest(".daily-report-heading-tools")
            ) {
              return;
            }
            view.dom
              .querySelectorAll<HTMLElement>(".daily-report-menu-panel")
              .forEach((panel) => {
                panel.hidden = true;
                panel.previousElementSibling?.setAttribute(
                  "aria-expanded",
                  "false"
                );
              });
          };
          view.dom.ownerDocument.addEventListener("mousedown", handleOutside);
          return {
            destroy: () =>
              view.dom.ownerDocument.removeEventListener(
                "mousedown",
                handleOutside
              ),
          };
        },
      }),
    ];
  }
}
