import fs from 'node:fs';
import path from 'node:path';
import { deflateSync } from 'node:zlib';
import { Session, root, settings } from './sso_test_client.mjs';
import { outlineApi } from './prepare_daily_report_demo.mjs';

// One caption-free blank image can be replaced with a screenshot while the
// separate caption paragraphs remain in the manual.
function blankPng(width = 960, height = 180) {
  const crcTable = Array.from({ length: 256 }, (_, n) => {
    let c = n;
    for (let i = 0; i < 8; i++) c = (c & 1) ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    return c >>> 0;
  });
  const chunk = (name, bytes) => {
    const type = Buffer.from(name);
    const input = Buffer.concat([type, bytes]);
    let crc = 0xffffffff;
    for (const byte of input) crc = crcTable[(crc ^ byte) & 255] ^ (crc >>> 8);
    const size = Buffer.alloc(4); size.writeUInt32BE(bytes.length);
    const check = Buffer.alloc(4); check.writeUInt32BE((crc ^ 0xffffffff) >>> 0);
    return Buffer.concat([size, input, check]);
  };
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width); header.writeUInt32BE(height, 4);
  header[8] = 8; header[9] = 6;
  const stride = width * 4 + 1;
  const pixels = Buffer.alloc(stride * height);
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const index = y * stride + 1 + x * 4;
    const border = x < 2 || x >= width - 2 || y < 2 || y >= height - 2;
    pixels[index] = border ? 229 : 255;
    pixels[index + 1] = border ? 231 : 255;
    pixels[index + 2] = border ? 235 : 255;
    pixels[index + 3] = 255;
  }
  return Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]), chunk('IHDR', header), chunk('IDAT', deflateSync(pixels)), chunk('IEND', Buffer.alloc(0))]);
}

const session = new Session();
await session.login(settings.urls.outline + '/auth/oidc');
const demo = JSON.parse(fs.readFileSync(path.join(root, '.local/daily-report-demo.json'), 'utf8'));
const native = JSON.parse(fs.readFileSync(path.join(root, '.local/daily-report-native-demo.json'), 'utf8'));
const current = await outlineApi(session, 'documents.info', { id: demo.guide.id });
const backupPath = path.join(root, '.local/daily-report-guide-before-manual-20261027.json');
if (!fs.existsSync(backupPath)) fs.writeFileSync(backupPath, JSON.stringify(current, null, 2));
const backup = JSON.parse(fs.readFileSync(backupPath, 'utf8'));
if (current.title !== '업무보고 기능 사용 안내' || current.collectionId !== demo.collectionId || current.text !== backup.text) throw new Error('Guide changed since the saved review; read the current page before replacing it.');

const blank = blankPng();
fs.mkdirSync(path.join(root, '.ui-review'), { recursive: true });
fs.writeFileSync(path.join(root, '.ui-review/daily-report-screenshot-placeholder.png'), blank);
const upload = await outlineApi(session, 'attachments.create', { name: 'daily-report-screenshot-placeholder.png', documentId: current.id, contentType: 'image/png', size: blank.length, preset: 'documentAttachment' });
const uploadUrl = new URL(upload.uploadUrl, settings.urls.outline);
if (upload.mode !== 'post' || uploadUrl.origin !== new URL(settings.urls.outline).origin) throw new Error('Unexpected upload destination');
const form = new FormData();
for (const [key, value] of Object.entries(upload.form)) form.append(key, String(value));
form.append('file', new Blob([blank], { type: 'image/png' }), 'daily-report-screenshot-placeholder.png');
const uploaded = await session.fetch(uploadUrl.href, { method: 'POST', headers: { Origin: settings.urls.outline }, body: form });
if (!uploaded.ok) throw new Error('Placeholder upload failed: ' + uploaded.status);
const picture = '![](' + upload.attachment.url + ' " =960x180")';

const manual = `2026.10.27 업데이트 기준

긴 업무보고를 날짜별로 정리하고, 미완료 업무를 오늘 보고로 이어 쓸 때 사용합니다.

## 1. 처음 사용할 때

1. 문서 상단 **⋯ → 업무보고 도구**를 켭니다. 문서 편집 권한이 필요합니다.
2. 본문에 날짜를 **제목 서식**으로 넣고, 그 아래에 작업자 표를 작성합니다. 예: **2026.10.27. 화**
3. 표는 **작업자 / 계속 되는 작업 / 당일 완료 예정 작업 / 참고** 열로 구성하면 됩니다. 기존 보고서를 복사해 사용해도 됩니다.

새 문서는 업무보고 도구가 꺼져 있으므로 먼저 켜 주세요.

${picture}

*그림 1. 문서 상단 ⋯ 메뉴의 ‘업무보고 도구’ 토글*

## 2. 매일 사용하는 기능

| 하고 싶은 일 | 사용 방법 |
| --- | --- |
| 날짜별로 접고 펼치기 | 날짜 앞의 화살표를 누릅니다. 화살표가 없으면 날짜 옆 ⋯ → **토글 제목으로 묶기**를 선택합니다. |
| 오늘 보고 만들기 | 날짜 옆 ⋯ → **오늘 보고 추가**. 가져올 미완료 업무를 고르거나, 선택 없이 빈 양식으로 만듭니다. |
| 미완료 업무 더 가져오기 | 날짜 옆 ⋯ → **미완료 업무 이월**. 이전 보고와 항목을 고른 뒤 이월합니다. |
| 특정 작업자만 보기 | 표 위 **작업자**에서 이름을 선택합니다. **전체**를 선택하면 모든 행이 다시 보입니다. |
| 지난 보고를 따로 보관하기 | 날짜 옆 ⋯ → **하위 문서로 이동**. 날짜별 내용이 하위 문서로 옮겨지고, 원래 자리에는 링크가 남습니다. |
| 날짜별 보고 지우기 | 날짜 옆 ⋯ → **이 날짜 보고 삭제**. 해당 날짜의 제목·표·본문을 함께 지웁니다. 실수했다면 편집기에서 바로 **Ctrl+Z**로 되돌립니다. |

- 오늘 보고는 **이전 날짜의 보고 양식**으로 만듭니다. 오늘 보고가 이미 있으면 기존 보고를 엽니다.
- 이월은 **미완료 체크 항목**만 대상으로 합니다. 완료 항목·참고 의견은 제외하고, 같은 작업자의 동일 항목은 중복해서 넣지 않습니다.
- 작업자 필터는 화면만 바꿉니다. 원본 내용은 그대로 유지됩니다.

${picture}

*그림 2. 날짜 옆 ⋯ 메뉴와 표 위 작업자 필터*

## 3. 전체 켜기·끄기 — 관리자 전용

**Outline 관리자만** [설정 → 워크스페이스 → 세부 정보](/settings/details)의 **업무보고 도구 사용**을 켜고 끌 수 있습니다.

전체 설정을 끄면 문서별로 켜 두었어도 업무보고 도구가 표시되지 않습니다. 기존 보고서는 삭제되지 않으며, 다시 켜면 문서별 설정대로 사용할 수 있습니다.

도구가 보이지 않으면 문서의 업무보고 도구가 켜져 있는지 확인하고, 전체 설정은 관리자에게 확인해 주세요.

${picture}

*그림 3. 관리자 설정의 ‘업무보고 도구 사용’ 스위치*

---

[업무보고 예시로 연습하기](${native.main.url})
`;

fs.writeFileSync(path.join(root, 'reports/daily-report-user-manual-20261027.txt'), manual);
const updated = await outlineApi(session, 'documents.update', { id: current.id, text: manual, lastRevision: current.revision });
const record = { at: new Date().toISOString(), id: current.id, title: updated.title, url: settings.urls.outline + updated.url, attachmentId: upload.attachment.id, screenshotSlots: 3, characterCount: manual.length };
fs.writeFileSync(path.join(root, 'reports/daily-report-user-manual-update.json'), JSON.stringify(record, null, 2));
console.log(JSON.stringify(record, null, 2));
