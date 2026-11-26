이 폴더(hanwoo-map)의 disease_status.json 을 최신 가축질병 현황으로 갱신해. 질문하지 말고 끝까지 진행하고, 한글로 한 줄 요약만 답해.

자료 읽는 법: WebFetch/WebSearch 대신 Bash 의 `curl -sL -m 30 URL -o /tmp/x.html` 로 두 페이지를 받아 grep·python3 으로 해석한다(둘 다 curl 로 HTML 이 받아진다. 데이터가 없는 것처럼 보이면 JS 호출 주소를 HTML 에서 찾아 그것도 curl 한다).

규칙 (CLAUDE.md '가축질병 현황' 절 준수):
- 위기경보 게이지(fmd·ai·asf): 농식품부 https://www.mafra.go.kr/FMD-AI2/ 의 지역별 단계 중 가장 높은 단계가 level. 구제역은 보도자료 확인 시 basis=official, AI·ASF는 화면 기준 basis=screen. 럼피스킨은 제2종이라 게이지 대상 아님(lumpy 문구만 갱신).
- recent(최근 발생)는 fetch_kahis.py 가 KAHIS 전 쪽에서 이미 채웠다(리 주소·농장명 제외). **recent 는 고치지 말고 그대로 둔다.** 너는 게이지(fmd·ai·asf)·lumpy·asof·asofTime 만 갱신한다.
- asof=오늘 날짜(YYYY-MM-DD), asofTime=현재 시각(HH:MM, KST). 기존 JSON 구조·키를 그대로 유지.
- 자료를 읽을 수 없거나 확신이 없는 항목은 기존 값을 유지한다(추측 금지). 전부 못 읽으면 파일을 건드리지 않는다.
- 끝나면 python3 test_kosis.py --disease-only 로 질병 현황 검사가 통과하는지 확인한다.
- 커밋·푸시는 하지 않는다(스크립트가 한다). zl*.env 는 열지 않는다.
