import type {
  DocumentPreferences,
  ProsemirrorData,
  TeamPreferences,
} from "../types";
import { DailyReportMode, DocumentPreference, TeamPreference } from "../types";

/** Maps legacy automatic mode and unset preferences to the two supported choices.
 *
 * @param mode the stored or incoming document preference.
 * @returns the effective on/off mode.
 */
export function normalizeDailyReportMode(
  mode?: DailyReportMode | null
): DailyReportMode.On | DailyReportMode.Off {
  return mode === DailyReportMode.Off
    ? DailyReportMode.Off
    : DailyReportMode.On;
}

/** Applies the workspace master switch before the document's mode.
 *
 * @param team the current workspace preferences.
 * @param document the current document preferences; existing documents default to on.
 * @returns whether report recognition and tools may run.
 */
export function dailyReportToolsEnabled(
  team?: TeamPreferences | null,
  document?: DocumentPreferences | null
): boolean {
  return (
    team?.[TeamPreference.DailyReports] !== false &&
    normalizeDailyReportMode(
      document?.[DocumentPreference.DailyReportTools]
    ) !== DailyReportMode.Off
  );
}

/** Initializes new documents with report tools off while preserving explicit preferences.
 *
 * @param preferences explicitly requested document preferences.
 * @returns preferences suitable for a newly created document.
 */
export function dailyReportCreationPreferences(
  preferences?: DocumentPreferences | null
): DocumentPreferences {
  return {
    ...preferences,
    [DocumentPreference.DailyReportTools]:
      preferences?.[DocumentPreference.DailyReportTools] === undefined
        ? DailyReportMode.Off
        : normalizeDailyReportMode(
            preferences[DocumentPreference.DailyReportTools]
          ),
  };
}

/** A top-level date heading and the blocks that belong to it. */
export interface DailyReportSection {
  date: string;
  title: string;
  start: number;
  end: number;
  heading: ProsemirrorData;
  blocks: ProsemirrorData[];
  /** Index path to the containing block's content; absent for legacy root sections. */
  parentPath?: number[];
  /** The existing native toggle wrapper, when present. */
  toggle?: ProsemirrorData;
}

/** A selectable, unfinished item from one person's report row. */
export interface CarryReportItem {
  id: string;
  worker: string;
  column: string;
  text: string;
  node: ProsemirrorData;
}

/** A readable day, optionally stored in a child document. */
export interface DailyReportDay extends DailyReportSection {
  sourceDocumentId: string;
  sourceRevision: number;
  movedUrl?: string;
  items: CarryReportItem[];
}

/** Server-authorized snapshot used by the report controls. */
export interface DailyReportSnapshot {
  id: string;
  revision: number;
  today: string;
  canUpdate: boolean;
  canCreateChild: boolean;
  common: ProsemirrorData[];
  days: DailyReportDay[];
  /** Saved structured content used to verify that live edits have reached the server. */
  content?: ProsemirrorData;
}

/** Actions exposed by the native heading menu and slash commands. */
export type DailyReportAction = "create" | "carry" | "extract";

/** Returns readable text, including line breaks, without changing the node. */
export function reportText(node: ProsemirrorData): string {
  if (node.type === "hard_break" || node.type === "br") {
    return "\n";
  }
  return node.text ?? (node.content ?? []).map(reportText).join("");
}

/** Parses a whole date heading; impossible calendar dates are rejected. */
export function reportHeadingDate(title: string): string | undefined {
  const match = title
    .trim()
    .match(
      /^(\d{4})[.\-/]\s*(\d{1,2})[.\-/]\s*(\d{1,2})\.?\s*(?:[월화수목금토일](?:요일)?|\([월화수목금토일](?:요일)?\))?\s*$/
    );
  if (!match) {
    return undefined;
  }
  const [, year, month, day] = match;
  const date = `${year}-${month.padStart(2, "0")}-${day.padStart(2, "0")}`;
  const parsed = new Date(`${date}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) &&
    parsed.toISOString().slice(0, 10) === date
    ? date
    : undefined;
}

/** Returns the current report date in Korea, independently of server timezone. */
export function reportToday(now = new Date()): string {
  return new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
}

/** Formats a date using the existing Korean report heading convention. */
export function reportDateTitle(date: string): string {
  const parsed = new Date(`${date}T00:00:00Z`);
  return `${date.replace(/-/g, ".")}. ${"일월화수목금토"[parsed.getUTCDay()]}`;
}

/** Finds ordinary headings and native toggle titles, ignoring table/list cell headings. */
export function dailyReportSections(
  data: ProsemirrorData
): DailyReportSection[] {
  const sections: DailyReportSection[] = [];
  const visit = (parent: ProsemirrorData, parentPath: number[]) => {
    const blocks = parent.content ?? [];
    for (let start = 0; start < blocks.length; start++) {
      const node = blocks[start];
      const head = node.type === "container_toggle" ? node.content?.[0] : node;
      const date =
        head &&
        (head.type === "heading" ||
          (node.type === "container_toggle" && head.type === "paragraph"))
          ? reportHeadingDate(reportText(head))
          : undefined;
      if (!date || !head) {
        if (
          node.type === "container_toggle" ||
          node.type === "container_notice"
        ) {
          visit(node, [...parentPath, start]);
        }
        continue;
      }
      let end = start + 1;
      if (node.type !== "container_toggle") {
        const level = Number(head.attrs?.level ?? 1);
        while (end < blocks.length) {
          const next = blocks[end];
          const nextHead =
            next.type === "container_toggle" ? next.content?.[0] : next;
          if (
            (next.type === "heading" &&
              Number(next.attrs?.level ?? 1) <= level) ||
            (next.type === "container_toggle" &&
              nextHead &&
              reportHeadingDate(reportText(nextHead)))
          ) {
            break;
          }
          end++;
        }
      }
      sections.push({
        date,
        title: reportText(head),
        start,
        end,
        parentPath,
        heading: head,
        blocks:
          node.type === "container_toggle"
            ? (node.content ?? []).slice(1)
            : blocks.slice(start + 1, end),
        ...(node.type === "container_toggle" ? { toggle: node } : {}),
      });
      start = end - 1;
    }
  };
  visit(data, []);
  return sections;
}

/** Replaces a section in its original container without flattening unrelated content. */
export function replaceReportSection(
  data: ProsemirrorData,
  section: DailyReportSection,
  replacement: ProsemirrorData[]
): ProsemirrorData {
  const path = section.parentPath ?? [];
  const visit = (node: ProsemirrorData, depth: number): ProsemirrorData => {
    const content = [...(node.content ?? [])];
    if (depth === path.length) {
      content.splice(
        section.start,
        section.end - section.start,
        ...replacement
      );
    } else {
      const index = path[depth];
      if (!content[index]) {
        throw new Error("보고 위치가 변경되었습니다.");
      }
      content[index] = visit(content[index], depth + 1);
    }
    return { ...node, content };
  };
  return visit(data, 0);
}

/** Keeps the original native toggle around changed report content. */
export function wrapReportSection(
  section: DailyReportSection,
  blocks: ProsemirrorData[]
): ProsemirrorData[] {
  return section.toggle ? [{ ...section.toggle, content: blocks }] : blocks;
}

/** Identifies a report table by its worker header, never by column position alone. */
export function isReportTable(node: ProsemirrorData): boolean {
  return (
    node.type === "table" &&
    /^(작업자|담당자|이름)$/.test(
      reportText(
        node.content?.[0]?.content?.[0] ?? { type: "paragraph" }
      ).trim()
    )
  );
}

/** Finds the report table in a section. */
export function reportTable(
  section: DailyReportSection
): ProsemirrorData | undefined {
  return section.blocks.find(isReportTable);
}

/** Lists unique report authors in their original order. */
export function reportWorkers(sections: DailyReportSection[]): string[] {
  return [
    ...new Set(
      sections.flatMap((section) =>
        (reportTable(section)?.content ?? [])
          .slice(1)
          .map((row) =>
            reportText(row.content?.[0] ?? { type: "paragraph" }).trim()
          )
          .filter(Boolean)
      )
    ),
  ];
}

/** Filters report rows for display, preserving all original blocks and cell data. */
export function filterReportWorker(
  blocks: ProsemirrorData[],
  worker: string
): ProsemirrorData[] {
  if (!worker) {
    return blocks;
  }
  return blocks.map((node) =>
    isReportTable(node)
      ? {
          ...node,
          content: (node.content ?? []).filter(
            (row, index) =>
              index === 0 ||
              reportText(row.content?.[0] ?? { type: "paragraph" }).trim() ===
                worker
          ),
        }
      : node
  );
}

/** Returns common blocks outside all date sections in their original order. */
export function reportCommonBlocks(
  data: ProsemirrorData,
  sections: DailyReportSection[]
): ProsemirrorData[] {
  return (data.content ?? []).filter(
    (_, index) =>
      !sections.some(
        (section) =>
          !section.parentPath?.length &&
          index >= section.start &&
          index < section.end
      )
  );
}

/** Checks whether the document has report dates and at least one report table or moved-day link. */
export function isDailyReport(data: ProsemirrorData): boolean {
  return dailyReportSections(data).some(
    (section) => !!reportTable(section) || !!reportChildLink(section)
  );
}

/** Finds a section link created by the move command. */
export function reportChildLink(
  section: DailyReportSection
): string | undefined {
  if (section.blocks.length !== 1 || section.blocks[0].type !== "paragraph") {
    return undefined;
  }
  const node = section.blocks[0].content?.[0];
  const href = node?.marks?.find((mark) => mark.type === "link")?.attrs?.href;
  return node?.text?.startsWith("📄 ") &&
    typeof href === "string" &&
    href.startsWith("/doc/")
    ? href
    : undefined;
}

function paragraph(text = ""): ProsemirrorData {
  return {
    type: "paragraph",
    ...(text ? { content: [{ type: "text", text }] } : {}),
  };
}

function inlineRange(
  nodes: ProsemirrorData[],
  from: number,
  to: number
): ProsemirrorData[] {
  let offset = 0;
  return nodes.flatMap((node) => {
    const length = reportText(node).length;
    const start = Math.max(0, from - offset);
    const end = Math.min(length, to - offset);
    offset += length;
    if (end <= start) {
      return [];
    }
    return node.text !== undefined
      ? [{ ...node, text: node.text.slice(start, end) }]
      : [node];
  });
}

function unfinishedNodes(node: ProsemirrorData): ProsemirrorData | undefined {
  if (node.type === "checkbox_item" && node.attrs?.checked === true) {
    return undefined;
  }
  const content = node.content?.flatMap((child) => {
    const result = unfinishedNodes(child);
    return result ? [result] : [];
  });
  if (
    (node.type === "checkbox_list" ||
      node.type === "bullet_list" ||
      node.type === "ordered_list") &&
    !content?.length
  ) {
    return undefined;
  }
  return { ...node, ...(content ? { content } : {}) };
}

/** Collects unfinished real checkboxes and literal Markdown checkboxes in table cells. */
export function reportCarryItems(
  section: DailyReportSection,
  includeCompleted = false
): CarryReportItem[] {
  const table = reportTable(section);
  const headers = table?.content?.[0]?.content ?? [];
  const result: CarryReportItem[] = [];
  (table?.content ?? []).slice(1).forEach((row, rowIndex) => {
    const worker = reportText(row.content?.[0] ?? paragraph()).trim();
    (row.content ?? []).forEach((cell, columnIndex) => {
      const column = reportText(headers[columnIndex] ?? paragraph()).trim();
      if (
        columnIndex === 0 ||
        !/(계속|진행|예정|계획|오늘|당일)/.test(column) ||
        /참고|의견|결과/.test(column)
      ) {
        return;
      }
      const add = (node: ProsemirrorData, path: string) => {
        const text = reportText(node).trim();
        if (text) {
          result.push({
            id: `${section.date}:${rowIndex}:${columnIndex}:${path}`,
            worker,
            column,
            text,
            node,
          });
        }
      };
      const visit = (node: ProsemirrorData, path: string) => {
        const first = node.content?.[0];
        if (
          node.type === "checkbox_item" &&
          first?.type === "paragraph" &&
          /\[[ xX]\]/.test(reportText(first))
        ) {
          visit(
            {
              ...first,
              content: [
                {
                  type: "text",
                  text: node.attrs?.checked === true ? "[x] " : "[ ] ",
                },
                ...(first.content ?? []),
              ],
            },
            `${path}.inline`
          );
          (node.content ?? [])
            .slice(1)
            .forEach((child, index) => visit(child, `${path}.child${index}`));
          return;
        }
        if (
          node.type === "checkbox_item" &&
          (includeCompleted || node.attrs?.checked !== true)
        ) {
          const clean = includeCompleted ? node : unfinishedNodes(node);
          if (clean) {
            add(clean, path);
          }
          return;
        }
        if (node.type === "paragraph") {
          const text = reportText(node);
          const matches = [...text.matchAll(/(?:-\s*)?\[([ xX])\]\s*/g)];
          matches.forEach((match, index) => {
            if (!includeCompleted && match[1] !== " ") {
              return;
            }
            const from = (match.index ?? 0) + match[0].length;
            const to = matches[index + 1]?.index ?? text.length;
            const content = inlineRange(node.content ?? [], from, to);
            add(
              {
                type: "checkbox_item",
                attrs: { checked: false },
                content: [{ type: "paragraph", content }],
              },
              `${path}.${index}`
            );
          });
          return;
        }
        (node.content ?? []).forEach((child, index) =>
          visit(child, `${path}.${index}`)
        );
      };
      (cell.content ?? []).forEach((node, index) => visit(node, String(index)));
    });
  });
  return result;
}

/** Builds a blank report using the existing authors and table headers. */
export function createReportDay(
  date: string,
  source: DailyReportSection
): ProsemirrorData[] {
  const table = reportTable(source);
  if (!table?.content?.length) {
    throw new Error("보고 양식을 찾을 수 없습니다.");
  }
  const rows = table.content.map((row, rowIndex) =>
    rowIndex === 0
      ? row
      : {
          ...row,
          content: (row.content ?? []).map((cell, index) =>
            index === 0 ? cell : { ...cell, content: [paragraph()] }
          ),
        }
  );
  return [
    {
      type: "heading",
      attrs: { ...source.heading.attrs },
      content: [{ type: "text", text: reportDateTitle(date) }],
    },
    { ...table, content: rows },
  ];
}

/** Adds selected work to the ongoing column, skipping duplicates already in that person's row. */
export function carryReportItems(
  blocks: ProsemirrorData[],
  items: CarryReportItem[]
): { blocks: ProsemirrorData[]; added: number } {
  let added = 0;
  const normalize = (text: string) => text.replace(/\s+/g, " ").trim();
  const updated = blocks.map((table) => {
    if (!isReportTable(table)) {
      return table;
    }
    const headers = table.content?.[0]?.content ?? [];
    const targetColumn = headers.findIndex(
      (cell, index) => index > 0 && /(계속|진행)/.test(reportText(cell))
    );
    if (targetColumn < 0) {
      throw new Error("계속 되는 작업 또는 진행 업무 열이 필요합니다.");
    }
    return {
      ...table,
      content: (table.content ?? []).map((row, index) => {
        if (index === 0) {
          return row;
        }
        const worker = reportText(row.content?.[0] ?? paragraph()).trim();
        const existing = new Set(
          reportCarryItems(
            {
              date: "",
              title: "",
              start: 0,
              end: 1,
              heading: paragraph(),
              blocks: [table],
            },
            true
          )
            .filter((item) => item.worker === worker)
            .map((item) => normalize(item.text))
        );
        const seen = new Set<string>();
        const selected = items.filter((item) => {
          const key = normalize(item.text);
          if (item.worker !== worker || existing.has(key) || seen.has(key)) {
            return false;
          }
          seen.add(key);
          return true;
        });
        added += selected.length;
        return {
          ...row,
          content: (row.content ?? []).map((cell, columnIndex) =>
            columnIndex === targetColumn && selected.length
              ? {
                  ...cell,
                  content: [
                    ...(cell.content ?? []).filter((node) =>
                      reportText(node).trim()
                    ),
                    {
                      type: "checkbox_list",
                      content: selected.map((item) => item.node),
                    },
                  ],
                }
              : cell
          ),
        };
      }),
    };
  });
  return { blocks: updated, added };
}
