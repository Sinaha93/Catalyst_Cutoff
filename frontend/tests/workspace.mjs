import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {spawn, spawnSync} from 'node:child_process';
import {mkdtemp, mkdir, rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

async function chooseMaster(panel,role){
 const labels={bom_master:'BOM 버전',price_master:'촉매 단가',route_master:'물류 경로·공장'};
 await panel.getByRole('group',{name:'기준 등록·적용 상태',exact:true}).getByRole('button',{name:labels[role],exact:true}).click();
}
const root = fileURLToPath(new URL('../../', import.meta.url));
const data = await mkdtemp(path.join(os.tmpdir(), '촉매 W1 테스트 '));
const python = process.env.CATALYST_TEST_PYTHON ?? path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
await mkdir(path.join(root, 'test-results'), {recursive:true});
const sourceLabels={erp_receipts:'ERP 촉매 입고',product_stock:'제품 창고 수불',semi_stock:'반제품 창고 수불',umicore_statement:'유미코아 납품 Summary',glovis_receipts:'글로비스 실제 입고',bom_master:'BOM 기준',route_master:'통합 경로 기준',price_master:'촉매 단가',plan_master:'월계획'};
async function chooseSource(sources,role){
  const standard=['bom_master','route_master','price_master','plan_master','price_policy'].includes(role);
  await sources.getByRole('button',{name:role==='plan_master'?'월계획':'이번 달 원본',exact:true}).click();
  await sources.locator('.source-checklist').getByRole('button').filter({has:sources.page().getByText(sourceLabels[role],{exact:true})}).click();
  assert.equal(await sources.getByLabel('선택한 자료',{exact:true}).inputValue(),`${sourceLabels[role]} (XLSX)`);
  assert.equal(await sources.getByRole('combobox',{name:'자료 종류',exact:true}).count(),0);
}
async function registerMaster(page,role,buffer){
 await page.getByRole('button',{name:'기준 관리',exact:true}).click();
 const panel=page.getByRole('region',{name:'프로그램 기준 관리',exact:true});
 await chooseMaster(panel,role);
 await panel.getByLabel('기준 파일',{exact:true}).setInputFiles({name:`${role}.xlsx`,mimeType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',buffer});
 await panel.getByRole('button',{name:'기준 파일 읽기',exact:true}).click();
 await panel.getByText(`${role}.xlsx · 읽기 검산 완료`,{exact:true}).waitFor();
 const cardNames={bom_master:'BOM 버전',price_master:'촉매 단가',route_master:'물류 경로·공장'};
 const card=panel.getByRole('group',{name:'기준 등록·적용 상태'}).getByRole('button',{name:cardNames[role],exact:true});
 await card.getByText('파일 읽기 완료 · 기준 저장 전',{exact:true}).waitFor();
 await panel.getByLabel('기준 변경 사유').fill('합성 기준 최초 등록');
 await panel.getByRole('button',{name:'기준 변경 내용 비교',exact:true}).click();
 await panel.getByRole('button',{name:'새 기준 버전 저장',exact:true}).click();
 await panel.getByText('새 기준 버전을 저장했습니다.',{exact:false}).waitFor();
 await card.getByText('기준 저장됨 · 이번 달 적용 전',{exact:true}).waitFor();
 await panel.getByRole('button',{name:'이번 달 적용 전 차이 보기',exact:true}).click();
 await panel.getByRole('button',{name:'이 버전을 이번 달에 적용',exact:true}).click();
 await panel.getByText('이번 달 계산 기준에 적용했습니다.',{exact:false}).waitFor();
 await card.getByText('✓ 이번 달 사용',{exact:true}).waitFor();
 await page.getByRole('button',{name:'자료 등록',exact:true}).click();
}
let current;
let currentUrl;
async function start() {
  const proc = spawn(python, ['-m','backend.launcher','--data-dir',data,'--no-browser'], {cwd:root, env:{...process.env, PYTHONIOENCODING:'utf-8', PYTHONUTF8:'1'}, windowsHide:true});
  current = proc;
  const url = await new Promise((resolve,reject) => {
    let output = '';
    const timer = setTimeout(() => reject(new Error(`Server timeout: ${output}`)), 25000);
    proc.stdout.on('data', chunk => {output += chunk; const match = output.match(/CATALYST_URL=(http:\/\/127\.0\.0\.1:\d+)/); if (match) {clearTimeout(timer); resolve(match[1])}});
    proc.stderr.on('data', chunk => {output += chunk});
    proc.on('exit', code => {clearTimeout(timer); reject(new Error(`Exited ${code}: ${output}`))});
    proc.on('error', reject);
  });
  currentUrl = url;
  return {proc,url};
}
const browser = await chromium.launch({headless:true,channel:'msedge'});
try {
  let server = await start();
  const page = await browser.newPage({viewport:{width:1920,height:1080}});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  // Session can succeed while the month list fails. Retry must remain visible.
  await page.route('**/api/months', route => route.request().method()==='GET'
    ? route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({message:'목록 조회 실패 테스트'})}) : route.continue());
  await page.goto(server.url);
  await page.getByText('월 작업 목록을 읽지 못했습니다').waitFor();
  assert.equal(await page.getByText('아직 월 작업이 없습니다').count(),0);
  await page.unroute('**/api/months');
  await page.getByRole('button',{name:'다시 연결',exact:true}).click();
  await page.getByText('아직 월 작업이 없습니다').waitFor();
  await page.locator('#month').fill('2026-09');
  await page.getByRole('button',{name:'월 작업 열기',exact:true}).click();
  await page.locator('#note').waitFor();
  await page.locator('#note').fill('기말적송재고 PDF 대조 예정');
  await page.waitForFunction(() => document.querySelector('[role="status"]')?.textContent === '저장 완료');
  await page.reload();
  await page.waitForFunction(() => document.querySelector('#note')?.value === '기말적송재고 PDF 대조 예정');
  // Reopening an existing month must not create another draft.
  await page.getByRole('button',{name:'월 작업 열기',exact:true}).click();
  await page.waitForFunction(() => document.querySelector('[role="status"]')?.textContent === '저장 완료');
  assert.equal(await page.locator('tbody tr').count(),1);
  await page.screenshot({path:path.join(root,'test-results/workspace-1920.png'),fullPage:true});
  for (const width of [1920,1536,1280,768,360]) {
    await page.setViewportSize({width,height:1080});
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `overflow at ${width}`);
  }
  await page.setViewportSize({width:1920,height:1080});
  // A failed autosave must keep the user's input and allow retry.
  await page.route('**/api/months/2026-09', route => route.request().method() === 'PATCH' ? route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({code:'STORAGE_FAILED',message:'검증용 저장 실패'})}) : route.continue());
  await page.locator('#note').fill('저장 실패 후에도 남을 입력');
  await page.getByRole('alert').waitFor();
  assert.equal(await page.locator('#note').inputValue(),'저장 실패 후에도 남을 입력');
  await page.unroute('**/api/months/2026-09');
  await page.getByRole('button',{name:'지금 저장',exact:true}).click();
  await page.waitForFunction(() => document.querySelector('[role="status"]')?.textContent === '저장 완료');
  // Another tab's update must not be silently overwritten.
  await page.evaluate(async () => {
    const s = await (await fetch('/api/session')).json();
    const d = await (await fetch('/api/months/2026-09')).json();
    await fetch('/api/months/2026-09',{method:'PATCH',headers:{'Content-Type':'application/json','X-Session-Token':s.token},body:JSON.stringify({expected_revision:d.revision,note:'다른 창에서 저장한 내용'})});
  });
  await page.locator('#note').fill('현재 화면에 보존할 메모');
  await page.getByRole('alert').filter({hasText:'다른 화면에서'}).waitFor();
  assert.equal(await page.locator('#note').inputValue(),'현재 화면에 보존할 메모');
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button',{name:'최신 저장본 불러오기',exact:true}).click();
  await page.waitForFunction(() => document.querySelector('#note')?.value === '다른 창에서 저장한 내용');
  const exited = new Promise(resolve => server.proc.once('exit',resolve));
  await page.getByRole('button',{name:'프로그램 종료',exact:true}).click();
  await page.getByRole('heading',{name:'프로그램을 종료했습니다.'}).waitFor();
  await exited;
  server = await start();
  await page.goto(server.url);
  await page.waitForFunction(() => document.querySelector('#note')?.value === '다른 창에서 저장한 내용');
  // Loading another saved copy must disable editing until the response arrives.
  let release;
  const delayed=new Promise(resolve=>{release=resolve});
  await page.route('**/api/months/2026-09',async route=>{await delayed;await route.continue()});
  await page.getByRole('button',{name:'최신 저장본 불러오기',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#note')?.disabled===true);
  assert.equal(await page.locator('#note').inputValue(),'다른 창에서 저장한 내용');
  release();
  await page.waitForFunction(()=>document.querySelector('#note')?.disabled===false);
  await page.unroute('**/api/months/2026-09');
  // Upload a generated, non-business fixture; keep source registration distinct from adoption.
  let releaseOpen;
  const opening=new Promise(resolve=>{releaseOpen=resolve});
  await page.route('**/api/months',async route=>{if(route.request().method()==='POST')await opening;await route.continue()});
  await page.getByRole('button',{name:'월 작업 열기',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#note')?.disabled===true);
  releaseOpen();await page.waitForFunction(()=>document.querySelector('#note')?.disabled===false);
  await page.unroute('**/api/months');
  const generated=spawnSync(python,['-c',"import runpy,sys; sys.stdout.buffer.write(runpy.run_path('tests/test_imports.py')['workbook']())"],{cwd:root,windowsHide:true});
  assert.equal(generated.status,0,generated.stderr?.toString());
  await page.getByRole('button',{name:'자료 등록',exact:true}).click();
  const sources=page.getByRole('region',{name:'원본 자료 등록',exact:true});
  await sources.getByLabel('원본 파일',{exact:true}).setInputFiles({name:'희성 예시.xlsx',mimeType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',buffer:generated.stdout});
  await sources.getByRole('button',{name:'원본 보관·읽기',exact:true}).click();
  await sources.getByText('파일 상태: 읽기 검산 완료',{exact:true}).waitFor();
  await sources.getByText(/원문 3행 · 품번 2종/).waitFor();
  assert.equal(await sources.locator('.evidence-table tbody tr').count(),3);
  await sources.getByRole('button',{name:'원본 보관·읽기',exact:true}).click();
  await sources.getByText('같은 파일이 이미 등록되어 있습니다. 중복 추가하지 않았습니다.').waitFor();
  assert.equal(await sources.locator('table').first().locator('tbody tr').count(),1);
  await sources.getByRole('button',{name:'이번 달 원본으로 사용',exact:true}).click();
  await sources.getByText('파일 상태: 이번 달 사용',{exact:true}).waitFor();
  await page.reload();
  await sources.getByText('이번 달 사용',{exact:true}).waitFor();
  await sources.getByRole('button',{name:'내용 보기',exact:true}).click();
  await sources.getByText(/원문 3행 · 품번 2종/).waitFor();
  // ERP exports lack the query month. Require confirmation on each new file.
  for (const [role, factory, args, count] of [['erp_receipts','receipt_book','',4],['product_stock','stock_book','',1],['semi_stock','stock_book','True',1]]) {
    const fixture=spawnSync(python,['-c',`import runpy,sys; m=runpy.run_path('tests/test_erp.py'); sys.stdout.buffer.write(m['content'](m['${factory}'](${args})))`],{cwd:root,windowsHide:true});
    assert.equal(fixture.status,0,fixture.stderr?.toString());
    await chooseSource(sources,role);
    assert.equal(await sources.getByLabel('자료 기준월',{exact:true}).inputValue(),'2026-09');
    await sources.getByLabel('원본 파일',{exact:true}).setInputFiles({name:`${role}_20261008.xlsx`,mimeType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',buffer:fixture.stdout});
    assert.equal(await sources.getByRole('button',{name:'원본 보관·읽기',exact:true}).isDisabled(),true);
    await sources.getByRole('checkbox',{name:/전체 기간/}).check();
    await sources.getByRole('button',{name:'원본 보관·읽기',exact:true}).click();
    await sources.getByRole('heading',{name:`${role}_20261008.xlsx`,exact:true}).waitFor();
    assert.equal(await sources.locator('.evidence-table tbody tr').count(),count);
    if(role==='erp_receipts') await sources.getByText(/촉매 입고 수량 합계 8개/).waitFor();
    else {
      await sources.getByText('입고/이동처리: 12',{exact:true}).waitFor();
      await sources.getByText('출고/이동처리: 10',{exact:true}).waitFor();
      await sources.getByText('출고/적송처리: 4',{exact:true}).waitFor();
    }
    await sources.getByRole('button',{name:'이번 달 원본으로 사용',exact:true}).click();
    await page.waitForFunction(()=>!document.querySelector('#note')?.disabled);
  }
  for (const [role,factory] of [['umicore_statement','umicore_book'],['glovis_receipts','glovis_book']]) {
    const fixture=spawnSync(python,['-c',`import runpy,sys; m=runpy.run_path('tests/test_partners.py'); sys.stdout.buffer.write(m['content'](m['${factory}']()))`],{cwd:root,windowsHide:true});
    assert.equal(fixture.status,0,fixture.stderr?.toString());
    await chooseSource(sources,role);
    assert.equal(await sources.locator('.source-checklist').getByText('월별 적용 단가',{exact:true}).count(),0);
    await sources.getByLabel('원본 파일',{exact:true}).setInputFiles({name:`${role}.xlsx`,mimeType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',buffer:fixture.stdout});
    assert.equal(await sources.getByRole('button',{name:'원본 보관·읽기',exact:true}).isDisabled(),true);
    await sources.getByRole('checkbox',{name:/전체 기간/}).check();
    await sources.getByRole('button',{name:'원본 보관·읽기',exact:true}).click();
    await sources.getByRole('heading',{name:`${role}.xlsx`,exact:true}).waitFor();
    if(role==='umicore_statement') {
      await sources.getByText(/유미코아 원문 마감 표기 합계 13개/).waitFor();
      await sources.getByText('원문 적송 잔여: -1',{exact:true}).waitFor();
      await sources.getByText('1차 마감 표기: 미기재',{exact:true}).first().waitFor();
    } else {
      await sources.getByText(/글로비스 제품 실제 입고 합계 9개/).waitFor();
      await sources.getByText('입고일: 2026-09-01',{exact:true}).waitFor();
    }
    await sources.getByRole('button',{name:'이번 달 원본으로 사용',exact:true}).click();
    await page.waitForFunction(()=>!document.querySelector('#note')?.disabled);
  }
  for (const [role,factory] of [['bom_master','bom_book'],['route_master','route_book']]) {
    const fixture=spawnSync(python,['-c',`import runpy,sys; m=runpy.run_path('tests/test_basis.py'); sys.stdout.buffer.write(m['content'](m['${factory}']()))`],{cwd:root,windowsHide:true});
    assert.equal(fixture.status,0,fixture.stderr?.toString());
    await registerMaster(page,role,fixture.stdout);
  }
  await page.getByRole('button',{name:'마감 검토',exact:true}).click();
  await page.getByRole('button',{name:'계산 근거',exact:true}).click();
  await page.getByLabel('확인할 자료',{exact:true}).selectOption('basis');
  const basis=page.getByRole('region',{name:'BOM·경로 연결 검토',exact:true});
  await basis.getByRole('button',{name:'채택 자료로 연결 검토'}).click();
  await basis.getByText(/2경로/).waitFor();
  assert.equal(await basis.locator('tbody tr').count(),2);
  await basis.getByLabel('연결 근거 검색').fill('세종공업');
  await page.waitForFunction(()=>document.querySelector('[aria-label="BOM·경로 연결 검토"] tbody')?.children.length===1);
  assert.equal(await basis.getByText('제품 수량: 미정',{exact:true}).count(),1);
  await page.getByRole('button',{name:'자료 등록',exact:true}).click();
  for (const [role,factory] of [['price_master','price_book'],['plan_master','plan_book']]) {
    const fixture=spawnSync(python,['-c',`import runpy,sys; m=runpy.run_path('tests/test_pricing.py'); sys.stdout.buffer.write(m['content'](m['${factory}']()))`],{cwd:root,windowsHide:true});
    assert.equal(fixture.status,0,fixture.stderr?.toString());
    if(role==='price_master'){await registerMaster(page,role,fixture.stdout);continue;}
    await chooseSource(sources,role);
    await sources.getByLabel('원본 파일',{exact:true}).setInputFiles({name:`${role}.xlsx`,mimeType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',buffer:fixture.stdout});
    await sources.getByRole('checkbox',{name:/적용할 기준/}).check();
    await sources.getByRole('button',{name:'원본 보관·읽기',exact:true}).click();
    await sources.getByRole('heading',{name:`${role}.xlsx`,exact:true}).waitFor();
    await sources.getByRole('button',{name:'이번 달 원본으로 사용',exact:true}).click();
    await page.waitForFunction(()=>!document.querySelector('#note')?.disabled);
  }
  assert.equal(await sources.getByRole('button',{name:'기준·계획 자료',exact:true}).count(),0);
  assert.equal(await sources.getByRole('button',{name:/BOM 기준|통합 경로 기준|촉매 단가/}).count(),0);
  await page.getByRole('button',{name:'마감 검토',exact:true}).click();
  await page.getByRole('button',{name:'계산 근거',exact:true}).click();
  await page.getByLabel('확인할 자료',{exact:true}).selectOption('pricing');
  const pricing=page.getByRole('region',{name:'단가·월계획 연결 검토',exact:true});
  await pricing.getByRole('button',{name:'채택 단가·계획 검토'}).click();
  await pricing.getByText('계획 10개 · 10원',{exact:true}).waitFor();
  assert.equal(await pricing.getByText('가단가',{exact:true}).count(),0);
  assert.equal(await pricing.getByText('1원',{exact:true}).count(),2);
  await pricing.getByLabel('단가·계획 검색').fill('공장 A');
  await page.waitForFunction(()=>document.querySelector('[aria-label="단가·월계획 연결 검토"] tbody')?.children.length===1);
  await page.reload();
  await page.waitForFunction(()=>document.querySelectorAll('.sources table:first-of-type tbody tr').length>=7);
  await page.getByRole('button',{name:'자료 등록',exact:true}).click();
  assert.equal(await sources.getByText('이번 달 사용',{exact:true}).count(),7);
  await page.getByRole('button',{name:'마감 검토',exact:true}).click();
  await page.getByRole('button',{name:'계산 근거',exact:true}).click();
  await page.getByLabel('확인할 자료',{exact:true}).selectOption('allocation');
  const allocation=page.getByRole('region',{name:'마감 수량 배분 검토',exact:true});
  await allocation.getByRole('button',{name:'채택 자료로 배분 검토'}).click();
  await allocation.getByText('납품 근거 확인 필요 1품목',{exact:true}).waitFor();
  await allocation.getByLabel('배분 검색').fill('99998-AA001');
  assert.equal(await allocation.locator('tbody tr').count(),1);
  const downloadPromise=page.waitForEvent('download');
  await allocation.getByRole('link',{name:'공장별 수량·촉매 총량 입력 양식 내려받기'}).click();
  const allocationDownload=await downloadPromise;
  assert.equal(allocationDownload.suggestedFilename(),'allocation-input-2026-09.xlsx');
  await page.getByRole('button',{name:'자료 등록',exact:true}).click();
  await sources.getByRole('row').filter({hasText:'product_stock_20261008.xlsx'}).getByRole('button',{name:'내용 보기'}).click();
  await sources.getByText('입고/이동처리: 12',{exact:true}).waitFor();
  await sources.getByLabel('품번·창고·거래처 검색',{exact:true}).fill('없는 품번');
  assert.equal(await sources.locator('.evidence-table tbody tr').count(),0);
  await sources.getByLabel('품번·창고·거래처 검색',{exact:true}).fill('가상 창고');
  assert.equal(await sources.locator('.evidence-table tbody tr').count(),1);
  await page.screenshot({path:path.join(root,'test-results/imports-1920.png'),fullPage:true});
  assert.deepEqual(errors,[]);
  console.log('PASS: workspace lifecycle, source preservation, ERP period confirmation, three ERP roles, directed quantities, adoption and reload.');
} finally {
  await browser.close();
  if (current && current.exitCode === null) {
    const done = new Promise(resolve => current.once('exit',resolve));
    try {
      const session = await (await fetch(`${currentUrl}/api/session`,{signal:AbortSignal.timeout(5000)})).json();
      const response = await fetch(`${currentUrl}/api/shutdown`,{method:'POST',headers:{Origin:currentUrl,'X-Session-Token':session.token},signal:AbortSignal.timeout(5000)});
      if (!response.ok) throw new Error('Test shutdown failed');
    } catch {
      if (process.platform === 'win32') spawnSync('taskkill',['/PID',String(current.pid),'/T','/F'],{windowsHide:true});
      else current.kill();
    }
    await done;
  }
  if (path.dirname(path.resolve(data)) !== path.resolve(os.tmpdir()) || !path.basename(data).startsWith('촉매 W1 테스트 ')) throw new Error('Unexpected cleanup path');
  await rm(data,{recursive:true,force:true});
}
