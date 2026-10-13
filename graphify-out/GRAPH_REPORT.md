# Graph Report - Catalyst_Cutoff  (2026-10-13)

## Corpus Check
- Corpus is ~25,669 words - fits in a single context window. You may not need a graph.

## Summary
- 56 nodes · 82 edges · 7 communities (6 shown, 1 thin omitted)
- Extraction: 100% EXTRACTED · 0% INFERRED · 0% AMBIGUOUS
Semantic token usage/cost: unavailable from the host; not measured as zero.

## Community Hubs (Navigation)
- 원본 정합과 별도 귀속
- 제품 경로와 집계 근거
- 월 작업과 확정 이력
- 미정산과 공통 출력
- 설계 기준과 후속 작업
- 단가와 수량 금액 검산
- 기본 배분과 월별 입력

## God Nodes (most connected - your core abstractions)
1. `원본 등록·수정본·출처 추적` - 11 edges
2. `월 확정본과 근거 스냅샷` - 9 edges
3. `전체 점검·운영 설계` - 8 edges
4. `제품별 다중 물류 경로` - 8 edges
5. `제품×BOM 기본 비율 배분` - 7 edges
6. `일반 배분 대상 총량` - 7 edges
7. `집계 지점 선택과 후속 이동 중복 제외` - 6 edges
8. `동일 확정 데이터의 엑셀 출력` - 6 edges
9. `촉매사·자체 장부 원천 정합` - 5 edges
10. `확정 전 수량·금액 균형 검산` - 5 edges

## Surprising Connections (you probably didn't know these)
- `촉매 마감 자동화 설계 저장소` --references--> `2026-10-08 검토 기록과 후속 정정`  [EXTRACTED]
  README.md → docs/reviews/2026-10-08-검토폴더-검토결과.md
- `촉매 마감 자동화 설계 저장소` --references--> `전체 점검·운영 설계`  [EXTRACTED]
  README.md → docs/reviews/2026-10-12-전체점검-운영설계.md
- `촉매 마감 자동화 설계 저장소` --references--> `촉매 마감 자동화 상세 설계`  [EXTRACTED]
  README.md → docs/superpowers/specs/2026-10-08-촉매마감-자동화-design.md
- `원본 등록·수정본·출처 추적` --shares_data_with--> `반제품 적송출고 근거`  [EXTRACTED]
  docs/reviews/2026-10-12-전체점검-운영설계.md → docs/superpowers/specs/2026-10-08-촉매마감-자동화-design.md
- `원본 등록·수정본·출처 추적` --shares_data_with--> `ERP 등록 단가와 적용 단가`  [EXTRACTED]
  docs/reviews/2026-10-12-전체점검-운영설계.md → docs/superpowers/specs/2026-10-08-촉매마감-자동화-design.md

## Communities (7 total, 1 thin omitted)

### Community 0 - "원본 정합과 별도 귀속"
Cohesion: 0.24
Nodes (7): BOM 구성·소요량 버전, 28991-4C520 전주 직사급 예외, ERP 촉매 입고 원본, 글로비스 실제 입고 원본, 유미코아 Summary·주간 납품 원본, 승인 양식 규칙과 수동 복구, 희성 출하·적송재고 원본

### Community 1 - "제품 경로와 집계 근거"
Cohesion: 0.22
Nodes (8): 완성차 직납·HSL 상세 유보, 제품 수불 비율 근거, 제품별 다중 물류 경로, 현대기아 세부 공장, ERP 통합 마감처, 반제품 적송출고 근거, UCC 1차사 경유, WCC 엔진공장 직납

### Community 2 - "월 작업과 확정 이력"
Cohesion: 0.25
Nodes (4): 작업 초안 자동 저장, 월 확정본과 근거 스냅샷, 2JAV0 및 과거 배분 차이, 월별 입력·검토 화면 초안

### Community 3 - "미정산과 공통 출력"
Cohesion: 0.29
Nodes (6): 종합·누적·과거 이관, ERP 거래처별 명세, 현대기아 세부 공장 검토 명세, 희성 공장별 가공표, 미정산 명세 출력, 계획 버전·계획 대비 분석

### Community 4 - "설계 기준과 후속 작업"
Cohesion: 0.47
Nodes (4): 2026-10-08 검토 기록과 후속 정정, 전체 점검·운영 설계, 촉매 마감 자동화 상세 설계, 촉매 마감 자동화 설계 저장소

### Community 5 - "단가와 수량 금액 검산"
Cohesion: 0.40
Nodes (3): 9월 전체 확정 명세 대조, 희성3촉매 입고 각2개 차이, ERP 등록 단가와 적용 단가

## Knowledge Gaps
- **6 isolated node(s):** `ERP 통합 마감처`, `완성차 직납·HSL 상세 유보`, `작업 초안 자동 저장`, `희성 공장별 가공표`, `월별 입력·검토 화면 초안` (+1 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 13 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `월 확정본과 근거 스냅샷` connect `월 작업과 확정 이력` to `원본 정합과 별도 귀속`, `미정산과 공통 출력`, `설계 기준과 후속 작업`, `기본 배분과 월별 입력`?**
  _High betweenness centrality (0.374) - this node is a cross-community bridge._
- **What connects `ERP 통합 마감처`, `완성차 직납·HSL 상세 유보`, `작업 초안 자동 저장` to the rest of the system?**
  _6 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Why does `전체 점검·운영 설계` connect `설계 기준과 후속 작업` to `원본 정합과 별도 귀속`, `제품 경로와 집계 근거`, `월 작업과 확정 이력`?**
  _High betweenness centrality (0.321) - this node is a cross-community bridge._
- **Why does `원본 등록·수정본·출처 추적` connect `원본 정합과 별도 귀속` to `제품 경로와 집계 근거`, `월 작업과 확정 이력`, `미정산과 공통 출력`, `단가와 수량 금액 검산`?**
  _High betweenness centrality (0.291) - this node is a cross-community bridge._

## Run scope and limitations

Design-document graph only; numerical correctness of source workbooks was not re-audited. Semantic extraction was performed by a host agent. The host exposes no input/output token usage; zero placeholders in internal extraction data are not measured usage or cost.

graphify-out/ is written into the working tree and may appear in git status; review the generated document-derived content before sharing or committing.
