"""KOSIS 가축동향조사(분기) 한우 자료 수집.

받는 표 (통계청/국가데이터처 orgId=101, 분기 자료 · 3/6/9/12월 1일 기준)
  DT_1EO251  축종별 시군구별 농장수 및 마릿수   → data/kosis_hanwoo.csv  (한우 농장수 T01, 마릿수 T02)
  DT_1EO252  한육우 시군구/연령/성별 마릿수      → data/kosis_age.csv     (성별 합계의 합계 T01, 1세미만 T02)
  DT_1EO221  한우 시도/사육규모별 농장수·마릿수  → data/kosis_scale.csv   (규모 구간 4개 + 합계)

실행:  python fetch_kosis.py           전체(2021년 1분기~최신) 받아 저장
       python fetch_kosis.py --test    1개 분기만 받아 구조만 확인 (저장 안 함)
인증키: 같은 폴더 zl3.env 의 KOSIS_API_KEY (코드·출력에 키를 쓰지 않습니다. 오류는 종류만 출력).
KOSIS 는 한 번에 4만 셀까지라 표마다 항목을 한우 위주로 줄여서 받습니다.
"""
import csv
import datetime
import logging
import sys
import time
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
ENV = BASE / "zl3.env"
URL = "https://kosis.kr/openapi/Param/statisticsParameterData.do"
START = "202101"          # 표가 제공하는 가장 이른 분기

# (표 ID, 항목, 2차 분류, 저장 파일)
TABLES = {
    "hanwoo": ("DT_1EO251", "T01+T02+", "", "kosis_hanwoo.csv"),
    "age": ("DT_1EO252", "T01+T02+", "0", "kosis_age.csv"),          # 2차 분류 0 = 성별 합계
    "scale": ("DT_1EO221", "T01+T02+", "ALL", "kosis_scale.csv"),
}
COLS = ["PRD_DE", "C1", "C1_NM", "C2", "C2_NM", "ITM_ID", "ITM_NM", "DT"]
log = logging.getLogger("kosis")


def load_key():
    if not ENV.exists():
        sys.exit(f"[오류] {ENV.name} 파일이 없습니다. KOSIS_API_KEY=키 한 줄을 넣어 두세요.")
    for line in ENV.read_text(encoding="utf-8-sig").splitlines():
        if line.strip().startswith("KOSIS_API_KEY="):
            v = line.split("=", 1)[1].strip().strip('"\'')
            if v:
                return v
    sys.exit(f"[오류] {ENV.name} 에서 KOSIS_API_KEY 를 찾지 못했습니다.")


def end_period(today=None):
    today = today or datetime.date.today()
    return f"{today.year}04"      # 아직 안 나온 분기는 응답에 없을 뿐이라 안전


def fetch_table(key, tbl, itm, l2, start=START, end=None, latest_only=False, retries=3):
    """한 표를 받아 행(dict) 목록으로 돌려줍니다. 실패하면 RuntimeError(종류만)."""
    params = dict(method="getList", apiKey=key, itmId=itm, objL1="ALL", objL2=l2, format="json",
                  jsonVD="Y", prdSe="Q", orgId="101", tblId=tbl)
    if latest_only:
        params["newEstPrdCnt"] = 1
    else:
        params.update(startPrdDe=start, endPrdDe=end or end_period())
    last = "알 수 없음"
    for attempt in range(1, retries + 1):
        try:
            res = requests.get(URL, params=params, timeout=120)
            res.raise_for_status()
            data = res.json()
        except Exception as exc:          # URL(키)이 섞이지 않게 종류만 기록
            last = type(exc).__name__
            log.warning("%s 시도 %d/%d 실패(%s)", tbl, attempt, retries, last)
            time.sleep(2 * attempt)
            continue
        if isinstance(data, dict):        # KOSIS 오류 응답 {"err":"20","errMsg":"..."}
            raise RuntimeError(f"{tbl}: KOSIS 오류 {data.get('err')} {data.get('errMsg', '')[:80]}")
        if not data:
            raise RuntimeError(f"{tbl}: 빈 응답")
        return data
    raise RuntimeError(f"{tbl}: 받지 못함({last})")


def clean(rows):
    out = []
    for r in rows:
        dt = (r.get("DT") or "").strip()
        out.append({**{c: (r.get(c) or "") for c in COLS[:-1]}, "DT": "" if dt in ("-", "") else dt})
    return out


def save(rows, path):
    DATA.mkdir(exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    key = load_key()
    test = "--test" in argv
    results = {}
    for name, (tbl, itm, l2, fname) in TABLES.items():
        try:
            rows = clean(fetch_table(key, tbl, itm, l2, latest_only=test))
        except RuntimeError as e:
            if test:
                raise SystemExit(f"[오류] {e}")
            if (DATA / fname).exists():
                log.warning("%s — 이전에 받아 둔 %s 를 사용합니다", e, fname)
                continue
            raise SystemExit(f"[오류] {e}")
        periods = sorted({r["PRD_DE"] for r in rows})
        log.info("%s %s: %d행, 분기 %d개 (%s~%s), 지역 %d곳, 값 있음 %d행",
                 name, tbl, len(rows), len(periods), periods[0], periods[-1],
                 len({r["C1"] for r in rows}), sum(1 for r in rows if r["DT"]))
        results[name] = rows
        if not test:
            save(rows, DATA / fname)
    if test:
        print("[시험 모드] 저장하지 않았습니다. 예시 한 행:", {k: v for k, v in results["hanwoo"][0].items() if k != "ITM_NM"})
    return results


if __name__ == "__main__":
    main()
