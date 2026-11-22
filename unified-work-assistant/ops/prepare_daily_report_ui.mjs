import fs from 'node:fs';
import path from 'node:path';
import { Session, root, settings } from './sso_test_client.mjs';
import { outlineApi, demoFile, sampleText } from './prepare_daily_report_demo.mjs';

const session = new Session();
await session.login(settings.urls.outline + '/auth/oidc');
const demo = JSON.parse(fs.readFileSync(demoFile, 'utf8'));
const recordPath = path.join(root, 'reports/daily-reports-ui-fixture.json');
if (process.argv.includes('--cleanup')) {
  const fixture = JSON.parse(fs.readFileSync(recordPath, 'utf8'));
  const current = await outlineApi(session, 'documents.info', { id: fixture.id });
  if (!current.title.startsWith('[검증] 업무보고 화면') || current.collectionId !== demo.collectionId) { throw new Error('Unexpected fixture'); }
  const snapshot = await outlineApi(session, 'dailyReports.info', { id: current.id });
  for (const id of new Set(snapshot.days.map((day) => day.sourceDocumentId).filter((id) => id !== current.id))) {
    const child = await outlineApi(session, 'documents.info', { id });
    if (child.parentDocumentId !== current.id || child.collectionId !== demo.collectionId) { throw new Error('Unexpected child fixture'); }
    await outlineApi(session, 'documents.delete', { id });
  }
  await outlineApi(session, 'documents.delete', { id: current.id });
  console.log('UI fixture moved to recoverable trash.');
} else {
  const previousOnly = sampleText.slice(0, sampleText.indexOf('# 2026.10.26. 월')) + sampleText.slice(sampleText.indexOf('# 2026.10.23. 금'));
  const fixture = await outlineApi(session, 'documents.create', { collectionId: demo.collectionId, title: '[검증] 업무보고 화면 ' + Date.now(), text: previousOnly, publish: true, fullWidth: true, preferences: { dailyReportTools: 'auto' } });
  const record = { id: fixture.id, url: settings.urls.outline + fixture.url };
  fs.writeFileSync(recordPath, JSON.stringify(record, null, 2));
  console.log(JSON.stringify(record));
}
