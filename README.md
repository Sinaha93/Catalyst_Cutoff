# Catalyst_Cutoff

Windows PC에서 혼자 사용하는 촉매 마감 자동화 프로그램입니다. ERP와 촉매사 자료를 대조하고 제품 납품·BOM·마감처를 연결하여 마감 수량과 금액을 검토한 뒤 엑셀을 만드는 것이 목표입니다.

## 현재 상태 — W4.3

- 월 작업, 메모, 원본 보관, 자료 검산·정정·채택 및 변경 이력
- 희성 출하·적송재고, ERP 입고·제품/반제품 수불, 유미코아 Summary, 글로비스 실제 입고 읽기
- BOM·경로 연결, ERP 단가·월별 적용 단가·월계획 검토
- 희성 마감 수량 배분, 공장별 수량 보완, 원천 수량 자동 대조
- 월별 보류·해소 저장, 이력 조회, 기준 변경 감지 및 희성 배분 연결

원천 차이 처리, 유미코아 최종 마감 연결, 금액 검산, 월 확정·다음 달 이월·최종 엑셀 출력은 남아 있습니다. 현재 UI는 기능 검증용이며 최종 디자인은 확정하지 않았습니다.

## 다른 PC에서 시작

Windows에 Python 3.12와 Node.js 22.12 이상을 준비합니다. 코드와 업무 자료는 별도로 옮깁니다.

```powershell
git clone https://github.com/Sinaha93/Catalyst_Cutoff.git
cd Catalyst_Cutoff
.\setup.ps1
.\start.ps1 -ChooseDataDir
```

자료 폴더 선택 창에서 별도로 옮긴 `프로그램_개발검토_W4_3` 폴더를 선택합니다. 기존 DB는 스키마 변경 전에 백업합니다. 의존성 설치에는 인터넷이 필요하며 현재 구현 기능은 외부 AI API 없이 실행됩니다.

이관 ZIP의 코드 폴더에는 미커밋 변경이 있습니다. 그 위에서 바로 pull하거나 덮어쓰지 말고, 새 폴더에 clone한 코드로 ZIP의 업무 자료 폴더를 여세요. ZIP 작성 당시의 미푸시 안내보다 이번 GitHub 코드 안내를 우선합니다.

상세한 재개 순서는 [개발 재개 안내](docs/handoff/README.md)를 확인합니다. 업무 원본·ZIP·DB·검증 화면과 실제 업무 수치를 담은 이번 검토 문서는 이번 커밋에 포함하지 않습니다.

## 검증

```powershell
.\.venv\Scripts\python.exe -m pytest -q
cd frontend
npm.cmd run build
npm.cmd run test:browser
node tests/holds.mjs
```

브라우저 검증에는 Microsoft Edge가 필요합니다. W4.3 검증에서 Python 테스트 총 147개(전체 146개와 추가 검증 1개), 프런트엔드 빌드와 두 브라우저 검증을 통과했습니다.

GitHub 전송은 사용자가 해당 시점에 명시적으로 요청한 경우에만 진행합니다. 결과물 범위는 엑셀이며 PPT 생성은 포함하지 않습니다.
