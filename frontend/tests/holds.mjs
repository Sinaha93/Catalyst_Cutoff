import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {spawn,spawnSync} from 'node:child_process';
import {mkdtemp,mkdir} from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {fileURLToPath} from 'node:url';

const root=fileURLToPath(new URL('../../',import.meta.url));
const data=await mkdtemp(path.join(os.tmpdir(),'촉매 보류 검증 '));
const python=process.env.CATALYST_TEST_PYTHON??path.join(root,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
const seed=spawnSync(python,['-c',"import sys;sys.path.insert(0,'tests');from pathlib import Path;from test_holds import seed;from backend.adapters.storage import Store;seed(Store(Path(sys.argv[1])))",data],{cwd:root,windowsHide:true,encoding:'utf8'});
assert.equal(seed.status,0,seed.stderr);
const browser=await chromium.launch({headless:true,channel:'msedge'});
let proc,url;
async function start(){
 proc=spawn(python,['-m','backend.launcher','--data-dir',data,'--no-browser'],{cwd:root,windowsHide:true});
 url=await new Promise((resolve,reject)=>{let output='';const timer=setTimeout(()=>reject(new Error(output)),25000);proc.stdout.on('data',x=>{output+=x;const m=output.match(/CATALYST_URL=(http:\/\/127\.0\.0\.1:\d+)/);if(m){clearTimeout(timer);resolve(m[1])}});proc.stderr.on('data',x=>output+=x);proc.on('error',reject);proc.on('exit',code=>{clearTimeout(timer);reject(new Error(`exit ${code}: ${output}`))})});
}
async function stop(){
 if(!proc||proc.exitCode!==null)return;
 const p=proc;const done=new Promise(resolve=>p.once('exit',resolve));
 const session=await (await fetch(url+'/api/session')).json();
 await fetch(url+'/api/shutdown',{method:'POST',headers:{Origin:url,'X-Session-Token':session.token}});
 await done;
}
try{
 await start();const page=await browser.newPage({viewport:{width:1536,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(url+'#review/evidence');
 await page.getByLabel('확인할 자료',{exact:true}).selectOption('holds');
 const holds=page.getByRole('region',{name:'미마감 수량 조정',exact:true});
 await holds.getByRole('button',{name:'미마감 내역 불러오기'}).click();
 await holds.getByLabel('미마감 촉매 선택').selectOption('99998-AA001');
 await holds.getByLabel('이번 달 추가 미마감 1').fill('1');await holds.getByLabel('전월 미마감 중 이번 달 마감 1').fill('4');
 await holds.getByLabel('미마감 사유 1').fill('가상 검증: 일부 해소');await holds.getByLabel('미마감 근거 1').fill('가상 전표 17호');
 assert.equal(await page.getByRole('navigation',{name:'주요 메뉴'}).getByRole('button',{name:'월 작업',exact:true}).isEnabled(),false);
 await holds.getByRole('button',{name:'미마감 조정 저장'}).click();await holds.getByRole('alert').waitFor();
 assert.equal(await holds.getByLabel('미마감 근거 1').inputValue(),'가상 전표 17호');
 await holds.getByLabel('전월 미마감 중 이번 달 마감 1').fill('2');await holds.getByRole('button',{name:'미마감 조정 저장'}).click();
 await holds.getByText('다음 달 미마감 2개를 새 이력으로 저장했습니다.',{exact:true}).waitFor();
 const allocation=page.getByRole('region',{name:'마감 수량 배분 검토',exact:true});
 await page.getByLabel('확인할 자료',{exact:true}).selectOption('allocation');
 await allocation.getByRole('button',{name:'채택 자료로 배분 검토'}).click();await allocation.getByText('8개',{exact:true}).waitFor();
 await page.getByLabel('확인할 자료',{exact:true}).selectOption('holds');
 await holds.getByLabel('이번 달 추가 미마감 1').fill('0');await holds.getByLabel('전월 미마감 중 이번 달 마감 1').fill('3');
 await holds.getByLabel('미마감 사유 1').fill('가상 검증: 전부 해소');await holds.getByRole('button',{name:'미마감 조정 저장'}).click();
 await holds.getByText('다음 달 미마감 0개를 새 이력으로 저장했습니다.',{exact:true}).waitFor();
 await stop();await start();await page.goto(url+'#review/evidence');
 await page.getByLabel('확인할 자료',{exact:true}).selectOption('holds');
 await holds.getByRole('button',{name:'미마감 내역 불러오기'}).click();await holds.getByLabel('미마감 촉매 선택').selectOption('99998-AA001');
 assert.equal(await holds.getByLabel('전월 미마감 중 이번 달 마감 1').inputValue(),'3');
 await holds.getByText('미마감 조정 이력 2건',{exact:true}).click();
 await holds.getByText(/현대 울산 · 전월 미마감 일부 마감 \+ 이번 달 추가 미마감/).waitFor();await holds.getByText(/현대 울산 · 전월 미마감 전량 마감/).waitFor();
 await page.getByLabel('확인할 자료',{exact:true}).selectOption('allocation');
 await allocation.getByRole('button',{name:'채택 자료로 배분 검토'}).click();await allocation.getByText('10개',{exact:true}).waitFor();
 await page.getByLabel('확인할 자료',{exact:true}).selectOption('holds');
 await holds.scrollIntoViewIfNeeded();await mkdir(path.join(root,'test-results'),{recursive:true});await page.screenshot({path:path.join(root,'test-results/holds-workflow.png')});
 // Render the real allocation function's synthetic multi-plant result in the
 // same UI, independently of hold editing and without changing stored sources.
 const detailed=spawnSync(python,['-c',"import sys,json;sys.path.insert(0,'tests');from test_basis import sources;from test_allocation import pool;from backend.application.basis import link;from backend.application.allocation import calculate;b=link(sources());b['rows'][0]['plant']='울산3';b['rows'][1]['plant']='울산1';b['rows'][1]['components'][0]['destination']='현대 울산';p=pool(previous='0',incoming='100');p['evidence']={'filename':'가상 검증','sheet':'총량','row_number':1};print(json.dumps(calculate(b,[p]),ensure_ascii=False))"],{cwd:root,windowsHide:true,encoding:'utf8',env:{...process.env,PYTHONIOENCODING:'utf-8'}});
 assert.equal(detailed.status,0,detailed.stderr);
 await page.route('**/api/months/2026-09/allocation',async route=>{
  const response=await route.fetch();const original=await response.json();
  await route.fulfill({response,json:{...original,...JSON.parse(detailed.stdout)}});
 });
 await page.setViewportSize({width:1920,height:1080});
 await page.getByLabel('확인할 자료',{exact:true}).selectOption('allocation');
 await allocation.getByRole('button',{name:'채택 자료로 배분 검토'}).click();
 await allocation.getByText('60개',{exact:true}).waitFor();await allocation.getByText('40개',{exact:true}).waitFor();
 await allocation.getByText('ERP 지역별 합계',{exact:true}).click();
 await allocation.getByText('현대 울산: 100개',{exact:true}).waitFor();
 await allocation.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(root,'test-results/allocation-plants-1920.png')});
 assert.deepEqual(errors,[]);
 console.log('PASS holds: invalid input retained, dirty navigation guarded, save/allocation, supersession, restart, history and detailed plant/ERP display');
}finally{await stop();await browser.close()}
