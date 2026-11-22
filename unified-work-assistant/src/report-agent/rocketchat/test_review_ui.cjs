// Read-only UI check against the synthetic report produced by smoke_review.py.
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const local = path.join(__dirname, '.local');
let browser;

(async () => {
  const credentials = JSON.parse(fs.readFileSync(path.join(local, 'credentials.json'), 'utf8'));
  const result = JSON.parse(fs.readFileSync(path.join(local, 'review-smoke-results.json'), 'utf8'));
  browser = await chromium.launch({headless: true, ...(process.env.PLAYWRIGHT_BROWSER ? {channel: process.env.PLAYWRIGHT_BROWSER} : {})});
  const page = await browser.newPage({viewport: {width: 1360, height: 980}});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(result.review_url);
  await page.locator('#username').fill(credentials.employee.username);
  await page.locator('#password').fill(credentials.employee.password);
  const loaded = page.waitForResponse(response => response.url().endsWith('/api/review/drafts/' + result.draft_id) && response.ok());
  await page.locator('#login button').click();
  await page.locator('#editor').waitFor({state: 'visible', timeout: 30000});
  if (!(await page.locator('#state').innerText()).includes('저장 완료')) throw new Error('Confirmed state not rendered');
  const persisted = await (await loaded).json();
  for (let i=0; i<persisted.items.length; i++) {
    if (await page.locator('[data-key=progress]').nth(i).inputValue() !== String(persisted.items[i].progress ?? '')) throw new Error('Persisted progress differs from displayed progress');
  }
  await page.locator('[data-key=progress]').first().fill('');
  if (await page.locator('[data-key=progress]').first().inputValue() !== '') throw new Error('Empty progress was coerced to zero');
  await page.locator('[data-key=task]').first().fill('UI 검증 · 수정 미리보기 (저장하지 않음)');
  if (!(await page.locator('#preview').innerText()).includes('UI 검증 · 수정 미리보기')) throw new Error('Preview not updated');
  // Reload the persisted values without saving UI-only changes.
  await page.reload();
  await page.locator('#password').fill(credentials.employee.password);
  await page.locator('#login button').click();
  await page.locator('#editor').waitFor({state: 'visible', timeout: 30000});
  await page.locator('[data-period="이번 주"]').click();
  await page.locator('#search-info').filter({hasText: '본인 확정 업무'}).waitFor();
  await page.locator('#search-input').fill('직원 수정');
  await page.locator('#search-form button').click();
  await page.locator('#search-results .search-result').first().waitFor();
  if (!(await page.locator('#search-results').innerText()).includes('직원 수정')) throw new Error('Keyword search failed');
  await page.screenshot({path: path.join(local, 'review-desktop.png'), fullPage: true});
  await page.setViewportSize({width: 390, height: 844});
  await page.screenshot({path: path.join(local, 'review-mobile.png'), fullPage: true});
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  if (overflow) throw new Error('Mobile horizontal overflow');
  if (errors.length) throw new Error(errors.join('\n'));
  console.log('UI PASS: login, author draft, persisted confirmed state, null progress, live edit preview, session reset, mobile width; no report modified.');
  await browser.close();
})().catch(async error => { console.error(error.message); if(browser)await browser.close(); process.exitCode = 1; });
