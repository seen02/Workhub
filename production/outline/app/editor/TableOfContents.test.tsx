import i18next from "i18next";
import { createRef } from "react";
import ReactDOM from "react-dom";
import { act } from "react-dom/test-utils";
import { ThemeProvider } from "styled-components";
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
import { toggleFoldPluginKey } from "@shared/editor/nodes/ToggleBlock";
import light from "@shared/styles/theme";
import { HeadingPrefixStyle } from "@shared/types";
import { Editor } from "./index";

// The image gallery is unrelated to document contents and pulls browser-only
// gesture and dialog packages into the editor's otherwise headless test.
vi.mock("~/components/Lightbox", () => ({ default: () => null }));

// Use the real document editor with its heading, contents, and folding plugins.
// Unrelated third-party math/code views instantiate a separate CommonJS
// DecorationSet under Node and are not needed by these fixtures.
const editorExtensions = richExtensions.filter((extension) =>
  [
    "Doc",
    "Paragraph",
    "Text",
    "Heading",
    "TableOfContents",
    "HeadingPrefix",
    "ToggleBlock",
    "History",
    "TrailingNode",
  ].includes(extension.name)
);

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
});

describe("contents in the document editor", () => {
  it("renders in reading mode, updates numbering preferences, and blocks insertion", () => {
    const ref = createRef<Editor>();
    const content = "[[_OUTLINE_TOC_]]\n\n# Title\n\n## Child";
    const render = (headingPrefix: HeadingPrefixStyle) => {
      act(() => {
        ReactDOM.render(
          <ThemeProvider theme={light}>
            <Editor
              ref={ref}
              theme={light}
              defaultValue={content}
              placeholder=""
              embeds={[]}
              extensions={editorExtensions}
              onClickLink={vi.fn()}
              readOnly
              headingPrefix={headingPrefix}
            />
          </ThemeProvider>,
          host
        );
      });
    };
    render(HeadingPrefixStyle.None);
    const editor = ref.current;
    if (!editor) {
      throw new Error("Editor was not mounted");
    }
    expect(
      [...host.querySelectorAll("nav a")].map((link) => link.textContent)
    ).toEqual(["Title", "Child"]);
    const original = editor.value(false);
    editor.commands.table_of_contents();
    expect(editor.value(false)).toEqual(original);
    render(HeadingPrefixStyle.Outline);
    expect(
      [...host.querySelectorAll("nav a")].map((link) => link.textContent)
    ).toEqual(["I Title", "A Child"]);
    expect(editor.value(false)).toEqual(original);
  });

  it("opens a folded toggle when a reader follows a contents link", async () => {
    const ref = createRef<Editor>();
    const onClickLink = vi.fn();
    act(() => {
      ReactDOM.render(
        <ThemeProvider theme={light}>
          <Editor
            ref={ref}
            theme={light}
            defaultValue={{
              type: "doc",
              content: [
                { type: "table_of_contents" },
                {
                  type: "container_toggle",
                  attrs: { id: "toc-folded-target" },
                  content: [
                    {
                      type: "paragraph",
                      content: [{ type: "text", text: "Folded" }],
                    },
                    {
                      type: "heading",
                      attrs: { level: 2 },
                      content: [{ type: "text", text: "Target" }],
                    },
                  ],
                },
              ],
            }}
            placeholder=""
            embeds={[]}
            extensions={editorExtensions}
            onClickLink={onClickLink}
            readOnly
          />
        </ThemeProvider>,
        host
      );
    });
    const editor = ref.current;
    if (!editor) {
      throw new Error("Editor was not mounted");
    }
    expect(
      toggleFoldPluginKey
        .getState(editor.view.state)
        ?.foldedIds.has("toc-folded-target")
    ).toBe(true);
    await act(async () => {
      host
        .querySelector("nav a")
        ?.dispatchEvent(
          new MouseEvent("click", { bubbles: true, cancelable: true })
        );
    });
    expect(onClickLink).toHaveBeenCalledWith(
      "#h-target",
      expect.any(MouseEvent)
    );
    expect(
      toggleFoldPluginKey
        .getState(editor.view.state)
        ?.foldedIds.has("toc-folded-target")
    ).toBe(false);
  });
});
