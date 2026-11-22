// Read-only after login: verifies the simplified four-part review UI.
const fs=require('node:fs');const path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const local=path.join(__dirname,'.local');let browser;
(async()=>{
  const creds=JSON.parse(fs.readFileSync(path.join(local,'credentials.json'),'utf8'));
  const result=JSON.parse(fs.readFileSync(path.join(local,'team-smoke-results.json'),'utf8'));
  browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_BROWSER||'msedge'});
  const page=await browser.newPage({viewport:{width:1360,height:950}});const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/api/review/**',async route=>{const req=route.request();if(req.method()!=='GET'&&!req.url().endsWith('/login'))throw new Error('Unexpected UI write');await route.continue();});
  await page.goto('http://127.0.0.1:8003/#'+result.draft_id);
  await page.locator('#password').fill(creds.employee.password);await page.locator('#login button').click();
  try{await page.locator('#editor').waitFor({state:'visible',timeout:15000});}catch(e){console.error('Notice:',await page.locator('#notice').innerText(),'JS:',errors);throw e;}
  for(const title of ['수정할 보고 선택','이 내용으로 저장됩니다','프로젝트·내용 수정','내용 저장 또는 보내기'])await page.getByRole('heading',{name:title,exact:true}).waitFor();
  for(const removed of ['지난 보고 찾기','이전 보고 가져오기','원문·AI 근거 확인','변경 이력 보기'])if(await page.getByText(removed,{exact:true}).count())throw new Error('Old explanation remains: '+removed);
  const buttons=page.locator('#draft-list button');const times=await buttons.evaluateAll(rows=>rows.map(row=>row.dataset.time));if(JSON.stringify(times)!==JSON.stringify([...times].sort().reverse()))throw new Error('Reports are not ordered newest to oldest');
  const selected=page.locator('#draft-list button.selected');if(await selected.count()!==1||await selected.getAttribute('data-draft-id')!==result.draft_id)throw new Error('Current report is not selected');
  if(!await selected.locator('.selected-label').isVisible())throw new Error('Current report label is not visible');
  if(await buttons.count()>1){const colors=await buttons.evaluateAll(rows=>rows.slice(0,2).map(row=>getComputedStyle(row).backgroundColor));const selectedColor=await selected.evaluate(row=>getComputedStyle(row).backgroundColor);if(colors.every(color=>color===selectedColor))throw new Error('Current report background is not distinct');}
  if(await page.locator('[data-key=project]').count()!==2)throw new Error('Project choices missing/duplicated');
  if(!(await page.locator('#preview').innerText()).includes('[업무목록]'))throw new Error('Save preview missing');
  if(await page.locator('#publication-confirm').isVisible())throw new Error('Already published version offered again');
  await page.screenshot({path:path.join(local,'team-publication-desktop.png'),fullPage:true});
  await page.locator('[data-key=task]').first().fill('저장하지 않는 UI 미리보기');
  if(!(await page.locator('#publication-status').innerText()).includes('먼저 저장'))throw new Error('Dirty edit state unclear');
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(local,'team-publication-mobile.png'),fullPage:true});
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw new Error('Mobile overflow');
  if(errors.length)throw new Error(errors.join('\n'));
  console.log('PASS: four-part UI, report preview, project fields, save/send state, removed explanations, mobile; no report written');
  await browser.close();
})().catch(async e=>{console.error(e.message);if(browser)await browser.close();process.exitCode=1;});
