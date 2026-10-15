import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {spawn,spawnSync} from 'node:child_process';
import {mkdtemp,mkdir} from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../../',import.meta.url));
const data=await mkdtemp(path.join(os.tmpdir(),'catalyst-month-delete-'));
const python=process.env.CATALYST_TEST_PYTHON??path.join(root,'.venv','Scripts/python.exe');
const seed=spawnSync(python,['-c',"import sys;sys.path.insert(0,'tests');from pathlib import Path;from test_closing import ready;from backend.adapters.storage import Store;ready(Store(Path(sys.argv[1])))",data],{cwd:root,windowsHide:true,encoding:'utf8',env:{...process.env,PYTHONIOENCODING:'utf-8'}});assert.equal(seed.status,0,seed.stderr);
const proc=spawn(python,['-m','backend.launcher','--data-dir',data,'--no-browser'],{cwd:root,windowsHide:true,env:{...process.env,PYTHONIOENCODING:'utf-8'}});
const browser=await chromium.launch({headless:true,channel:'msedge'});let url;
try{
 url=await new Promise((resolve,reject)=>{let output='';const timer=setTimeout(()=>reject(new Error(output)),25000);proc.stdout.on('data',x=>{output+=x;const m=output.match(/CATALYST_URL=(http:\/\/127\.0\.0\.1:\d+)/);if(m){clearTimeout(timer);resolve(m[1])}});proc.stderr.on('data',x=>output+=x);proc.on('error',reject);proc.on('exit',c=>{clearTimeout(timer);reject(new Error(`exit ${c}: ${output}`))})});
 const page=await browser.newPage({viewport:{width:1920,height:1080}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(url);await page.locator('#note').waitFor();
 const list=page.locator('.month-list');
 const deletion=list.getByRole('button',{name:'2026년 9월 작업 삭제',exact:true});
 await page.once('dialog',d=>d.dismiss());await deletion.click();assert.equal(await list.locator('tbody tr').count(),1);
 const session=await(await fetch(url+'/api/session')).json();
 const before=await(await fetch(url+'/api/months/2026-09')).json();
 const unauthorized=await fetch(url+'/api/months/2026-09',{method:'DELETE',headers:{Origin:url,'Content-Type':'application/json'},body:JSON.stringify({expected_revision:before.revision})});assert.equal(unauthorized.status,403);
 await mkdir(path.join(root,'test-results'),{recursive:true});await page.screenshot({path:path.join(root,'test-results/month-delete-1920.png'),fullPage:true});
 await page.setViewportSize({width:1536,height:864});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:path.join(root,'test-results/month-delete-1536.png'),fullPage:true});
 page.once('dialog',d=>{assert(d.message().includes('2026년 9월'));assert(d.message().includes('되돌릴 수 없습니다'));void d.accept()});await deletion.click();
 await list.getByText('2026년 9월 작업을 완전히 삭제했습니다.',{exact:true}).waitFor();
 assert.equal(await list.locator('tbody tr').count(),0);assert.equal(await page.locator('#note').count(),0);
 await page.reload();await list.getByText('아직 월 작업이 없습니다',{exact:true}).waitFor();
 await page.locator('#month').fill('2026-09');await page.getByRole('button',{name:'월 작업 열기',exact:true}).click();await page.locator('#note').waitFor();
 const after=await(await fetch(url+'/api/months/2026-09')).json();assert.notEqual(after.id,before.id);assert.equal(after.revision,1);
 assert.deepEqual(errors,[]);console.log('PASS: permanent month deletion confirmation/cancel, session security, reload persistence, current selection clearing and clean new month.');
}finally{
 await browser.close();if(url&&proc.exitCode===null){const ended=new Promise(resolve=>proc.once('exit',resolve));const s=await(await fetch(url+'/api/session')).json();await fetch(url+'/api/shutdown',{method:'POST',headers:{Origin:url,'X-Session-Token':s.token}});await ended}else if(proc.exitCode===null)proc.kill();
}
