import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {spawn, spawnSync} from 'node:child_process';
import {mkdtemp, mkdir, rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = fileURLToPath(new URL('../../', import.meta.url));
const data = await mkdtemp(path.join(os.tmpdir(), '촉매 W1 테스트 '));
const python = process.env.CATALYST_TEST_PYTHON ?? path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
await mkdir(path.join(root, 'test-results'), {recursive:true});
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
  const sources=page.getByRole('region',{name:'원본 자료 등록',exact:true});
  await sources.getByLabel('원본 파일',{exact:true}).setInputFiles({name:'희성 예시.xlsx',mimeType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',buffer:generated.stdout});
  await sources.getByRole('button',{name:'원본 보관·읽기',exact:true}).click();
  await sources.getByText('읽기 검산 완료',{exact:true}).waitFor();
  await sources.getByText(/원문 3행 · 촉매 2종/).waitFor();
  assert.equal(await sources.locator('.evidence-table tbody tr').count(),3);
  await sources.getByRole('button',{name:'원본 보관·읽기',exact:true}).click();
  await sources.getByText('같은 파일이 이미 등록되어 있습니다. 중복 추가하지 않았습니다.').waitFor();
  assert.equal(await sources.locator('table').first().locator('tbody tr').count(),1);
  await sources.getByRole('button',{name:'이번 달 원본으로 사용',exact:true}).click();
  await sources.getByText('이번 달 사용',{exact:true}).waitFor();
  await page.reload();
  await sources.getByText('이번 달 사용',{exact:true}).waitFor();
  await sources.getByRole('button',{name:'내용 보기',exact:true}).click();
  await sources.getByText(/원문 3행 · 촉매 2종/).waitFor();
  await page.screenshot({path:path.join(root,'test-results/imports-1920.png'),fullPage:true});
  assert.deepEqual(errors,[]);
  console.log('PASS: workspace lifecycle, list retry, read lock, upload evidence, duplicate source, adoption and restored source.');
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
