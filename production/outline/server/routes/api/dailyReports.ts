import Router from "koa-router";
import { randomUUID } from "node:crypto";
import { Node } from "prosemirror-model";
import { z } from "zod";
import { DocumentPreference } from "@shared/types";
import type {
  DailyReportDay,
  DailyReportSnapshot,
  DailyReportSection,
} from "@shared/utils/dailyReport";
import {
  carryReportItems,
  createReportDay,
  dailyReportSections,
  dailyReportToolsEnabled,
  reportCarryItems,
  reportChildLink,
  reportCommonBlocks,
  reportTable,
  reportToday,
  reportWorkers,
  replaceReportSection,
  wrapReportSection,
} from "@shared/utils/dailyReport";
import parseDocumentSlug from "@shared/utils/parseDocumentSlug";
import documentCreator, {
  authorizeDocumentCreate,
} from "@server/commands/documentCreator";
import { schema } from "@server/editor";
import auth from "@server/middlewares/authentication";
import { transaction } from "@server/middlewares/transaction";
import validate from "@server/middlewares/validate";
import { Document } from "@server/models";
import { DocumentHelper } from "@server/models/helpers/DocumentHelper";
import { authorize, can } from "@server/policies";
import type { APIContext } from "@server/types";
import { BaseSchema } from "./schema";

const router = new Router();
const infoSchema = BaseSchema.extend({
  body: z.object({ id: z.string().uuid() }).strict(),
});
const mutationSchema = BaseSchema.extend({
  body: z
    .object({
      id: z.string().uuid(),
      revision: z.number().int().nonnegative(),
      action: z.enum(["create", "carry", "extract"]),
      date: z
        .string()
        .regex(/^\d{4}-\d{2}-\d{2}$/)
        .optional(),
      sourceDate: z
        .string()
        .regex(/^\d{4}-\d{2}-\d{2}$/)
        .optional(),
      sourceRevision: z.number().int().nonnegative().optional(),
      itemIds: z.array(z.string().max(200)).max(500).default([]),
    })
    .strict(),
});

/** Loads an authorized source; mutation callers serialize on the root row first. */
async function loadReport(
  ctx: APIContext,
  id: string,
  lock = false
): Promise<Document> {
  const { user } = ctx.state.auth;
  if (!dailyReportToolsEnabled(user.team.preferences)) {
    ctx.throw(403, "관리자가 워크스페이스의 업무보고 도구를 껐습니다.");
  }
  const tx = ctx.state.transaction;
  if (lock && tx) {
    await Document.unscoped().findOne({
      where: { id, teamId: user.teamId },
      attributes: ["id"],
      transaction: tx,
      lock: tx.LOCK.UPDATE,
    });
  }
  const document = await Document.findByPk(id, {
    userId: user.id,
    includeState: true,
    transaction: tx,
  });
  authorize(user, "read", document);
  if (
    document &&
    !dailyReportToolsEnabled(user.team.preferences, document.preferences)
  ) {
    ctx.throw(403, "이 문서의 업무보고 도구가 꺼져 있습니다.");
  }
  if (
    !document ||
    document.isDraft ||
    document.isArchived ||
    document.deletedAt ||
    !document.collectionId
  ) {
    ctx.throw(400, "게시된 활성 문서에서 업무보고 기능을 사용하세요.");
  }
  return document;
}

/** Resolves a moved day only when it still belongs to this parent and is readable. */
async function resolveDay(
  ctx: APIContext,
  root: Document,
  section: DailyReportSection,
  lock = false
): Promise<{
  document: Document;
  section: DailyReportSection;
  movedUrl?: string;
}> {
  const movedUrl = reportChildLink(section);
  if (!movedUrl) {
    return { document: root, section };
  }
  const slug = parseDocumentSlug(movedUrl);
  if (!slug) {
    ctx.throw(400, "하위 문서 링크를 확인하세요.");
  }
  const child = await Document.findByPk(slug, {
    userId: ctx.state.auth.user.id,
    transaction: ctx.state.transaction,
  });
  authorize(ctx.state.auth.user, "read", child);
  if (
    !child ||
    child.parentDocumentId !== root.id ||
    child.teamId !== root.teamId
  ) {
    ctx.throw(409, "하위 문서의 위치가 바뀌었습니다. 문서를 새로고침하세요.");
  }
  const document = await loadReport(ctx, child.id, lock);
  const childSection = dailyReportSections(
    await DocumentHelper.toJSON(document)
  ).find((day) => day.date === section.date);
  if (!childSection) {
    ctx.throw(409, "하위 문서의 날짜 제목이 변경되었습니다.");
  }
  return { document, section: childSection, movedUrl };
}

/** Persists exact structured content and schedules the standard collaboration event. */
async function saveContent(
  ctx: APIContext,
  document: Document,
  content: NonNullable<Document["content"]>
) {
  const node = Node.fromJSON(schema, content);
  node.check();
  DocumentHelper.applyProsemirrorToDocument(document, node);
  document.lastModifiedById = ctx.state.auth.user.id;
  document.updatedBy = ctx.state.auth.user;
  await document.saveWithCtx(ctx);
}

router.post(
  "dailyReports.info",
  auth(),
  validate(infoSchema),
  async (ctx: APIContext<z.infer<typeof infoSchema>>) => {
    const document = await loadReport(ctx, ctx.input.body.id);
    const data = await DocumentHelper.toJSON(document);
    const sections = dailyReportSections(data);
    const days: DailyReportDay[] = [];
    // Resolve only authorized direct children. A missing/restricted child remains a link.
    for (const section of sections) {
      try {
        const resolved = await resolveDay(ctx, document, section);
        days.push({
          ...section,
          blocks: resolved.section.blocks,
          sourceDocumentId: resolved.document.id,
          sourceRevision: resolved.document.revisionCount,
          movedUrl: resolved.movedUrl,
          items: reportCarryItems(resolved.section),
        });
      } catch (error) {
        if (!reportChildLink(section)) {
          throw error;
        }
        days.push({
          ...section,
          sourceDocumentId: document.id,
          sourceRevision: document.revisionCount,
          movedUrl: reportChildLink(section),
          items: [],
        });
      }
    }
    const result: DailyReportSnapshot = {
      id: document.id,
      revision: document.revisionCount,
      today: reportToday(),
      canUpdate: !!can(ctx.state.auth.user, "update", document),
      canCreateChild: !!can(
        ctx.state.auth.user,
        "createChildDocument",
        document
      ),
      common: reportCommonBlocks(data, sections),
      days,
      content: data,
    };
    ctx.body = { data: result };
  }
);

router.post(
  "dailyReports.mutate",
  auth(),
  validate(mutationSchema),
  transaction(),
  async (ctx: APIContext<z.infer<typeof mutationSchema>>) => {
    const input = ctx.input.body;
    const document = await loadReport(ctx, input.id, true);
    const { user } = ctx.state.auth;
    authorize(user, "update", document);
    const data = await DocumentHelper.toJSON(document);
    const sections = dailyReportSections(data);
    const today = reportToday();
    const matching = sections.filter(
      (section) =>
        section.date === (input.action === "extract" ? input.date : today)
    );
    if (matching.length > 1) {
      ctx.throw(
        409,
        "같은 날짜의 보고가 여러 개 있습니다. 문서에서 날짜 제목을 정리하세요."
      );
    }
    const existing = matching[0];
    // Retry-safe even after the original write advanced the revision.
    if (input.action === "create" && existing) {
      ctx.body = {
        data: {
          existing: true,
          date: today,
          url: reportChildLink(existing) ?? document.path,
          added: 0,
        },
      };
      return;
    }
    if (input.action === "extract" && existing && reportChildLink(existing)) {
      const resolved = await resolveDay(ctx, document, existing);
      ctx.body = {
        data: {
          existing: true,
          date: existing.date,
          url: resolved.document.path,
          added: 0,
        },
      };
      return;
    }
    if (document.revisionCount !== input.revision) {
      ctx.throw(
        409,
        "다른 편집 내용이 저장되었습니다. 새로고침한 뒤 다시 실행하세요."
      );
    }
    if (input.action === "extract") {
      if (!existing || !reportTable(existing)) {
        ctx.throw(400, "이동할 날짜의 업무보고 표를 찾을 수 없습니다.");
      }
      await authorizeDocumentCreate(ctx, {
        parentDocumentId: document.id,
        collectionId: document.collectionId,
      });
      const child = await documentCreator(ctx, {
        parentDocumentId: document.id,
        collectionId: document.collectionId,
        title: existing.title,
        fullWidth: true,
        publish: true,
        preferences: {
          [DocumentPreference.DailyReportTools]: document.getPreference(
            DocumentPreference.DailyReportTools
          ),
        },
        content: {
          type: "doc",
          content: [existing.heading, ...existing.blocks],
        },
      });
      const link = {
        type: "paragraph",
        content: [
          {
            type: "text",
            text: `📄 ${existing.title}`,
            marks: [{ type: "link", attrs: { href: child.path } }],
          },
        ],
      };
      await saveContent(
        ctx,
        document,
        replaceReportSection(
          data,
          existing,
          wrapReportSection(existing, [existing.heading, link])
        )
      );
      ctx.body = { data: { date: existing.date, url: child.path, added: 0 } };
      return;
    }
    const sourceDate =
      input.sourceDate ??
      sections
        .filter((section) => section.date < today)
        .sort((a, b) => b.date.localeCompare(a.date))[0]?.date;
    const sourceSections = sections.filter(
      (section) => section.date === sourceDate && section.date < today
    );
    if (sourceSections.length !== 1) {
      ctx.throw(400, "오늘보다 이전 날짜의 보고 양식을 하나 선택하세요.");
    }
    const source = await resolveDay(ctx, document, sourceSections[0], true);
    if (!reportTable(source.section)) {
      ctx.throw(400, "이전 보고의 작업자 표를 찾을 수 없습니다.");
    }
    if (
      input.itemIds.length &&
      source.document.revisionCount !== input.sourceRevision
    ) {
      ctx.throw(
        409,
        "이전 보고가 변경되었습니다. 이월 항목을 다시 선택하세요."
      );
    }
    const candidates = reportCarryItems(source.section);
    const uniqueIds = [...new Set(input.itemIds)];
    const selected = candidates.filter((item) => uniqueIds.includes(item.id));
    if (selected.length !== uniqueIds.length) {
      ctx.throw(400, "선택한 미완료 항목을 다시 확인하세요.");
    }
    let target = document;
    let targetSection = existing;
    if (existing) {
      const resolved = await resolveDay(ctx, document, existing, true);
      target = resolved.document;
      targetSection = resolved.section;
      authorize(user, "update", target);
    }
    const targetData =
      target.id === document.id ? data : await DocumentHelper.toJSON(target);
    const dayBlocks = targetSection
      ? [targetSection.heading, ...targetSection.blocks]
      : createReportDay(today, source.section);
    const authors = new Set(
      reportWorkers([{ ...source.section, blocks: dayBlocks.slice(1) }])
    );
    if (selected.some((item) => !authors.has(item.worker))) {
      ctx.throw(
        409,
        "오늘 보고에 없는 작업자의 항목이 있습니다. 작업자 행을 추가한 뒤 다시 이월하세요."
      );
    }
    const carried = carryReportItems(dayBlocks, selected);
    let updated: NonNullable<Document["content"]>;
    if (targetSection) {
      updated = replaceReportSection(
        targetData,
        targetSection,
        wrapReportSection(targetSection, carried.blocks)
      );
    } else {
      const placement = sourceSections[0];
      const siblings = sections.filter(
        (section) =>
          JSON.stringify(section.parentPath ?? []) ===
          JSON.stringify(placement.parentPath ?? [])
      );
      const start = Math.min(...siblings.map((section) => section.start));
      const blocks =
        source.section.toggle || placement.toggle
          ? [
              {
                type: "container_toggle",
                attrs: { id: randomUUID() },
                content: carried.blocks,
              },
            ]
          : carried.blocks;
      updated = replaceReportSection(
        targetData,
        { ...placement, start, end: start },
        blocks
      );
    }
    if (!targetSection || carried.added) {
      await saveContent(ctx, target, updated);
    }
    ctx.body = {
      data: {
        existing: !!existing,
        date: today,
        url: target.path,
        added: carried.added,
      },
    };
  }
);

export default router;
