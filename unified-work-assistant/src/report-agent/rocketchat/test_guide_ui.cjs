// Read-only mechanism map/manual check. Clipboard and print are stubbed.
const path=require("node:path");
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||"playwright");
let browser;
(async()=>{
  browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_BROWSER||"msedge"});
  const page=await browser.newPage({viewport:{width:1440,height:1100}});
  const errors=[],writes=[];
  page.on("pageerror",error=>errors.push(error.message));
  page.on("request",request=>{if(request.method()!=="GET")writes.push(request.url());});
  await page.addInitScript(()=>{
    Object.defineProperty(navigator,"clipboard",{value:{writeText:async text=>{window.testCopiedText=text;}}});
    window.print=()=>{window.testPrintCalled=true;};
  });
  const response=await page.goto("http://127.0.0.1:8003/assets/guide.html");
  if(!response.ok())throw new Error("Guide unavailable");
  if(await page.locator(".manual-panel:visible").count()!==1)throw new Error("Show only one purpose at a time");
  if(await page.locator("#map:visible").count()!==1)throw new Error("Mechanism map should be the entry point");
  if(await page.locator(".flow-row").count()!==2)throw new Error("New and historical report flows must be distinct");
  const visibleMap=await page.locator("#map").innerText();
  for(const text of ["초안 DB","최종 보고","LLM·RAG","내 확인 필요"])if(!visibleMap.includes(text))throw new Error("Missing boundary: "+text);
  await page.screenshot({path:path.join(__dirname,".local","manual-map-desktop.png"),fullPage:true});
  await page.locator('.mechanism').screenshot({path:path.join(__dirname,".local","mechanism-map.png")});
  await page.locator('nav a[href="#new-report"]').click();
  await page.locator("#new-report").waitFor({state:"visible"});
  await page.locator("[data-copy]").click();
  await page.locator("#copy-status").filter({hasText:"복사했습니다"}).waitFor();
  if(!(await page.evaluate(()=>window.testCopiedText)).startsWith("보고 "))throw new Error("Wrong example copied");
  await page.getByText("초안이 여러 개 있나요?",{exact:true}).click();
  if(!(await page.locator("#new-report details[open]").innerText()).includes("이대로 보고"))throw new Error("Missing one-click confirmation");
  await page.locator('nav a[href="#import-help"]').click();
  if(!(await page.locator("#import-help").innerText()).includes("채팅의 ‘확정’으로 저장되지 않습니다"))throw new Error("Historical import needs web confirmation");
  await page.locator('nav a[href="#search-help"]').click();
  if(!(await page.locator("#search-help").innerText()).includes("최신 상태를 자동 판단하지는"))throw new Error("Historical incomplete query limit omitted");
  await page.locator('nav a[href="#features"]').click();
  if(!(await page.locator("#features").innerText()).includes("메뉴 미구현"))throw new Error("Placeholder features not distinguished");
  await page.screenshot({path:path.join(__dirname,".local","manual-features-desktop.png"),fullPage:true});
  await page.locator("#print-guide").click();
  if(!(await page.evaluate(()=>window.testPrintCalled)))throw new Error("Print action failed");
  await page.evaluate(()=>window.dispatchEvent(new Event("beforeprint")));
  await page.emulateMedia({media:"print"});
  if(await page.locator(".manual-panel:visible").count()!==6)throw new Error("Printing omits hidden purposes");
  await page.emulateMedia({media:"screen"});
  await page.evaluate(()=>window.dispatchEvent(new Event("afterprint")));
  for(const width of [390,320]){
    await page.setViewportSize({width,height:844});
    for(const id of ["map","new-report","import-help","search-help","features","help"]){
      await page.locator('nav a[href="#'+id+'"]').click();
      if(await page.locator(".manual-panel:visible").count()!==1)throw new Error("Multiple purposes visible");
      if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw new Error("Overflow: "+width+" / "+id);
    }
  }
  await page.setViewportSize({width:390,height:844});
  await page.locator('nav a[href="#map"]').click();
  await page.screenshot({path:path.join(__dirname,".local","manual-map-mobile.png"),fullPage:true});
  await page.goto("http://127.0.0.1:8003/assets/guide.html#edit");
  if(await page.locator("#search-help:visible").count()!==1)throw new Error("Old manual anchors must remain usable");
  if(errors.length||writes.length)throw new Error("Unexpected error/write: "+errors.join(";")+writes.join(";"));
  console.log("PASS: actual flow map, 6 purpose panels, copy, original anchors, limitations, all-section print, 320/390px layouts; no API mutations or real clipboard/print.");
  await browser.close();
})().catch(async error=>{console.error(error.message);if(browser)await browser.close();process.exitCode=1;});
