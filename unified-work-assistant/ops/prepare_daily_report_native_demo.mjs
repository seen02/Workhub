import fs from 'node:fs';
import path from 'node:path';
import { Session, root, settings } from './sso_test_client.mjs';
import { outlineApi, demoFile, sampleText } from './prepare_daily_report_demo.mjs';

export const nativeDemoFile = path.join(root, '.local/daily-report-native-demo.json');
/** Uses Outline's existing native toggle Markdown fences around date sections. */
export function nativeReportText(text) {
  const parts = text.split(/(?=^# 20\d{2}\.\d{2}\.\d{2}\.)/m);
  return parts.map((part) => /^# 20\d{2}\./.test(part) ? '++++++++++\n' + part.trim() + '\n++++++++++\n\n' : part).join('');
}

/** Creates a new example, preserving every previous demo and all user edits. */
export async function prepareNativeDemo() {
  const session = new Session();
  await session.login(settings.urls.outline + '/auth/oidc');
  if (fs.existsSync(nativeDemoFile)) {
    const saved = JSON.parse(fs.readFileSync(nativeDemoFile, 'utf8'));
    await outlineApi(session, 'documents.info', { id: saved.main.id });
    console.log(JSON.stringify({ preserved: true, ...saved }, null, 2));
    return saved;
  }
  const previous = JSON.parse(fs.readFileSync(demoFile, 'utf8'));
  const collectionId = previous.collectionId;
  const priorText = sampleText.slice(0, sampleText.indexOf('# 2026.10.26. 월')) + sampleText.slice(sampleText.indexOf('# 2026.10.23. 금'));
  const main = await outlineApi(session, 'documents.create', { collectionId, title: '[체험] 일일 업무보고 · 편집기 통합', text: nativeReportText(sampleText), publish: true, fullWidth: true, preferences: { dailyReportTools: 'auto' } });
  const create = await outlineApi(session, 'documents.create', { collectionId, title: '[체험] 오늘 보고 추가 · 편집기 통합', text: '> 날짜 제목 옆 ⋯ → 오늘 보고 추가. 미완료 업무를 선택하거나 빈 양식으로 만드세요. 기존 토글과 편집기를 그대로 사용합니다.\n\n' + nativeReportText(priorText), publish: true, fullWidth: true, preferences: { dailyReportTools: 'auto' } });
  const plain = await outlineApi(session, 'documents.create', { collectionId, title: '[체험] 기존 Markdown 문서에 적용', text: '> 기존 제목과 표도 그대로 인식합니다. 날짜 제목 옆 ⋯ → 토글 제목으로 묶기를 눌러 보세요.\n\n' + sampleText, publish: true, fullWidth: true, preferences: { dailyReportTools: 'auto' } });
  const guide = await outlineApi(session, 'documents.create', { collectionId, title: '업무보고 사용 안내 · 편집기 통합', publish: true, text: `# 직접 사용하기\n\n[기존 편집기와 토글로 작성된 업무보고](${main.url})\n\n[오늘 보고 추가와 선택 이월](${create.url})\n\n[기존 Markdown 제목과 표에 적용](${plain.url})\n\n# 사용 방법\n\n1. 날짜 앞의 기존 토글 화살표로 접고 펼칩니다. 본문과 표는 평소처럼 바로 편집합니다.\n2. 날짜 제목 옆 ⋯에서 오늘 보고 추가, 미완료 업무 이월, 하위 문서로 이동을 사용합니다.\n3. 표 위의 작업자 선택은 화면만 필터링합니다. 문서 내용과 Markdown 내보내기에는 전체 작업자가 남습니다.\n4. 빈 문단에서 /보고를 입력해 오늘 보고 추가나 미완료 업무 가져오기를 실행할 수도 있습니다.\n5. 기존 Markdown 문서는 그대로 붙여넣거나 가져와 사용할 수 있습니다. 일반 날짜 제목 옆 ⋯ → 토글 제목으로 묶기를 누르면 다음 날짜 앞까지 기존 토글로 묶습니다.\n6. 오늘 보고는 이전 표의 작업자와 열 구조로 만듭니다. 선택한 미완료 업무만 가져오며, 같은 날짜와 같은 업무의 중복 생성을 막습니다.\n7. 하위 문서로 이동하면 해당 날짜 내용 전체를 자식 문서에 넣고 원래 자리에는 날짜와 문서 링크를 남깁니다.\n\n오늘 날짜는 한국 시간을 사용합니다. 이전에 사용하신 예시는 그대로 두고 새 체험 문서를 만들었습니다.` });
  const record = { createdAt: new Date().toISOString(), collectionId, ...Object.fromEntries(Object.entries({ main, create, plain, guide }).map(([name, doc]) => [name, { id: doc.id, url: settings.urls.outline + doc.url }])) };
  fs.writeFileSync(nativeDemoFile, JSON.stringify(record, null, 2));
  console.log(JSON.stringify(record, null, 2));
  return record;
}
if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(import.meta.filename)) { await prepareNativeDemo(); }
