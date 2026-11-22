import {
  CalendarIcon,
  TodoListIcon,
  DocumentIcon,
  ShapesIcon,
} from "outline-icons";
import { cloneDeep } from "es-toolkit/compat";
import { observer } from "mobx-react";
import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import Icon from "@shared/components/Icon";
import type { MenuItem } from "@shared/editor/types";
import { ProsemirrorHelper } from "@shared/utils/ProsemirrorHelper";
import { TextHelper } from "@shared/utils/TextHelper";
import { isDailyReport } from "@shared/utils/dailyReport";
import useCurrentUser from "~/hooks/useCurrentUser";
import useStores from "~/hooks/useStores";
import getMenuItems from "../menus/block";
import { useEditor } from "./EditorContext";
import type { Props as SuggestionsMenuProps } from "./SuggestionsMenu";
import SuggestionsMenu from "./SuggestionsMenu";
import SuggestionsMenuItem from "./SuggestionsMenuItem";

/**
 * Hook that returns a template menu item with children for inserting template
 * content into the editor, or undefined if no templates are available.
 */
function useTemplateMenuItem(): MenuItem | undefined {
  const { t } = useTranslation();
  const user = useCurrentUser({ rejectOnEmpty: false });
  const { documents, templates: templatesStore } = useStores();
  const editor = useEditor();
  const documentId = editor.props.id;
  const document = documentId ? documents.get(documentId) : undefined;
  const collectionId = document?.collectionId;

  return useMemo(() => {
    if (!user) {
      return undefined;
    }

    const allTemplates = templatesStore.published.filter(
      (template) => !!template.data
    );
    const hasTemplates = allTemplates.some(
      (template) =>
        template.isWorkspaceTemplate || template.collectionId === collectionId
    );

    if (!hasTemplates) {
      return undefined;
    }

    const toMenuItem = (template: (typeof allTemplates)[0]): MenuItem => ({
      name: "noop",
      title: TextHelper.replaceTemplateVariables(
        template.titleWithDefault,
        user
      ),
      icon: template.icon ? (
        <Icon
          value={template.icon}
          initial={template.initial}
          color={template.color ?? undefined}
        />
      ) : (
        <DocumentIcon />
      ),
      keywords: template.titleWithDefault,
      onClick: () => {
        const data = cloneDeep(template.data);
        ProsemirrorHelper.replaceTemplateVariables(data, user);
        editor.insertContent(data);
      },
    });

    const children = (): MenuItem[] => {
      const collectionTemplates = allTemplates.filter(
        (template) =>
          !template.isWorkspaceTemplate &&
          template.collectionId === collectionId
      );
      const workspaceTemplates = allTemplates.filter(
        (tmpl) => tmpl.isWorkspaceTemplate
      );

      const items: MenuItem[] = collectionTemplates.map(toMenuItem);

      if (collectionTemplates.length && workspaceTemplates.length) {
        items.push({ name: "separator" });
      }

      if (workspaceTemplates.length) {
        for (const template of workspaceTemplates) {
          items.push(toMenuItem(template));
        }
      }

      return items;
    };

    return {
      name: "noop",
      title: t("Templates"),
      icon: <ShapesIcon />,
      keywords: "template",
      children,
    } satisfies MenuItem;
  }, [user, templatesStore.published, collectionId, editor, t]);
}

type Props = Omit<SuggestionsMenuProps, "renderMenuItem" | "items"> &
  Required<Pick<SuggestionsMenuProps, "embeds">>;

function BlockMenu(props: Props) {
  const { t } = useTranslation();
  const editor = useEditor();
  const { elementRef, view } = editor;
  const hasReports =
    !!editor.props.dailyReportEnabled &&
    !!editor.props.onDailyReportAction &&
    isDailyReport(view.state.doc.toJSON());
  const templateMenuItem = useTemplateMenuItem();
  const canInsertContents =
    view.state.selection.empty &&
    view.state.selection.$from.depth === 1 &&
    view.state.selection.$from.parent.type.name === "paragraph";

  const items = useMemo(() => {
    const baseItems = getMenuItems(t, elementRef).filter(
      (item) => item.name !== "table_of_contents" || canInsertContents
    );

    const reports: MenuItem[] = hasReports
      ? [
          {
            name: "noop",
            title: "오늘 보고 추가",
            icon: <CalendarIcon />,
            keywords: "보고 오늘보고 일일 업무보고 today daily report",
            onClick: () => editor.props.onDailyReportAction?.("create"),
          },
          {
            name: "noop",
            title: "미완료 업무 가져오기",
            icon: <TodoListIcon />,
            keywords: "보고 이월 미완료 업무 report carry unfinished",
            onClick: () => editor.props.onDailyReportAction?.("carry"),
          },
          { name: "separator" },
        ]
      : [];
    return [
      ...reports,
      ...baseItems,
      ...(templateMenuItem ? [{ name: "separator" }, templateMenuItem] : []),
    ];
  }, [t, elementRef, templateMenuItem, canInsertContents, hasReports, editor]);

  const renderMenuItem = useCallback(
    (item, _index, options) => (
      <SuggestionsMenuItem
        {...options}
        icon={item.icon}
        title={item.title}
        shortcut={item.shortcut}
        disclosure={options.disclosure}
      />
    ),
    []
  );

  return (
    <SuggestionsMenu
      {...props}
      filterable
      trigger="/"
      renderMenuItem={renderMenuItem}
      items={items}
    />
  );
}

export default observer(BlockMenu);
