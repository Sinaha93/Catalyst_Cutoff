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
  await page.goto(server.url);
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
  assert.deepEqual(errors,[]);
  console.log('PASS: create, autosave, refresh, duplicate month, responsive widths, failed-save retry, stale revision, shutdown and process restart.');
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
