import i18next from "i18next";
import { JSDOM } from "jsdom";
import { beforeAll, describe, expect, it } from "vitest";
import { HeadingPrefixStyle } from "@shared/types";
import { ProsemirrorHelper as SharedProsemirrorHelper } from "@shared/utils/ProsemirrorHelper";
import { DocumentConverter } from "@server/converters/DocumentConverter";
import { parser, schema, serializer } from "@server/editor";
import { DocumentHelper } from "@server/models/helpers/DocumentHelper";
import { ProsemirrorHelper } from "@server/models/helpers/ProsemirrorHelper";

beforeAll(async () => {
  await i18next.init({ lng: "en", fallbackLng: "en", resources: {} });
});

describe("table of contents export", () => {
  it("preserves the node through the server's internal Markdown pipeline", () => {
    const doc = parser.parse("[[_OUTLINE_TOC_]]\n\n# Title");
    expect(doc?.firstChild?.type.name).toBe("table_of_contents");
    expect(parser.parse(serializer.serialize(doc))?.toJSON()).toEqual(
      doc?.toJSON()
    );
  });

  it("renders static HTML links with matching duplicate targets and current numbering", async () => {
    const doc = schema.nodes.doc.create(null, [
      schema.nodes.table_of_contents.create(),
      schema.nodes.heading.create({ level: 1 }, schema.text("Same")),
      schema.nodes.heading.create({ level: 2 }, schema.text("Same")),
      schema.nodes.heading.create(
        { level: 4 },
        schema.text("<script>unsafe</script>")
      ),
    ]);
    const html = await ProsemirrorHelper.toHTML(doc, {
      includeStyles: false,
      includeHead: false,
      headingPrefix: HeadingPrefixStyle.Outline,
    });
    const dom = new JSDOM(html);
    try {
      const document = dom.window.document;
      const links = [...document.querySelectorAll<HTMLAnchorElement>("nav a")];
      expect(links.map((link) => link.textContent)).toEqual([
        "I Same",
        "A Same",
        "1 <script>unsafe</script>",
      ]);
      for (const link of links) {
        const target = document.getElementById(link.hash.slice(1));
        expect(target?.classList.contains("heading-content")).toBe(true);
      }
      expect(document.querySelector("nav script")).toBeNull();
      expect(document.querySelector("[contenteditable=true]")).toBeNull();
    } finally {
      dom.window.close();
    }
    const imported = await DocumentConverter.htmlToProsemirror(html);
    expect(imported.firstChild?.type.name).toBe("table_of_contents");
    expect(
      SharedProsemirrorHelper.getHeadings(imported).map(
        (heading) => heading.title
      )
    ).toEqual(["Same", "Same", "<script>unsafe</script>"]);
  });

  it("keeps independently rendered export views isolated", async () => {
    const left = parser.parse("[[_OUTLINE_TOC_]]\n\n# Left");
    const right = parser.parse("[[_OUTLINE_TOC_]]\n\n# Right");
    if (!left || !right) {
      throw new Error("Expected test documents");
    }
    const [leftHTML, rightHTML] = await Promise.all([
      ProsemirrorHelper.toHTML(left, {
        includeHead: false,
        headingPrefix: HeadingPrefixStyle.Outline,
      }),
      ProsemirrorHelper.toHTML(right, { includeHead: false }),
    ]);
    expect(leftHTML).toContain("h-left");
    expect(leftHTML).not.toContain("h-right");
    expect(rightHTML).toContain("h-right");
    expect(rightHTML).not.toContain("h-left");
  });

  it("writes portable Markdown through the external document export path", async () => {
    const doc = parser.parse("[[_OUTLINE_TOC_]]\n\n# Title");
    if (!doc) {
      throw new Error("Expected test document");
    }
    const text = await DocumentHelper.toMarkdown(doc.toJSON(), {
      commonMark: true,
      includeTitle: false,
    });
    expect(text).toContain("[Title](#h-title)");
    expect(text).toContain('<a id="h-title"></a>');
    expect(text).not.toContain("[[_OUTLINE_TOC_]]");
  });
});
