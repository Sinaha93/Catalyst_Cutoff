import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {spawn,spawnSync} from 'node:child_process';
import {mkdtemp,mkdir} from 'node:fs/promises';
import path from 'node:path';import os from 'node:os';import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../../',import.meta.url));
const data=await mkdtemp(path.join(os.tmpdir(),'catalyst-master-reset-'));
const python=path.join(root,'.venv','Scripts/python.exe');
const seeded=spawnSync(python,['-c',"import sys;sys.path.insert(0,'tests');from pathlib import Path;from test_holds import seed;from test_masters_reset import publish;from backend.adapters.storage import Store;s=Store(Path(sys.argv[1]));seed(s);publish(s,'bom_master');publish(s,'bom_master');publish(s,'route_master')",data],{cwd:root,windowsHide:true});assert.equal(seeded.status,0,seeded.stderr.toString());
const proc=spawn(python,['-m','backend.launcher','--data-dir',data,'--no-browser'],{cwd:root,windowsHide:true});
const url=await new Promise((resolve,reject)=>{let out='';const t=setTimeout(()=>reject(Error(out)),25000);proc.stdout.on('data',b=>{out+=b;const m=out.match(/CATALYST_URL=(http:\/\/127\.0\.0\.1:\d+)/);if(m){clearTimeout(t);resolve(m[1])}});proc.stderr.on('data',b=>out+=b);proc.on('error',reject)});
const browser=await chromium.launch({headless:true,channel:'msedge'});
try{
 const page=await browser.newPage({viewport:{width:1536,height:864}});const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto(url);
 await page.getByRole('navigation',{name:'주요 메뉴'}).getByRole('button',{name:'기준 관리',exact:true}).click();
 const panel=page.getByRole('region',{name:'프로그램 기준 관리'}),cards=panel.getByRole('group',{name:'기준 등록·적용 상태'});
 const bom=cards.getByRole('button',{name:'BOM 버전',exact:true}),route=cards.getByRole('button',{name:'물류 경로·공장',exact:true});
 await bom.click();await bom.getByText('✓ 이번 달 사용',{exact:true}).waitFor();
 const reset=panel.getByRole('region',{name:'선택한 기준 자료 초기화'});
 await reset.getByRole('button',{name:'BOM 초기화 범위 확인',exact:true}).click();
 await reset.getByText(/버전 2개/).waitFor();assert.equal(await reset.getByRole('button',{name:'확인한 기준 초기화 실행',exact:true}).isDisabled(),true);
 await reset.getByRole('button',{name:'취소',exact:true}).click();await bom.getByText('✓ 이번 달 사용',{exact:true}).waitFor();
 await reset.getByRole('button',{name:'BOM 초기화 범위 확인',exact:true}).click();
 await reset.getByRole('checkbox',{name:'BOM의 등록 버전·파일을 비우는 것을 확인했습니다.',exact:true}).check();
 await mkdir(path.join(root,'test-results'),{recursive:true});await reset.screenshot({path:path.join(root,'test-results/master-reset-confirm.png')});
 await reset.getByRole('button',{name:'확인한 기준 초기화 실행',exact:true}).click();
 await bom.getByText('등록된 기준 없음',{exact:true}).waitFor();await route.getByText('✓ 이번 달 사용',{exact:true}).waitFor();
 const overview=await(await fetch(url+'/api/months/2026-09/masters')).json();assert(!overview.versions.some(v=>v.role==='bom_master'));assert(overview.selected.route_master);
 // Re-register the same BOM through the new, same-screen upload workflow.
 const fixture=spawnSync(python,['-c',"import sys;sys.path.insert(0,'tests');from test_basis import bom_book,content;sys.stdout.buffer.write(content(bom_book()))"],{cwd:root,windowsHide:true});assert.equal(fixture.status,0);
 await panel.getByLabel('기준 파일',{exact:true}).setInputFiles({name:'BOM-again.xlsx',mimeType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',buffer:fixture.stdout});
 await panel.getByRole('button',{name:'기준 파일 읽기',exact:true}).click();await panel.getByText('BOM-again.xlsx · 읽기 검산 완료',{exact:true}).waitFor();
 await panel.getByLabel('기준 변경 사유').fill('합성 기준 초기화 후 재등록');
 await panel.getByRole('button',{name:'기준 변경 내용 비교',exact:true}).click();await panel.getByRole('button',{name:'새 기준 버전 저장',exact:true}).click();
 await panel.getByText('새 기준 버전을 저장했습니다.',{exact:false}).waitFor();
 await panel.getByRole('button',{name:'이번 달 적용 전 차이 보기',exact:true}).click();await panel.getByRole('button',{name:'이 버전을 이번 달에 적용',exact:true}).click();
 await bom.getByText('✓ 이번 달 사용',{exact:true}).waitFor();await bom.getByText('v1 · 2026-09부터',{exact:true}).waitFor();assert.deepEqual(errors,[]);
 console.log('PASS master reset preview/cancel/confirmation, only selected family removed, route preserved, same BOM re-registration');
}finally{
 await browser.close();const s=await(await fetch(url+'/api/session')).json();const done=new Promise(r=>proc.once('exit',r));await fetch(url+'/api/shutdown',{method:'POST',headers:{Origin:url,'X-Session-Token':s.token}});await done;
}
