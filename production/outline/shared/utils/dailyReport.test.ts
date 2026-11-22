import { describe, expect, it } from "vitest";
import type { ProsemirrorData } from "../types";
import {
  DailyReportMode,
  DocumentPreference,
  HeadingPrefixStyle,
  TeamPreference,
} from "../types";
import {
  carryReportItems,
  createReportDay,
  dailyReportSections,
  dailyReportCreationPreferences,
  dailyReportToolsEnabled,
  normalizeDailyReportMode,
  filterReportWorker,
  isDailyReport,
  reportCarryItems,
  reportCommonBlocks,
  reportHeadingDate,
  reportText,
  reportToday,
  reportWorkers,
  replaceReportSection,
  wrapReportSection,
} from "./dailyReport";

const p = (text: string): ProsemirrorData => ({
  type: "paragraph",
  content: [{ type: "text", text }],
});
const cell = (text: string): ProsemirrorData => ({
  type: "td",
  content: [p(text)],
});
const heading = (text: string, level = 1): ProsemirrorData => ({
  type: "heading",
  attrs: { level },
  content: [{ type: "text", text }],
});
const table: ProsemirrorData = {
  type: "table",
  content: [
    {
      type: "tr",
      content: [
        cell("작업자"),
        cell("계속 되는 작업"),
        cell("당일 완료 예정 작업"),
        cell("참고"),
      ],
    },
    {
      type: "tr",
      content: [
        cell("김지웅"),
        cell("- [ ] 배속 시스템 변경[x] 이전 테스트 완료[ ] 로그 방식 변경"),
        cell("- [ ] 테스트 실행"),
        cell("[ ] 검토 의견"),
      ],
    },
    {
      type: "tr",
      content: [
        cell("정수민"),
        {
          type: "td",
          content: [
            {
              type: "checkbox_list",
              content: [
                {
                  type: "checkbox_item",
                  attrs: { checked: false },
                  content: [p("영상 편집")],
                },
                {
                  type: "checkbox_item",
                  attrs: { checked: true },
                  content: [p("시나리오 완료")],
                },
              ],
            },
          ],
        },
        cell(""),
        cell(""),
      ],
    },
  ],
};
const data: ProsemirrorData = {
  type: "doc",
  content: [
    heading("K-Geo Festa용 영상 자료"),
    p("AI Ready"),
    heading("2026.10.26. 월"),
    table,
    heading("2026.10.23. 금"),
    table,
  ],
};
const previous = () => dailyReportSections(data)[1];

describe("daily report structured operations", () => {
  it("treats legacy automatic mode as on and defaults new documents to off", () => {
    expect(normalizeDailyReportMode(DailyReportMode.Auto)).toBe(
      DailyReportMode.On
    );
    expect(normalizeDailyReportMode(undefined)).toBe(DailyReportMode.On);
    expect(normalizeDailyReportMode(DailyReportMode.Off)).toBe(
      DailyReportMode.Off
    );
    expect(
      dailyReportCreationPreferences({ dailyReportTools: DailyReportMode.Auto })
    ).toEqual({ dailyReportTools: DailyReportMode.On });
    expect(dailyReportToolsEnabled(null, null)).toBe(true);
    expect(dailyReportCreationPreferences()).toEqual({
      dailyReportTools: DailyReportMode.Off,
    });
    expect(
      dailyReportToolsEnabled(null, dailyReportCreationPreferences())
    ).toBe(false);
    expect(
      dailyReportCreationPreferences({
        headingPrefix: HeadingPrefixStyle.Numeric,
        dailyReportTools: DailyReportMode.On,
      })
    ).toEqual({
      headingPrefix: HeadingPrefixStyle.Numeric,
      dailyReportTools: DailyReportMode.On,
    });
  });
  it("always gives the workspace master switch precedence over every document mode", () => {
    for (const mode of Object.values(DailyReportMode)) {
      const preferences = { [DocumentPreference.DailyReportTools]: mode };
      expect(
        dailyReportToolsEnabled(
          { [TeamPreference.DailyReports]: false },
          preferences
        )
      ).toBe(false);
      expect(
        dailyReportToolsEnabled(
          { [TeamPreference.DailyReports]: true },
          preferences
        )
      ).toBe(mode !== DailyReportMode.Off);
    }
  });
  it("recognizes nested native toggles and preserves their ids and surrounding content", () => {
    const toggle: ProsemirrorData = {
      type: "container_toggle",
      attrs: { id: "day-native" },
      content: [heading("2026.10.23. 금"), table],
    };
    const nested: ProsemirrorData = {
      type: "doc",
      content: [
        {
          type: "container_toggle",
          attrs: { id: "month" },
          content: [p("10월"), toggle, p("마지막 메모")],
        },
        p("문서 메모"),
      ],
    };
    const section = dailyReportSections(nested)[0];
    expect(section.parentPath).toEqual([0]);
    expect(section.toggle?.attrs?.id).toBe("day-native");
    expect(reportCarryItems(section)).toHaveLength(4);
    const result = replaceReportSection(
      nested,
      section,
      wrapReportSection(section, [section.heading, p("하위 문서 링크")])
    );
    expect(result.content?.[0].attrs?.id).toBe("month");
    expect(result.content?.[0].content?.[1].attrs?.id).toBe("day-native");
    expect(reportText(result.content?.[0].content?.[2] ?? p(""))).toBe(
      "마지막 메모"
    );
    expect(result.content?.[1]).toEqual(p("문서 메모"));
    expect(nested.content?.[0].content?.[1]).toEqual(toggle);
  });
  it("ends a plain date section before the following native date toggle", () => {
    const sections = dailyReportSections({
      type: "doc",
      content: [
        heading("2026.10.26. 월"),
        table,
        {
          type: "container_toggle",
          attrs: { id: "old" },
          content: [heading("2026.10.23. 금"), table],
        },
      ],
    });
    expect(sections).toHaveLength(2);
    expect(sections[0].blocks).toEqual([table]);
    expect(sections[0].end).toBe(2);
    expect(sections[1].toggle?.attrs?.id).toBe("old");
  });
  it("preserves Outline line breaks in candidate text and carried nodes", () => {
    const richTable = structuredClone(table);
    const first = richTable.content?.[1]?.content?.[1];
    if (!first) {
      throw new Error("Missing cell");
    }
    first.content = [
      {
        type: "paragraph",
        content: [
          { type: "text", text: "[ ] 테스트" },
          { type: "br" },
          { type: "text", text: "지연 사유" },
        ],
      },
    ];
    const item = reportCarryItems({ ...previous(), blocks: [richTable] })[0];
    expect(item.text).toBe("테스트\n지연 사유");
    expect(
      item.node.content?.[0]?.content?.some((node) => node.type === "br")
    ).toBe(true);
  });
  it("recognizes Korean date headings and rejects invalid dates and embedded prose", () => {
    expect(reportHeadingDate("2026.10.26. 월")).toBe("2026-10-26");
    expect(reportHeadingDate("2026-10-26 (월)")).toBe("2026-10-26");
    expect(reportHeadingDate("2026.02.30. 월")).toBeUndefined();
    expect(reportHeadingDate("2026.10.26. 업무 진행")).toBeUndefined();
  });
  it("uses Korean midnight even when the server is on UTC", () => {
    expect(reportToday(new Date("2026-10-25T15:00:00Z"))).toBe("2026-10-26");
    expect(reportToday(new Date("2026-10-25T14:59:59Z"))).toBe("2026-10-25");
  });
  it("finds only top-level sections and keeps common content separate", () => {
    expect(dailyReportSections(data).map((section) => section.date)).toEqual([
      "2026-10-26",
      "2026-10-23",
    ]);
    expect(reportCommonBlocks(data, dailyReportSections(data))).toEqual(
      data.content?.slice(0, 2)
    );
    expect(isDailyReport(data)).toBe(true);
    expect(
      dailyReportSections({
        type: "doc",
        content: [
          {
            ...table,
            content: [
              {
                type: "tr",
                content: [{ type: "td", content: [heading("2026.10.26. 월")] }],
              },
            ],
          },
        ],
      })
    ).toHaveLength(0);
  });
  it("stops before a same-level non-date heading, including trailing notes", () => {
    const sections = dailyReportSections({
      type: "doc",
      content: [
        heading("2026.10.23. 금"),
        table,
        heading("다음 주 참고"),
        p("유지"),
      ],
    });
    expect(sections[0].end).toBe(2);
  });
  it("filters exact worker rows without modifying stored cells", () => {
    const before = JSON.stringify(data);
    const filtered = filterReportWorker([table], "김지웅")[0];
    expect(filtered.content).toHaveLength(2);
    expect(reportWorkers(dailyReportSections(data))).toEqual([
      "김지웅",
      "정수민",
    ]);
    expect(JSON.stringify(data)).toBe(before);
    expect(filterReportWorker([table], "없는 사람")[0].content).toHaveLength(1);
  });
  it("excludes finished literal checkboxes, real checkboxes and reference comments", () => {
    const items = reportCarryItems(previous());
    expect(items.map((item) => item.text.trim())).toEqual([
      "배속 시스템 변경",
      "로그 방식 변경",
      "테스트 실행",
      "영상 편집",
    ]);
    expect(new Set(items.map((item) => item.id)).size).toBe(items.length);
  });
  it("keeps inline marks when carrying literal checkboxes", () => {
    const richTable = structuredClone(table);
    const first = richTable.content?.[1]?.content?.[1];
    if (!first) {
      throw new Error("Missing cell");
    }
    first.content = [
      {
        type: "paragraph",
        content: [
          { type: "text", text: "[ ] " },
          { type: "text", text: "강조된 업무", marks: [{ type: "strong" }] },
        ],
      },
    ];
    const item = reportCarryItems({ ...previous(), blocks: [richTable] })[0];
    expect(item.node.content?.[0]?.content?.[0].marks).toEqual([
      { type: "strong" },
    ]);
  });
  it("creates a blank template with the same authors and no copied plans or comments", () => {
    const blocks = createReportDay("2026-10-27", previous());
    expect(reportText(blocks[0])).toBe("2026.10.27. 화");
    expect(reportText(blocks[1])).toContain("김지웅");
    expect(reportText(blocks[1])).not.toContain("검토 의견");
    expect(reportText(blocks[1])).not.toContain("배속");
    expect(blocks[1].content?.[0]).toEqual(table.content?.[0]);
  });
  it("moves chosen items into the ongoing column and makes repeated carry a no-op", () => {
    const items = reportCarryItems(previous());
    const first = carryReportItems(createReportDay("2026-10-27", previous()), [
      items[2],
      items[3],
    ]);
    expect(first.added).toBe(2);
    expect(
      reportText(first.blocks[1].content?.[1]?.content?.[1] ?? p(""))
    ).toContain("테스트 실행");
    expect(
      reportText(first.blocks[1].content?.[1]?.content?.[2] ?? p(""))
    ).toBe("");
    expect(carryReportItems(first.blocks, [items[2], items[3]]).added).toBe(0);
  });
  it("keeps unrelated rich content unchanged when filtering or carrying", () => {
    const image: ProsemirrorData = {
      type: "image",
      attrs: { src: "/api/attachments.redirect?id=asset", alt: "자료" },
    };
    const blocks = [image, ...createReportDay("2026-10-27", previous())];
    expect(
      carryReportItems(blocks, reportCarryItems(previous())).blocks[0]
    ).toEqual(image);
    expect(filterReportWorker(blocks, "김지웅")[0]).toEqual(image);
  });
});
