import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {spawn,spawnSync} from 'node:child_process';
import {mkdtemp,mkdir} from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {fileURLToPath} from 'node:url';

const root=fileURLToPath(new URL('../../',import.meta.url));
const data=await mkdtemp(path.join(os.tmpdir(),'catalyst-guide-'));
const python=process.env.CATALYST_TEST_PYTHON??path.join(root,'.venv','Scripts/python.exe');
const capture=process.env.CATALYST_CAPTURE_GUIDE==='1';
const imageDir=path.join(root,'frontend/public/guide');
const resultDir=path.join(root,'test-results');
await mkdir(resultDir,{recursive:true});
if(capture){
 await mkdir(imageDir,{recursive:true});
 const seed=spawnSync(python,['-c',"import sys;sys.path.insert(0,'tests');from pathlib import Path;from test_closing import ready,edit,MONTH;from test_holds import line;from test_masters_reset import publish;from backend.adapters.storage import Store;from backend.application.closing import Closing;s=Store(Path(sys.argv[1]));ready(s);publish(s);publish(s,'bom_master');c=Closing(s);edit(c,'hold',{'lines':[line()]});edit(c,'prices',{'lines':[{'destination':'현대 울산','price':'12.55','price_kind':'가단가'}]});assert c.preview(MONTH)['ready']",data],{cwd:root,windowsHide:true,encoding:'utf8',env:{...process.env,PYTHONIOENCODING:'utf-8'}});
 assert.equal(seed.status,0,seed.stderr);
}
const proc=spawn(python,['-m','backend.launcher','--data-dir',data,'--no-browser'],{cwd:root,windowsHide:true,env:{...process.env,PYTHONIOENCODING:'utf-8'}});
let url;
const browser=await chromium.launch({headless:true,channel:'msedge'});
try{
 url=await new Promise((resolve,reject)=>{let output='';const timer=setTimeout(()=>reject(new Error(output)),25000);proc.stdout.on('data',x=>{output+=x;const m=output.match(/CATALYST_URL=(http:\/\/127\.0\.0\.1:\d+)/);if(m){clearTimeout(timer);resolve(m[1])}});proc.stderr.on('data',x=>output+=x);proc.on('error',reject);proc.on('exit',c=>{clearTimeout(timer);reject(new Error(`exit ${c}: ${output}`))})});
 const page=await browser.newPage({viewport:{width:1920,height:1080}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(url);
 const nav=page.getByRole('navigation',{name:'주요 메뉴',exact:true});
 if(capture){
  await page.locator('#note').waitFor();
  const shot=async(name)=>{await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:path.join(imageDir,name+'.png'),clip:{x:0,y:0,width:1920,height:1000}})};
  await page.waitForFunction(()=>document.querySelector('.workflow-step')&&!document.querySelector('.workflow-next button')?.disabled);
  await shot('month');
  if(process.env.CATALYST_CAPTURE_GUIDE_MONTH_ONLY!=='1'){
  await nav.getByRole('button',{name:'자료 등록',exact:true}).click();
  await page.getByRole('region',{name:'원본 자료 등록',exact:true}).getByRole('button',{name:'원본 보관·읽기',exact:true}).waitFor();
  await page.getByRole('button',{name:'희성 출하 원본 ✓ 이번 달 사용',exact:true}).waitFor();
  await shot('sources');
  await nav.getByRole('button',{name:'마감 검토',exact:true}).click();
  const review=page.getByRole('region',{name:'통합 마감 검토',exact:true});
  await review.getByLabel('확인할 품목만',{exact:false}).uncheck();
  await review.getByRole('button',{name:/99998-AA001/}).click();
  await review.getByRole('heading',{name:'99998-AA001',exact:true}).waitFor();
  await shot('review');
  const sub=page.getByRole('navigation',{name:'마감 검토 메뉴',exact:true});
  await sub.getByRole('button',{name:'미마감 조정',exact:true}).click();
  await review.getByLabel('이번 달 추가 미마감',{exact:true}).waitFor();
  await shot('hold');
  await sub.getByRole('button',{name:'공장별 수량 조정',exact:true}).click();
  await review.getByPlaceholder('공란 = 자동 계산').waitFor();
  await shot('quantities');
  await nav.getByRole('button',{name:'확정·출력',exact:true}).click();
  await page.getByRole('button',{name:'이번 달 마감 확정',exact:true}).waitFor();
  await shot('final');
  await nav.getByRole('button',{name:'기준 관리',exact:true}).click();
  await page.getByRole('region',{name:'프로그램 기준 관리',exact:true}).waitFor();
  await shot('masters');
  }
  console.log('Captured 7 actual UI screenshots from synthetic fixtures only.');
 }else{
  await page.getByText('아직 월 작업이 없습니다',{exact:true}).waitFor();
  await nav.getByRole('button',{name:'사용 가이드',exact:true}).click();
  await page.waitForURL('**/#guide');
  const guide=page.getByRole('region',{name:'사용 가이드',exact:true});
  await guide.getByRole('heading',{name:'마감월을 여세요',exact:true}).waitFor();
  assert.equal(await page.locator('.work-grid').isVisible(),false);
  assert.equal((await(await fetch(url+'/api/months')).json()).length,0,'opening guide must not create a draft');
  await page.reload();await guide.getByRole('heading',{name:'마감월을 여세요',exact:true}).waitFor();
  for(let i=0;i<6;i++){
   await guide.locator('.guide-step-menu button').nth(i).click();
   const img=guide.locator('.guide-picture img');
   await img.evaluate(el=>el.decode());
   assert(await img.evaluate(el=>el.naturalWidth>0));
  }
  await guide.getByRole('button',{name:'확정·출력 예시 화면 크게 보기',exact:true}).click();
  await page.getByRole('dialog',{name:'가이드 화면 확대',exact:true}).waitFor();
  await page.keyboard.press('Escape');
  assert.equal(await page.getByRole('dialog',{name:'가이드 화면 확대',exact:true}).isVisible(),false);
  await guide.getByRole('navigation',{name:'가이드 주제'}).getByRole('button',{name:'무슨 파일을 넣나요?',exact:true}).click();
  assert.equal(await guide.locator('tbody tr').count(),8);
  await guide.getByRole('button',{name:'수량 수정 이해하기',exact:true}).click();
  await guide.getByText('100 − 10 + 5 = 95개',{exact:true}).waitFor();
  await guide.getByRole('button',{name:'막혔을 때',exact:true}).click();
  await guide.getByLabel('궁금한 내용 검색').fill('다른 컴퓨터');
  assert.equal(await guide.locator('.guide-faq details').count(),1);
  await guide.locator('.guide-faq summary').click();
  await guide.getByText(/GitHub 프로그램 코드만/).waitFor();
  await guide.getByRole('button',{name:'마감 따라하기',exact:true}).click();
  await guide.locator('.guide-step-menu button').first().click();
  await page.screenshot({path:path.join(resultDir,'guide-1920.png'),fullPage:true});
  await page.setViewportSize({width:1536,height:864});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'1536 viewport has no horizontal overflow');
  await page.screenshot({path:path.join(resultDir,'guide-1536.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'small guide viewport has no horizontal overflow');
  await guide.getByRole('button',{name:'이 작업 화면으로 이동 →',exact:true}).click();
  await page.waitForURL('**/#workspace');
  await page.locator('#month').fill('2026-10');
  await page.getByRole('button',{name:'월 작업 열기',exact:true}).click();await page.locator('#note').waitFor();
  const before=await(await fetch(url+'/api/months/2026-10')).json();
  await nav.getByRole('button',{name:'사용 가이드',exact:true}).click();
  await guide.getByRole('button',{name:'용어 쉽게 보기',exact:true}).click();
  const after=await(await fetch(url+'/api/months/2026-10')).json();assert.equal(after.revision,before.revision,'guide does not change monthly inputs');
  await guide.getByRole('button',{name:'마감 따라하기',exact:true}).click();
  await guide.locator('.guide-step-menu button').nth(1).click();
  await guide.getByRole('button',{name:'이 작업 화면으로 이동 →',exact:true}).click();
  await page.waitForURL('**/#sources');
  await page.getByLabel('원본 파일',{exact:true}).setInputFiles({name:'guide-example.xlsx',mimeType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',buffer:Buffer.from('synthetic, never uploaded')});
  await nav.getByRole('button',{name:'사용 가이드',exact:true}).click();
  await guide.getByRole('heading',{name:'이번 달 자료를 넣으세요',exact:true}).waitFor();
  await guide.getByRole('button',{name:'이 작업 화면으로 이동 →',exact:true}).click();
  assert.equal(await page.getByLabel('원본 파일',{exact:true}).evaluate(el=>el.files[0]?.name),'guide-example.xlsx','guide preserves an unsubmitted file selection');
  await page.getByLabel('원본 파일',{exact:true}).setInputFiles([]);
  await nav.getByRole('button',{name:'사용 가이드',exact:true}).click();
  await guide.getByRole('heading',{name:'이번 달 자료를 넣으세요',exact:true}).waitFor();
  assert.equal((await(await fetch(url+'/api/months/2026-10')).json()).revision,before.revision,'source example was not uploaded');
  await nav.getByRole('button',{name:'월 작업',exact:true}).click();
  await page.route('**/api/months/2026-10',route=>route.request().method()==='PATCH'?route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({message:'guide-test unsaved note'})}):route.continue());
  await page.locator('#note').fill('가이드 이동 보호 테스트');
  await page.waitForFunction(()=>document.querySelector('nav[aria-label="주요 메뉴"] button:last-child')?.disabled===true);
  await page.locator('#note').fill(before.note);
  await page.waitForFunction(()=>document.querySelector('nav[aria-label="주요 메뉴"] button:last-child')?.disabled===false);
  await page.unroute('**/api/months/2026-10');
  // Guide remains readable when a saved-month query fails.
  await page.route('**/api/months',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({message:'guide-test query error'})}));
  await page.goto(url);
  await page.getByRole('button',{name:'다시 연결',exact:true}).waitFor();
  await nav.getByRole('button',{name:'사용 가이드',exact:true}).click();
  await guide.getByRole('heading',{name:'마감월을 여세요',exact:true}).waitFor();
  console.log('Guide navigation, all screenshots, zoom/Escape, FAQ, no-draft, read-only behavior and viewport checks passed.');
 }
 assert.deepEqual(errors,[]);
}finally{
 await browser.close();
 if(url&&proc.exitCode===null){const ended=new Promise(resolve=>proc.once('exit',resolve));const session=await(await fetch(url+'/api/session')).json();await fetch(url+'/api/shutdown',{method:'POST',headers:{Origin:url,'X-Session-Token':session.token}});await ended}else if(proc.exitCode===null)proc.kill();
}
