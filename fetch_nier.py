"""국립환경과학원 축산계 정보제공서비스에서 읍면동별 한우 사육두수를 받아 data/nier_hanwoo.csv 로 저장합니다.

- 공공데이터포털 15057699 (apis.data.go.kr/1480523/StobrService/getStobrInfo), 가축분뇨 배출시설 신고 기반 환경 조사.
- 인증키: zl2.env 의 DATA_GO_KR_KEY (코드·출력에 키를 쓰지 않고, 오류는 종류만 출력).
- 가장 최근에 자료가 있는 연도를 자동으로 찾습니다(2026 → 2022). 한우("한우(소)")만 읍면동별로 합쳐 저장합니다.
  농가수는 같은 농가가 여러 줄로 나뉘어 들어 있어 믿기 어려워 두수만 씁니다.

실행:  python fetch_nier.py           (--test: 연도 확인만, 저장 안 함)
"""
import csv
import datetime
import logging
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
ENV = BASE / "zl2.env"
OUT = DATA / "nier_hanwoo.csv"
URL = "https://apis.data.go.kr/1480523/StobrService/getStobrInfo"
PAGE = 1000
log = logging.getLogger("nier")


def load_key():
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8-sig").splitlines():
            if line.strip().startswith("DATA_GO_KR_KEY="):
                v = line.split("=", 1)[1].strip().strip('"\'')
                if v:
                    return v
    sys.exit(f"[오류] {ENV.name} 에서 DATA_GO_KR_KEY 를 찾지 못했습니다.")


def call(key, page, rows, year, retries=3):
    last = "알 수 없음"
    for attempt in range(1, retries + 1):
        try:
            res = requests.get(URL, params={"serviceKey": key, "resultType": "json", "pageNo": page, "numOfRows": rows,
                                            "startYear": year, "endYear": year}, timeout=120)
            res.raise_for_status()
            body = res.json()["getStobrInfo"]
            if body.get("header", {}).get("code") not in (None, "00"):
                raise RuntimeError(f"API 응답 {body['header'].get('code')}")
            return body
        except Exception as exc:         # URL(키)이 섞이지 않게 종류만 기록
            last = type(exc).__name__
            log.warning("연도 %s 쪽 %d 시도 %d/%d 실패(%s)", year, page, attempt, retries, last)
            time.sleep(2 * attempt)
    raise RuntimeError(f"받지 못함({last})")


def latest_year(key, today=None):
    today = today or datetime.date.today()
    for y in range(today.year, today.year - 6, -1):
        if call(key, 1, 1, y).get("totalCount", 0) > 0:
            return y
    raise RuntimeError("최근 6년 안에 자료가 없습니다")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    key = load_key()
    try:
        year = latest_year(key)
        log.info("자료가 있는 가장 최근 연도: %d", year)
        if "--test" in argv:
            print("[시험 모드] 저장하지 않았습니다.")
            return year
        heads, rows_n, page, total = defaultdict(int), 0, 1, None
        while True:
            body = call(key, page, PAGE, year)
            total = body["totalCount"]
            for r in body.get("item") or []:
                rows_n += 1
                if r.get("LSTOCKKINDNM") == "한우(소)":
                    heads[(r["CITYNM"], r.get("CITICOUNGUNM") or "", r.get("ADIVIDOUNGNM") or "")] += r.get("BREECNT") or 0
            if page % 10 == 0:
                log.info("%d/%d행", rows_n, total)
            if rows_n >= total or not body.get("item"):
                break
            page += 1
    except RuntimeError as e:
        if OUT.exists():
            log.warning("%s — 이전에 받아 둔 %s 를 사용합니다", e, OUT.name)
            return None
        raise SystemExit(f"[오류] {e}")
    if rows_n < total:
        raise SystemExit(f"[오류] 받은 행 {rows_n}/{total} — 일부만 받아 저장하지 않았습니다")
    DATA.mkdir(exist_ok=True)
    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["YEAR", "CITYNM", "CITICOUNGUNM", "ADIVIDOUNGNM", "HEADS"])
        for (c, s, e), n in sorted(heads.items()):
            w.writerow([year, c, s, e, n])
    log.info("완료: %d년, 전체 %d행 중 한우 읍면동 %d곳, 합계 %s두", year, rows_n, len(heads), f"{sum(heads.values()):,}")
    return year


if __name__ == "__main__":
    main()
