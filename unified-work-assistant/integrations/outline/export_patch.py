"""Export only integration changes against the verified official source archive."""
import difflib, hashlib, json, tarfile
from pathlib import Path
root=Path(__file__).resolve().parent
commit='65be53c3eb093a535ce260eb2f2da897bb07a29e'
source=root/('outline-'+commit)
files=['app/actions/definitions/collections.tsx','app/components/Collection/CollectionForm.tsx',
       'app/components/Collection/CollectionNew.tsx','app/components/Collection/WorkhubProject.tsx',
       'app/components/Collection/WorkhubProject.test.tsx',
       'app/components/Collection/CollectionNew.test.tsx',
       'server/utils/workhubProjectGroup.ts','server/routes/api/workhubGroup.test.ts',
       'app/components/WorkhubButton.tsx','app/components/WorkhubNotice.tsx',
       'server/models/GroupMembership.ts','server/migrations/20261020000000-workhub-group-previous-permission.js',
       'app/hooks/useCollectionMenuAction.tsx','app/routes/authenticated.tsx','server/env.ts',
       'server/routes/api/index.ts','server/routes/api/workhub.ts','server/routes/api/workhub.test.ts',
       'server/routes/api/collections/collections.ts','server/routes/api/collections/schema.ts',
       'server/routes/api/documents/documents.ts',
       'server/routes/api/workhubSearch.ts','app/scenes/Search/Search.tsx',
       'app/scenes/Search/components/KnowledgeSearch.tsx',
       'app/components/Sidebar/App.tsx','app/components/Sidebar/components/WorkhubAnalyticsLink.tsx',
       'app/stores/RootStore.ts','app/stores/WorkhubAnalyticsStore.ts','app/stores/WorkhubAnalyticsStore.test.ts',
       'app/scenes/WorkhubAnalytics/index.tsx','app/scenes/WorkhubAnalytics/types.ts',
       'app/scenes/WorkhubAnalytics/calendar.ts','app/scenes/WorkhubAnalytics/calendar.test.ts',
       'server/routes/api/workhubAnalytics.ts','server/routes/api/workhubTasks.ts',
       'app/scenes/Document/components/Header.tsx',
       'app/components/WorkhubTaskCreate/index.tsx','app/components/WorkhubTaskCreate/dates.ts',
       'app/components/WorkhubTaskCreate/dates.test.ts',
       'app/components/WorkhubTaskCreate/SidebarTaskCreate.tsx',
       'app/components/Sidebar/components/DocumentLink.tsx',
       'app/components/Sidebar/components/DocumentRow.tsx',
       'app/components/Sidebar/components/DragPlaceholder.tsx',
       'app/scenes/Document/components/Document.tsx','app/scenes/Document/components/Editor.tsx',
       'app/components/WorkhubKanban/index.tsx','app/components/WorkhubKanban/dropTarget.ts',
       'app/components/WorkhubKanban/dropTarget.test.ts','app/stores/WorkhubKanbanStore.ts',
       'app/stores/WorkhubKanbanStore.test.ts','server/routes/api/workhubKanban.ts',
       'app/stores/WorkhubTaskEditStore.ts','app/stores/WorkhubTaskEditStore.test.ts',
       'app/components/WorkhubKanban/TaskList.tsx','app/components/WorkhubKanban/TaskList.test.tsx',
       'vitest.config.ts',
       'shared/helpers/AuthenticationHelper.ts','shared/helpers/AuthenticationHelper.test.ts',
       'app/components/DocumentContext.tsx','app/editor/menus/block.tsx',
       'app/editor/components/BlockMenu.tsx','app/editor/TableOfContents.test.tsx',
       'shared/editor/nodes/TableOfContents.ts','shared/editor/nodes/TableOfContents.test.ts',
       'shared/editor/lib/tableOfContents.ts','shared/editor/nodes/index.ts',
       'shared/editor/nodes/Heading.ts','shared/editor/lib/markdown/serializer.ts',
       'shared/editor/components/Styles.ts','shared/utils/ProsemirrorHelper.ts',
       'server/models/helpers/ProsemirrorHelper.tsx','server/models/helpers/DocumentHelper.tsx',
       'server/editor/TableOfContents.test.ts']
files += ['app/editor/index.tsx', 'app/editor/extensions/SelectionToolbar.tsx', 'app/editor/components/SelectionToolbar.tsx', 'app/editor/components/ToolbarButton.tsx', 'app/editor/components/ToolbarMenu.tsx', 'app/components/WorkhubTaskCreate/index.test.tsx', 'app/components/WorkhubTaskCreate/SelectionTaskCreate.tsx', 'shared/editor/lib/taskSelection.ts', 'shared/editor/lib/taskSelection.test.ts', 'server/routes/api/workhubTasks.test.ts']
files += ['app/components/Editor.tsx', 'app/components/WorkhubTaskCreate/SelectionTaskContext.ts', 'app/editor/SelectionTask.test.tsx']
files += ['shared/utils/dailyReport.ts', 'shared/utils/dailyReport.test.ts',
          'server/routes/api/dailyReports.ts', 'server/routes/api/dailyReports.test.ts',
          'app/stores/DailyReportStore.ts', 'app/components/DailyReports.tsx']
files += ['shared/editor/lib/dailyReport.ts', 'app/editor/extensions/DailyReport.ts',
          'app/editor/extensions/index.ts', 'app/editor/DailyReport.test.tsx',
          'app/components/DailyReportActions.tsx']
files += ['shared/types.ts', 'shared/constants.ts', 'server/routes/api/teams/schema.ts',
          'server/routes/api/documents/schema.ts', 'server/commands/documentCreator.ts',
          'app/components/DailyReportSettings.tsx', 'app/scenes/Settings/Details.tsx',
          'app/menus/DocumentMenu.tsx']
files += ['app/scenes/Settings/Profile.tsx', 'shared/utils/authentik.ts', 'shared/utils/authentik.test.ts']
patch=[]
with tarfile.open(root/'upstream.tar.gz') as archive:
    for name in files:
        try:before=archive.extractfile('outline-'+commit+'/'+name).read().decode().splitlines(True)
        except KeyError:before=[]
        after=(source/name).read_text(encoding='utf-8').splitlines(True)
        patch.extend(difflib.unified_diff(before,after,fromfile='a/'+name if before else '/dev/null',tofile='b/'+name))
(root/'patches').mkdir(exist_ok=True)
(root/'patches/0001-workhub-project-management.patch').write_text(''.join(patch),encoding='utf-8',newline='\n')
(root/'upstream.lock.json').write_text(json.dumps({'version':'1.10.0','commit':commit,
    'archiveUrl':'https://github.com/outline/outline/archive/'+commit+'.tar.gz',
    'archiveSha256':hashlib.sha256((root/'upstream.tar.gz').read_bytes()).hexdigest(),
    'baselineImage':'unified-work-assistant/outline:migration-baseline',
    'baselineDigest':'sha256:cc9f1f05fd7cd316745b5fc9cfe01e681b1b4cf97705d1d812a5c778d7986cfd',
    'patchedFiles':files},indent=2)+'\n',encoding='utf-8')
print('Exported',len(files),'source files to reproducible patch.')
