import i18next from "i18next";
import { history, undo, redo } from "prosemirror-history";
import {
  DOMParser as ProsemirrorDOMParser,
  DOMSerializer,
} from "prosemirror-model";
import { EditorState, NodeSelection, TextSelection } from "prosemirror-state";
import { EditorView } from "prosemirror-view";
import {
  prosemirrorToYDoc,
  yDocToProsemirrorJSON,
  ySyncPlugin,
} from "y-prosemirror";
import * as Y from "yjs";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { HeadingPrefixStyle } from "../../types";
import { ProsemirrorHelper } from "../../utils/ProsemirrorHelper";
import { p, parser, schema, serializer } from "../../test/editor";
import { headingPrefixPluginKey } from "../extensions/HeadingPrefix";
import { getTableOfContentsItems } from "../lib/tableOfContents";
import { TableOfContents, tableOfContentsPluginKey } from "./TableOfContents";

const toc = () => schema.nodes.table_of_contents.create();
const heading = (text: string, level = 1) =>
  schema.nodes.heading.create({ level }, schema.text(text));

beforeAll(async () => {
  await i18next.init({ lng: "en", fallbackLng: "en", resources: {} });
});

describe("table of contents data", () => {
  it("retains a leading or trailing contents block when empty paragraphs are trimmed", () => {
    const doc = schema.nodes.doc.create(null, [
      p(""),
      toc(),
      heading("Title"),
      toc(),
      p(""),
    ]);
    expect(ProsemirrorHelper.trim(doc).toJSON()).toEqual(
      schema.nodes.doc.create(null, [toc(), heading("Title"), toc()]).toJSON()
    );
    expect(
      ProsemirrorHelper.isEmpty(schema.nodes.doc.create(null, [toc()]), schema)
    ).toBe(false);
  });
  it("matches sidebar filtering, numbering, and indentation", () => {
    const headings = [
      { id: "a", title: "A", level: 2 },
      { id: "cell", title: "Cell", level: 1, inTable: true },
      { id: "b", title: "B", level: 4 },
      { id: "deep", title: "Deep", level: 5 },
      { id: "c", title: "C", level: 2 },
    ];
    const items = getTableOfContentsItems(headings, HeadingPrefixStyle.Outline);
    expect(items.map(({ id, depth, label }) => ({ id, depth, label }))).toEqual(
      [
        { id: "a", depth: 0, label: "I" },
        { id: "b", depth: 2, label: "A" },
        { id: "c", depth: 0, label: "II" },
      ]
    );
  });

  it("keeps the same duplicate heading anchors even when the first is in a table", () => {
    const cell = schema.nodes.td.create(null, heading("중복"));
    const table = schema.nodes.table.create(
      null,
      schema.nodes.tr.create(null, cell)
    );
    const doc = schema.nodes.doc.create(null, [
      table,
      toc(),
      heading("중복"),
      heading("중복"),
    ]);
    const headings = ProsemirrorHelper.getHeadings(doc);
    expect(getTableOfContentsItems(headings).map((item) => item.id)).toEqual([
      headings[1].id,
      headings[2].id,
    ]);
    expect(new Set(headings.map((item) => item.id)).size).toBe(3);
  });

  it("round trips through the collaborative document format without stored heading lists", () => {
    const doc = schema.nodes.doc.create(null, [
      toc(),
      heading("Title"),
      p("Text"),
      toc(),
    ]);
    const ydoc = prosemirrorToYDoc(doc);
    expect(yDocToProsemirrorJSON(ydoc)).toEqual(doc.toJSON());
    expect(toc().toJSON()).toEqual({ type: "table_of_contents" });
    ydoc.destroy();
  });
});

describe("table of contents serialization", () => {
  it("preserves multiple blocks in internal Markdown and position maps", () => {
    const doc = schema.nodes.doc.create(null, [
      heading("Before"),
      toc(),
      p("Middle"),
      toc(),
    ]);
    const text = serializer.serialize(doc);
    expect(text.split("[[_OUTLINE_TOC_]]").slice(1)).toHaveLength(2);
    expect(parser.parse(text)?.toJSON()).toEqual(doc.toJSON());
    const mapped = serializer.serializeWithPositions(doc);
    expect(mapped.markdown).toBe(text);
    expect(mapped.blockMap).toHaveLength(4);
    expect(parser.parse(mapped.markdown)?.toJSON()).toEqual(doc.toJSON());
  });

  it("does not interpret markers inside code blocks or inline text", () => {
    expect(
      parser.parse("```\n[[_OUTLINE_TOC_]]\n```")?.firstChild?.type.name
    ).toBe("code_block");
    expect(
      parser.parse("text [[_OUTLINE_TOC_]] text")?.firstChild?.type.name
    ).toBe("paragraph");
    expect(parser.parse("    [[_OUTLINE_TOC_]]")?.firstChild?.type.name).toBe(
      "code_block"
    );
  });

  it("exports a static CommonMark list with unique, explicit heading targets", () => {
    const doc = schema.nodes.doc.create(null, [
      heading("Same"),
      toc(),
      heading("Same", 2),
      heading("[Link]", 3),
    ]);
    const text = serializer.serialize(doc, { commonMark: true });
    const headings = ProsemirrorHelper.getHeadings(doc);
    expect(text).not.toContain("[[_OUTLINE_TOC_]]");
    expect(text).toContain("**Contents**");
    for (const item of headings) {
      expect(text).toContain(`](#${item.id})`);
      expect(text).toContain(`<a id="${item.id}"></a>`);
    }
    expect(text).toContain("\\[Link\\]");
  });

  it("does not change ordinary CommonMark documents", () => {
    expect(
      serializer.serialize(schema.nodes.doc.create(null, [heading("Title")]), {
        commonMark: true,
      })
    ).toBe("# Title");
  });

  it("keeps exported targets correct when earlier headings are inside tables", () => {
    const cell = schema.nodes.td.create(null, heading("Same"));
    const table = schema.nodes.table.create(
      null,
      schema.nodes.tr.create(null, cell)
    );
    const doc = schema.nodes.doc.create(null, [toc(), table, heading("Same")]);
    const text = serializer.serialize(doc, { commonMark: true });
    expect(text).toContain("[Same](#h-same-1)");
    expect(text).toContain('<a id="h-same-1"></a>');
    expect(text).not.toContain('<a id="h-same"></a>');
  });
});

describe("table of contents editing", () => {
  it("inserts into an empty paragraph and places the cursor below the block", () => {
    let state = EditorState.create({
      schema,
      doc: schema.nodes.doc.create(null, [p("")]),
      plugins: [history()],
    });
    const command = new TableOfContents().commands({
      type: schema.nodes.table_of_contents,
    })();
    expect(
      command(state, (tr) => {
        state = state.apply(tr);
      })
    ).toBe(true);
    expect(state.doc.toJSON()).toEqual(
      schema.nodes.doc.create(null, [toc(), p("")]).toJSON()
    );
    expect(state.selection.from).toBe(2);
    expect(
      undo(state, (tr) => {
        state = state.apply(tr);
      })
    ).toBe(true);
    expect(state.doc.toJSON()).toEqual(
      schema.nodes.doc.create(null, [p("")]).toJSON()
    );
    expect(
      redo(state, (tr) => {
        state = state.apply(tr);
      })
    ).toBe(true);
    expect(state.doc.firstChild?.type.name).toBe("table_of_contents");
  });

  it("preserves text on both sides when inserting in the middle of a paragraph", () => {
    let state = EditorState.create({
      schema,
      doc: schema.nodes.doc.create(null, [p("BeforeAfter"), heading("Next")]),
    });
    state = state.apply(
      state.tr.setSelection(TextSelection.create(state.doc, 7))
    );
    new TableOfContents().commands({ type: schema.nodes.table_of_contents })()(
      state,
      (tr) => {
        state = state.apply(tr);
      }
    );
    expect(state.doc.toJSON()).toEqual(
      schema.nodes.doc
        .create(null, [p("Before"), toc(), p("After"), heading("Next")])
        .toJSON()
    );
    expect(state.selection.$from.parent.textContent).toBe("After");
    expect(state.selection.$from.parentOffset).toBe(0);
  });

  it("rejects a selection spanning content", () => {
    let state = EditorState.create({
      schema,
      doc: schema.nodes.doc.create(null, [p("Keep")]),
    });
    state = state.apply(
      state.tr.setSelection(TextSelection.create(state.doc, 1, 4))
    );
    expect(
      new TableOfContents().commands({
        type: schema.nodes.table_of_contents,
      })()(state)
    ).toBe(false);
  });

  it("creates a paragraph with Enter when the atom is selected", () => {
    let state = EditorState.create({
      schema,
      doc: schema.nodes.doc.create(null, [toc()]),
    });
    state = state.apply(
      state.tr.setSelection(NodeSelection.create(state.doc, 0))
    );
    expect(
      new TableOfContents().keys().Enter(state, (tr) => {
        state = state.apply(tr);
      })
    ).toBe(true);
    expect(state.selection.$from.parent.type.name).toBe("paragraph");
  });
});

describe.skipIf(typeof document === "undefined")(
  "table of contents view",
  () => {
    it("converges after two editors synchronize concurrent Yjs updates", () => {
      const doc = schema.nodes.doc.create(null, [toc(), heading("Title")]);
      const leftDoc = prosemirrorToYDoc(doc);
      const rightDoc = new Y.Doc();
      Y.applyUpdate(rightDoc, Y.encodeStateAsUpdate(leftDoc));
      const createView = (ydoc: Y.Doc) => {
        const view = new EditorView(document.createElement("div"), {
          state: EditorState.create({
            schema,
            doc,
            plugins: [
              ySyncPlugin(ydoc.getXmlFragment("prosemirror")),
              ...new TableOfContents().plugins,
            ],
          }),
          dispatchTransaction(this: EditorView, tr) {
            this.updateState(this.state.apply(tr));
          },
        });
        return view;
      };
      const left = createView(leftDoc);
      const right = createView(rightDoc);
      try {
        left.dispatch(
          left.state.tr.insertText(" A", left.state.doc.content.size - 1)
        );
        right.dispatch(
          right.state.tr.insert(right.state.doc.content.size, heading("Remote"))
        );
        Y.applyUpdate(leftDoc, Y.encodeStateAsUpdate(rightDoc));
        Y.applyUpdate(rightDoc, Y.encodeStateAsUpdate(leftDoc));
        const links = (view: EditorView) =>
          [...view.dom.querySelectorAll("nav a")].map((link) => ({
            title: link.textContent,
            href: link.getAttribute("href"),
          }));
        expect(links(left)).toEqual(links(right));
        expect(links(left).map((link) => link.title)).toEqual([
          "Title A",
          "Remote",
        ]);
        expect(left.state.doc.toJSON()).toEqual(right.state.doc.toJSON());
      } finally {
        left.destroy();
        right.destroy();
        leftDoc.destroy();
        rightDoc.destroy();
      }
    });

    it("updates every block on remote-style edits and preference changes without changing stored nodes", () => {
      const extension = new TableOfContents();
      const view = new EditorView(document.createElement("div"), {
        state: EditorState.create({
          schema,
          doc: schema.nodes.doc.create(null, [toc(), toc(), p("Text")]),
          plugins: extension.plugins,
        }),
        dispatchTransaction(tr) {
          view.updateState(view.state.apply(tr));
        },
      });
      try {
        expect(
          view.dom.querySelectorAll(".table-of-contents-empty")
        ).toHaveLength(2);
        view.dispatch(
          view.state.tr.insert(view.state.doc.content.size, heading("Added"))
        );
        expect(
          [...view.dom.querySelectorAll("nav a")].map(
            (link) => link.textContent
          )
        ).toEqual(["Added", "Added"]);
        const original = view.state.doc.toJSON();
        view.dispatch(
          view.state.tr.setMeta(
            headingPrefixPluginKey,
            HeadingPrefixStyle.Outline
          )
        );
        expect(
          [...view.dom.querySelectorAll("nav a")].map(
            (link) => link.textContent
          )
        ).toEqual(["I Added", "I Added"]);
        expect(view.state.doc.toJSON()).toEqual(original);
        const previous = tableOfContentsPluginKey.getState(view.state);
        view.dispatch(view.state.tr.insertText("more", 5));
        expect(tableOfContentsPluginKey.getState(view.state)).toBe(previous);
      } finally {
        view.destroy();
      }
    });

    it("preserves only the atom when copied as HTML and safely renders heading text", () => {
      const doc = schema.nodes.doc.create(null, [
        toc(),
        heading('<img src=x onerror="bad()">'),
      ]);
      const view = new EditorView(document.createElement("div"), {
        state: EditorState.create({
          schema,
          doc,
          plugins: new TableOfContents().plugins,
        }),
        editable: () => false,
      });
      try {
        expect(view.dom.querySelector("nav img")).toBeNull();
        expect(view.dom.querySelector("nav a")?.textContent).toBe(
          '<img src=x onerror="bad()">'
        );
        const container = document.createElement("div");
        container.append(
          DOMSerializer.fromSchema(schema).serializeFragment(doc.content)
        );
        expect(
          ProsemirrorDOMParser.fromSchema(schema).parse(container).toJSON()
        ).toEqual(doc.toJSON());
      } finally {
        view.destroy();
      }
    });

    it("handles normal and repeated link clicks while leaving modified clicks native", () => {
      const extension = new TableOfContents();
      const onClickLink = vi.fn();
      const scrollToAnchor = vi.fn();
      Object.assign(extension, {
        editor: { props: { onClickLink }, scrollToAnchor },
      });
      const view = new EditorView(document.createElement("div"), {
        state: EditorState.create({
          schema,
          doc: schema.nodes.doc.create(null, [toc(), heading("Target")]),
          plugins: extension.plugins,
        }),
      });
      try {
        const link = view.dom.querySelector("nav a");
        link?.dispatchEvent(
          new MouseEvent("click", { bubbles: true, cancelable: true })
        );
        link?.dispatchEvent(
          new MouseEvent("click", { bubbles: true, cancelable: true })
        );
        expect(onClickLink).toHaveBeenCalledTimes(2);
        expect(scrollToAnchor).toHaveBeenCalledTimes(2);
        const modified = new MouseEvent("click", {
          bubbles: true,
          cancelable: true,
          ctrlKey: true,
        });
        link?.dispatchEvent(modified);
        expect(modified.defaultPrevented).toBe(false);
        expect(onClickLink).toHaveBeenCalledTimes(2);
      } finally {
        view.destroy();
      }
    });
  }
);
