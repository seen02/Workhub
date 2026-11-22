import { t } from "i18next";
import type { PluginSimple } from "markdown-it";
import type {
  NodeSpec,
  NodeType,
  Node as ProsemirrorNode,
} from "prosemirror-model";
import { Fragment } from "prosemirror-model";
import type { Command } from "prosemirror-state";
import {
  NodeSelection,
  Plugin,
  PluginKey,
  TextSelection,
} from "prosemirror-state";
import type { EditorView } from "prosemirror-view";
import { HeadingPrefixStyle } from "../../types";
import { ProsemirrorHelper } from "../../utils/ProsemirrorHelper";
import { headingPrefixPluginKey } from "../extensions/HeadingPrefix";
import type { MarkdownSerializerState } from "../lib/markdown/serializer";
import {
  getTableOfContentsItems,
  renderTableOfContents,
  type TableOfContentsItem,
} from "../lib/tableOfContents";
import Node from "./Node";

interface ContentsState {
  style: HeadingPrefixStyle;
  items: TableOfContentsItem[];
}

/** The derived contents shared by every contents block in one editor. */
export const tableOfContentsPluginKey = new PluginKey<ContentsState>(
  "table-of-contents"
);

const marker = "[[_OUTLINE_TOC_]]";

/** A document-wide, automatically updated table of contents stored as an atom. */
export class TableOfContents extends Node {
  get name() {
    return "table_of_contents";
  }

  get schema(): NodeSpec {
    return {
      group: "block",
      atom: true,
      selectable: true,
      draggable: true,
      leafText: () => t("Table of contents") || "Table of contents",
      parseDOM: [{ tag: 'nav[data-type="table_of_contents"]' }],
      toDOM: () => [
        "nav",
        {
          "data-type": this.name,
          class: "table-of-contents",
          "aria-label": t("Table of contents"),
        },
        ["div", { class: "table-of-contents-title" }, t("Contents")],
      ],
    };
  }

  commands({ type }: { type: NodeType }) {
    return (): Command => (state, dispatch) => {
      // Only offer insertion in a top-level paragraph. Replacing a selection
      // spanning existing content would otherwise silently remove that content.
      const { selection } = state;
      if (
        !selection.empty ||
        selection.$from.depth !== 1 ||
        selection.$from.parent.type.name !== "paragraph"
      ) {
        return false;
      }
      if (!dispatch) {
        return true;
      }
      const { $from } = selection;
      const paragraph = $from.parent;
      const before = paragraph.content.cut(0, $from.parentOffset);
      const after = paragraph.content.cut($from.parentOffset);
      const leading = before.size ? [paragraph.copy(before)] : [];
      const blocks = [...leading, type.create(), paragraph.copy(after)];
      const start = $from.before();
      const cursor = start + (leading[0]?.nodeSize ?? 0) + 2;
      const tr = state.tr.replaceWith(
        start,
        $from.after(),
        Fragment.fromArray(blocks)
      );
      dispatch(
        tr.setSelection(TextSelection.create(tr.doc, cursor)).scrollIntoView()
      );
      return true;
    };
  }

  keys(): Record<string, Command> {
    return {
      Enter: (state, dispatch) => {
        if (
          !(state.selection instanceof NodeSelection) ||
          state.selection.node.type.name !== this.name
        ) {
          return false;
        }
        const end = state.selection.to;
        const tr = state.tr.insert(end, state.schema.nodes.paragraph.create());
        dispatch?.(
          tr
            .setSelection(TextSelection.near(tr.doc.resolve(end + 1)))
            .scrollIntoView()
        );
        return true;
      },
    };
  }

  get plugins(): Plugin[] {
    // A plugin instance can be used by several static export views. Keep each
    // view's render callbacks isolated, and release them when its nodes die.
    const renderers = new Map<EditorView, Set<() => void>>();
    return [
      new Plugin<ContentsState>({
        key: tableOfContentsPluginKey,
        state: {
          init: (_, state) => {
            const style =
              this.editor?.props.headingPrefix ?? HeadingPrefixStyle.None;
            return {
              style,
              items: getTableOfContentsItems(
                ProsemirrorHelper.getHeadings(state.doc),
                style
              ),
            };
          },
          apply: (tr, previous) => {
            const style: HeadingPrefixStyle =
              tr.getMeta(headingPrefixPluginKey) ?? previous.style;
            if (!tr.docChanged && style === previous.style) {
              return previous;
            }
            const items = getTableOfContentsItems(
              ProsemirrorHelper.getHeadings(tr.doc),
              style
            );
            return JSON.stringify(items) === JSON.stringify(previous.items) &&
              style === previous.style
              ? previous
              : { style, items };
          },
        },
        view: () => ({
          update: (view, previous) => {
            if (
              tableOfContentsPluginKey.getState(view.state) !==
              tableOfContentsPluginKey.getState(previous)
            ) {
              renderers.get(view)?.forEach((render) => render());
            }
          },
        }),
        props: {
          nodeViews: {
            [this.name]: (_node, view) => {
              const dom = view.dom.ownerDocument.createElement("nav");
              dom.dataset.type = this.name;
              dom.className = "table-of-contents";
              dom.contentEditable = "false";
              const render = () =>
                renderTableOfContents(
                  dom,
                  tableOfContentsPluginKey.getState(view.state)?.items ?? []
                );
              render();
              let callbacks = renderers.get(view);
              if (!callbacks) {
                callbacks = new Set();
                renderers.set(view, callbacks);
              }
              callbacks.add(render);
              dom.addEventListener("click", (event) => {
                const target = event.target;
                if (!(target instanceof Element)) {
                  return;
                }
                const link = target.closest("a");
                if (
                  !link ||
                  event.button !== 0 ||
                  event.metaKey ||
                  event.ctrlKey ||
                  event.shiftKey ||
                  event.altKey
                ) {
                  return;
                }
                const href = link.getAttribute("href");
                if (!href || !this.editor?.scrollToAnchor) {
                  return;
                }
                event.preventDefault();
                this.editor.props.onClickLink(href, event);
                // Repeated clicks must also scroll when the hash did not change.
                void this.editor.scrollToAnchor(href);
              });
              return {
                dom,
                update: (node) => node.type.name === this.name,
                ignoreMutation: () => true,
                stopEvent: (event) =>
                  event.target instanceof Element &&
                  !!event.target.closest("a") &&
                  !event.type.startsWith("drag") &&
                  !event.type.startsWith("drop"),
                destroy: () => {
                  renderers.get(view)?.delete(render);
                  if (!renderers.get(view)?.size) {
                    renderers.delete(view);
                  }
                },
              };
            },
          },
        },
      }),
    ];
  }

  get rulePlugins(): PluginSimple[] {
    return [
      (md) => {
        md.block.ruler.before(
          "paragraph",
          this.name,
          (state, startLine, _endLine, silent) => {
            if (state.sCount[startLine] - state.blkIndent >= 4) {
              return false;
            }
            const line = state.src.slice(
              state.bMarks[startLine] + state.tShift[startLine],
              state.eMarks[startLine]
            );
            if (line.trim() !== marker) {
              return false;
            }
            if (!silent) {
              const token = state.push(this.name, "nav", 0);
              token.block = true;
              token.map = [startLine, startLine + 1];
              state.line = startLine + 1;
            }
            return true;
          },
          { alt: ["paragraph", "reference", "blockquote", "list"] }
        );
      },
    ];
  }

  parseMarkdown() {
    return { node: this.name, noCloseToken: true };
  }

  toMarkdown(state: MarkdownSerializerState, node: ProsemirrorNode) {
    if (!state.options.commonMark) {
      state.write(marker);
      state.closeBlock(node);
      return;
    }
    const items = getTableOfContentsItems(
      state.doc ? ProsemirrorHelper.getHeadings(state.doc) : [],
      state.options.headingPrefix
    );
    state.write(`**${t("Contents")}**\n\n`);
    for (const item of items) {
      const title =
        `${item.label ? item.label + " " : ""}${item.title || t("Untitled")}`.replace(
          /\s+/g,
          " "
        );
      state.write(
        `${"  ".repeat(item.depth)}- [${title.replace(/[\\`*_[\]<>~&]/g, "\\$&")}](#${item.id})\n`
      );
    }
    state.closeBlock(node);
  }
}
