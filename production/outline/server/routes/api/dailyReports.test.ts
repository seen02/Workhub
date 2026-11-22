import Koa from "koa";
import { IncomingMessage, ServerResponse } from "node:http";
import { Socket } from "node:net";
import { randomUUID } from "node:crypto";
import { z } from "zod";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { CollectionPermission, DailyReportMode, UserRole } from "@shared/types";
import { authorize } from "@server/policies";
import { TeamsUpdateSchema } from "./teams/schema";
import {
  DocumentsCreateSchema,
  DocumentsUpdateSchema,
} from "./documents/schema";
import {
  dailyReportSections,
  reportCarryItems,
  reportToday,
} from "@shared/utils/dailyReport";
import { Collection, Document, Team, User } from "@server/models";
import * as creator from "@server/commands/documentCreator";
import { DocumentHelper } from "@server/models/helpers/DocumentHelper";
import router from "./dailyReports";

describe("daily report authorized mutations", () => {
  let user: User;
  let document: Document;
  let collection: Collection;
  let child: Document;
  const rootId = randomUUID();
  const teamId = randomUUID();
  const collectionId = randomUUID();
  const oldDate = "2020-01-01";
  const markdown =
    "# 2020.01.01. 수\n\n| 작업자 | 계속 되는 작업 | 당일 완료 예정 작업 | 참고 |\n| --- | --- | --- | --- |\n| 김지웅 | [ ] 테스트 실행[x] 완료 업무 | | 의견 |";

  beforeEach(() => {
    user = User.build({ id: randomUUID(), teamId, role: UserRole.Member });
    user.team = Team.build({ id: teamId });
    collection = Collection.build({
      id: collectionId,
      teamId,
      permission: CollectionPermission.ReadWrite,
    });
    collection.memberships = [];
    collection.groupMemberships = [];
    document = Document.build({
      id: rootId,
      teamId,
      collectionId,
      title: "업무보고",
      publishedAt: new Date(),
      text: markdown,
      revisionCount: 3,
    });
    child = Document.build({
      id: randomUUID(),
      urlId: "child12345",
      parentDocumentId: rootId,
      teamId,
      collectionId,
      title: "2020.01.01. 수",
      publishedAt: new Date(),
      text: markdown,
      revisionCount: 1,
    });
    for (const doc of [document, child]) {
      doc.collection = collection;
      doc.memberships = [];
      doc.groupMemberships = [];
    }
    vi.spyOn(Document, "unscoped").mockReturnValue(Document);
    vi.spyOn(Document, "findOne").mockResolvedValue(document);
    vi.spyOn(Document, "findByPk").mockImplementation(async (id) =>
      id === rootId ? document : child
    );
    vi.spyOn(Collection, "findByPk").mockResolvedValue(collection);
    vi.spyOn(Document.prototype, "saveWithCtx").mockResolvedValue(document);
    vi.spyOn(creator, "default").mockResolvedValue(child);
  });
  afterEach(() => vi.restoreAllMocks());

  async function invoke(method: string, body: object) {
    const incoming = new IncomingMessage(new Socket());
    const ctx = Object.assign(
      new Koa().createContext(incoming, new ServerResponse(incoming)),
      {
        input: { body },
        params: {},
        router,
        _matchedRoute: method,
        _matchedRouteName: undefined,
      }
    );
    ctx.state.auth = { user };
    ctx.state.transaction = { LOCK: { UPDATE: "UPDATE" } };
    const handler = router.stack
      .find((route) => route.path === method)
      ?.stack.at(-1);
    if (!handler) {
      throw new Error("Missing handler");
    }
    await handler(ctx, async () => {});
    return {
      body: z
        .object({
          data: z.object({
            canUpdate: z.boolean().optional(),
            existing: z.boolean().optional(),
            days: z
              .array(
                z.object({ items: z.array(z.object({ text: z.string() })) })
              )
              .default([]),
          }),
        })
        .parse(ctx.body),
    };
  }
  const body = () => ({
    id: rootId,
    revision: 3,
    action: "extract",
    date: oldDate,
    itemIds: [],
  });

  it("returns only checked-policy snapshots and unfinished candidates", async () => {
    const ctx = await invoke("dailyReports.info", { id: rootId });
    expect(
      ctx.body.data.days[0].items.map((item: { text: string }) => item.text)
    ).toEqual(["테스트 실행"]);
    expect(ctx.body.data.canUpdate).toBe(true);
  });
  it("rejects all report reads and mutations when the workspace switch is off, even for an enabled document", async () => {
    user.team.preferences = { dailyReports: false };
    document.preferences = { dailyReportTools: DailyReportMode.On };
    await expect(invoke("dailyReports.info", { id: rootId })).rejects.toThrow(
      "관리자"
    );
    await expect(invoke("dailyReports.mutate", body())).rejects.toThrow(
      "관리자"
    );
    expect(Document.findByPk).not.toHaveBeenCalled();
    expect(creator.default).not.toHaveBeenCalled();
  });
  it("respects the document's off switch while the workspace is on", async () => {
    user.team.preferences = { dailyReports: true };
    document.preferences = { dailyReportTools: DailyReportMode.Off };
    await expect(invoke("dailyReports.info", { id: rootId })).rejects.toThrow(
      "이 문서"
    );
    await expect(invoke("dailyReports.mutate", body())).rejects.toThrow(
      "이 문서"
    );
    expect(document.saveWithCtx).not.toHaveBeenCalled();
  });
  it("keeps preference validation strict and uses the existing administrator policy", () => {
    expect(
      TeamsUpdateSchema.safeParse({
        query: {},
        body: { preferences: { dailyReports: false } },
      }).success
    ).toBe(true);
    expect(
      TeamsUpdateSchema.safeParse({
        query: {},
        body: { preferences: { dailyReports: "false" } },
      }).success
    ).toBe(false);
    expect(() => authorize(user, "update", user.team)).toThrow();
    user.role = UserRole.Admin;
    expect(() => authorize(user, "update", user.team)).not.toThrow();
    for (const dailyReportTools of Object.values(DailyReportMode)) {
      expect(
        DocumentsUpdateSchema.safeParse({
          query: {},
          body: { id: rootId, preferences: { dailyReportTools } },
        }).success
      ).toBe(true);
      expect(
        DocumentsCreateSchema.safeParse({
          query: {},
          body: { collectionId, preferences: { dailyReportTools } },
        }).success
      ).toBe(true);
    }
    expect(
      DocumentsUpdateSchema.safeParse({
        query: {},
        body: { id: rootId, preferences: { dailyReportTools: "invalid" } },
      }).success
    ).toBe(false);
  });
  it("denies mutations for a read-only collection before creating a child", async () => {
    collection.permission = CollectionPermission.Read;
    await expect(invoke("dailyReports.mutate", body())).rejects.toThrow();
    expect(creator.default).not.toHaveBeenCalled();
    expect(document.saveWithCtx).not.toHaveBeenCalled();
  });
  it("extracts a native toggle without flattening its outer container or duplicating its id", async () => {
    const original = await DocumentHelper.toJSON(document);
    document.content = {
      type: "doc",
      content: [
        {
          type: "container_toggle",
          attrs: { id: "month" },
          content: [
            {
              type: "paragraph",
              content: [{ type: "text", text: "월간 보고" }],
            },
            {
              type: "container_toggle",
              attrs: { id: "day" },
              content: original.content,
            },
            {
              type: "paragraph",
              content: [{ type: "text", text: "뒤쪽 메모" }],
            },
          ],
        },
      ],
    };
    await invoke("dailyReports.mutate", body());
    const updated = await DocumentHelper.toJSON(document);
    expect(updated.content?.[0].attrs?.id).toBe("month");
    const day = updated.content?.[0].content?.[1];
    expect(day?.attrs?.id).toBe("day");
    expect(day?.content?.[1].content?.[0].marks?.[0].attrs?.href).toBe(
      child.path
    );
    expect(updated.content?.[0].content?.[2].content?.[0].text).toBe(
      "뒤쪽 메모"
    );
    expect(creator.default).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ content: original })
    );
  });
  it("creates and carries inside the same native parent while retaining the old toggle", async () => {
    const original = await DocumentHelper.toJSON(document);
    document.content = {
      type: "doc",
      content: [
        {
          type: "container_toggle",
          attrs: { id: "month" },
          content: [
            {
              type: "paragraph",
              content: [{ type: "text", text: "월간 보고" }],
            },
            {
              type: "container_toggle",
              attrs: { id: "old-day" },
              content: original.content,
            },
          ],
        },
      ],
    };
    const source = dailyReportSections(document.content)[0];
    const candidate = reportCarryItems(source)[0];
    await invoke("dailyReports.mutate", {
      ...body(),
      action: "create",
      sourceDate: oldDate,
      sourceRevision: 3,
      itemIds: [candidate.id],
    });
    const updated = await DocumentHelper.toJSON(document);
    expect(updated.content?.[0].attrs?.id).toBe("month");
    const days = dailyReportSections(updated);
    expect(days.map((day) => day.date)).toEqual([reportToday(), oldDate]);
    expect(days[0].parentPath).toEqual([0]);
    expect(days[0].toggle?.attrs?.id).toBeTruthy();
    expect(days[0].toggle?.attrs?.id).not.toBe("old-day");
    expect(days[1].toggle?.attrs?.id).toBe("old-day");
    expect(days[1].blocks).toEqual(source.blocks);
    expect(reportCarryItems(days[0])[0].text).toBe(candidate.text);
    const first = await DocumentHelper.toJSON(document);
    await invoke("dailyReports.mutate", {
      ...body(),
      action: "carry",
      revision: document.revisionCount,
      sourceDate: oldDate,
      sourceRevision: document.revisionCount,
      itemIds: [candidate.id],
    });
    expect(await DocumentHelper.toJSON(document)).toEqual(first);
  });
  it("imports and exports reports using the existing toggle Markdown syntax", async () => {
    document.text = `++++++++++\n${markdown}\n++++++++++`;
    const content = await DocumentHelper.toJSON(document);
    expect(dailyReportSections(content)[0].toggle?.type).toBe(
      "container_toggle"
    );
    const exported = await DocumentHelper.toMarkdown(document);
    document.content = null;
    document.text = exported;
    expect(
      dailyReportSections(await DocumentHelper.toJSON(document))[0].blocks
    ).toEqual(dailyReportSections(content)[0].blocks);
  });
  it("rejects a stale source revision without changing content", async () => {
    await expect(
      invoke("dailyReports.mutate", { ...body(), revision: 2 })
    ).rejects.toThrow("다른 편집");
    expect(creator.default).not.toHaveBeenCalled();
  });
  it("moves the exact section under its parent and preserves the heading and link", async () => {
    const original = await DocumentHelper.toJSON(document);
    await invoke("dailyReports.mutate", body());
    expect(creator.default).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({
        parentDocumentId: rootId,
        collectionId,
        content: original,
        publish: true,
      })
    );
    const updated = await DocumentHelper.toJSON(document);
    expect(updated.content?.[0]).toEqual(original.content?.[0]);
    expect(updated.content?.[1]?.content?.[0]?.marks?.[0]?.attrs?.href).toBe(
      child.path
    );
    expect(updated.content?.some((node) => node.type === "table")).toBe(false);
  });
  it("does not remove the source if child creation fails", async () => {
    const original = await DocumentHelper.toJSON(document);
    vi.mocked(creator.default).mockRejectedValueOnce(
      new Error("creation failed")
    );
    await expect(invoke("dailyReports.mutate", body())).rejects.toThrow(
      "creation failed"
    );
    expect(await DocumentHelper.toJSON(document)).toEqual(original);
    expect(document.saveWithCtx).not.toHaveBeenCalled();
  });
  it("rejects forged item ids and old source snapshots", async () => {
    await expect(
      invoke("dailyReports.mutate", {
        ...body(),
        action: "create",
        sourceDate: oldDate,
        sourceRevision: 3,
        itemIds: ["forged"],
      })
    ).rejects.toThrow("선택");
    await expect(
      invoke("dailyReports.mutate", {
        ...body(),
        action: "create",
        sourceDate: oldDate,
        sourceRevision: 2,
        itemIds: ["anything"],
      })
    ).rejects.toThrow("이전 보고가 변경");
    expect(document.saveWithCtx).not.toHaveBeenCalled();
  });
  it("creates a blank day without carrying completed work or comments", async () => {
    await invoke("dailyReports.mutate", {
      ...body(),
      action: "create",
      sourceDate: oldDate,
    });
    const content = await DocumentHelper.toJSON(document);
    expect(
      content.content?.filter((node) => node.type === "table")
    ).toHaveLength(2);
    const todayTable = content.content?.[1];
    expect(JSON.stringify(todayTable)).toContain("김지웅");
    expect(JSON.stringify(todayTable)).not.toContain("완료 업무");
    expect(JSON.stringify(todayTable)).not.toContain("의견");
  });
  it("returns an existing day on retry, even when the original revision is stale", async () => {
    const today = reportToday().replace(/-/g, ".");
    document.text = markdown + `\n\n# ${today}.\n\n이미 작성한 내용`;
    const ctx = await invoke("dailyReports.mutate", {
      ...body(),
      revision: 0,
      action: "create",
    });
    expect(ctx.body.data.existing).toBe(true);
    expect(document.saveWithCtx).not.toHaveBeenCalled();
  });
  it("rejects another team's document even for the same collection id", async () => {
    document.teamId = randomUUID();
    await expect(invoke("dailyReports.info", { id: rootId })).rejects.toThrow();
  });
});
