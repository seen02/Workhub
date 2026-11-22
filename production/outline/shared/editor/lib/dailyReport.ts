import type { Node } from "prosemirror-model";
import type { DailyReportSection } from "../../utils/dailyReport";
import { dailyReportSections, isReportTable } from "../../utils/dailyReport";

/** Refreshes view-only report controls after permissions or preferences change. */
export const dailyReportSettingsMeta = "dailyReportSettingsChanged";

/** A report's live editor positions, independent of whether its title is a native toggle. */
export interface EditorReportRange {
  section: DailyReportSection;
  from: number;
  to: number;
  headingPos: number;
  tables: { node: Node; pos: number; key: string }[];
}

/** Maps recognized report sections to live ProseMirror positions, preserving nested containers. */
export function editorReportRanges(doc: Node): EditorReportRange[] {
  return dailyReportSections(doc.toJSON()).map((section) => {
    let parent = doc;
    let base = 0;
    for (const index of section.parentPath ?? []) {
      for (let i = 0; i < index; i++) {
        base += parent.child(i).nodeSize;
      }
      parent = parent.child(index);
      base++;
    }
    let from = base;
    for (let i = 0; i < section.start; i++) {
      from += parent.child(i).nodeSize;
    }
    let to = from;
    for (let i = section.start; i < section.end; i++) {
      to += parent.child(i).nodeSize;
    }
    const toggle = section.toggle ? parent.child(section.start) : undefined;
    const headingPos = from + (toggle ? 1 : 0);
    const nodes = toggle
      ? Array.from({ length: toggle.childCount }, (_, index) =>
          toggle.child(index)
        ).slice(1)
      : Array.from({ length: section.end - section.start - 1 }, (_, index) =>
          parent.child(section.start + index + 1)
        );
    let pos =
      headingPos +
      (toggle ? toggle.child(0) : parent.child(section.start)).nodeSize;
    const tables: EditorReportRange["tables"] = [];
    nodes.forEach((node, index) => {
      if (isReportTable(node.toJSON())) {
        tables.push({
          node,
          pos,
          key: `${String(section.toggle?.attrs?.id ?? (section.parentPath ?? []).join("."))}:${section.date}:${index}`,
        });
      }
      pos += node.nodeSize;
    });
    return { section, from, to, headingPos, tables };
  });
}
