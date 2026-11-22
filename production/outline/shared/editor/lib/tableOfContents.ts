import { t } from "i18next";
import { HeadingPrefixStyle } from "../../types";
import type { Heading } from "../../utils/ProsemirrorHelper";
import { sanitizeUrl } from "../../utils/urls";
import { HeadingPrefixHelper } from "../extensions/HeadingPrefix";

/** A heading displayed in a document's inline table of contents. */
export interface TableOfContentsItem extends Heading {
  /** Indentation relative to the shallowest displayed heading. */
  depth: number;
  /** Section number using the document's heading prefix preference. */
  label?: string;
}

/**
 * Builds contents using the same level, table, and numbering rules as the sidebar.
 *
 * @param headings all headings, including headings inside tables.
 * @param style the document's heading prefix preference.
 * @returns the headings displayed in the contents.
 */
export function getTableOfContentsItems(
  headings: Heading[],
  style = HeadingPrefixStyle.None
): TableOfContentsItem[] {
  const numbered = headings.filter((heading) => !heading.inTable);
  const labels =
    style === HeadingPrefixStyle.None
      ? undefined
      : HeadingPrefixHelper.labels(
          numbered.map((heading) => heading.level),
          style,
          { indented: true }
        );
  const items = numbered
    .map((heading, index) => ({ ...heading, label: labels?.[index] }))
    .filter((heading) => heading.level <= 4);
  const minLevel = Math.min(...items.map((heading) => heading.level));
  return items.map((heading) => ({
    ...heading,
    depth: heading.level - minLevel,
  }));
}

/**
 * Renders a contents block for both the live editor and static HTML export.
 * User content is assigned as text rather than interpreted as HTML.
 *
 * @param element the contents block to populate.
 * @param items the headings to display.
 */
export function renderTableOfContents(
  element: HTMLElement,
  items: TableOfContentsItem[]
): void {
  const owner = element.ownerDocument;
  const title = owner.createElement("div");
  title.className = "table-of-contents-title";
  title.textContent = t("Contents");
  element.setAttribute("aria-label", t("Table of contents"));

  if (!items.length) {
    const empty = owner.createElement("div");
    empty.className = "table-of-contents-empty";
    empty.textContent = t("Headings you add to the document will appear here");
    element.replaceChildren(title, empty);
    return;
  }

  const list = owner.createElement("ul");
  for (const item of items) {
    const row = owner.createElement("li");
    row.style.marginInlineStart = `${item.depth * 16}px`;
    const link = owner.createElement("a");
    link.href = sanitizeUrl(`#${item.id}`) ?? "#";
    if (item.label) {
      const prefix = owner.createElement("span");
      prefix.className = "table-of-contents-prefix";
      prefix.textContent = `${item.label} `;
      link.append(prefix);
    }
    link.append(owner.createTextNode(item.title || t("Untitled")));
    row.append(link);
    list.append(row);
  }
  element.replaceChildren(title, list);
}
