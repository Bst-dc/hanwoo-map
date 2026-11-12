"""지역별 농장 통계 API(Grid_20220824000000000642_1) 전체 다운로드.

- 인증키는 같은 폴더의 zl.env 파일에서만 읽습니다 (코드에 키가 없습니다).
- 결과는 data/ 폴더에 저장됩니다.
    data/farms_raw.csv        : 읍면동 단위 원본 전체
    data/farms_raw.json       : 같은 내용 (JSON)
    data/farms_sigungu.csv    : 시도/시군구/축종별 농장수 합계 (지도용)

실행:  python fetch_data.py
"""
import csv
import json
import sys
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / "zl.env"
DATA_DIR = BASE_DIR / "data"

HOST = "http://211.237.50.150:7080/openapi"
SERVICE = "Grid_20220824000000000642_1"
PAGE_SIZE = 1000  # 한 번에 받을 수 있는 최대 건수


def load_key():
    """zl.env 에서 인증키를 읽는다. 변수 이름에 KEY 가 들어간 항목을 우선 사용."""
    if not ENV_FILE.exists():
        sys.exit(f"[오류] {ENV_FILE.name} 파일을 찾을 수 없습니다. 이 스크립트와 같은 폴더에 두세요.")

    values = {}
    for line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        if value:
            values[name.strip()] = value

    if not values:
        sys.exit(f"[오류] {ENV_FILE.name} 안에 '이름=값' 형태의 줄이 없습니다.")

    for name in values:
        if "KEY" in name.upper():
            return values[name]
    # 비밀번호 등이 키로 잘못 전송되는 일을 막기 위해, KEY 가 들어간 이름이 없으면 중단
    sys.exit(
        f"[오류] {ENV_FILE.name} 에 이름에 KEY 가 들어간 항목이 없습니다. "
        f"현재 변수 이름: {', '.join(values)}. 인증키 항목 이름을 API_KEY 로 바꿔 주세요."
    )


def parse_xml(text):
    root = ET.fromstring(text)

    def find_text(tag):
        for el in root.iter():
            if el.tag.lower() == tag:
                return (el.text or "").strip()
        return ""

    code = find_text("code")
    message = find_text("message")
    total = find_text("totalcnt")
    rows = []
    for row in root.iter("row"):
        rows.append({child.tag: (child.text or "").strip() for child in row})
    return code, message, int(total) if total.isdigit() else 0, rows


def fetch_page(key, start, end, retries=3):
    url = f"{HOST}/{key}/xml/{SERVICE}/{start}/{end}"
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            res = requests.get(url, timeout=60)
            res.raise_for_status()
            return parse_xml(res.content.decode("utf-8", errors="replace"))
        except Exception as exc:  # 오류 메시지에 URL(키)이 섞이지 않도록 종류만 기록
            last_error = type(exc).__name__
            time.sleep(2 * attempt)
    sys.exit(f"[오류] {start}~{end}번 데이터를 받지 못했습니다 ({last_error}). 인터넷 연결과 인증키를 확인하세요.")


def main():
    key = load_key()
    DATA_DIR.mkdir(exist_ok=True)

    code, message, total, rows = fetch_page(key, 1, PAGE_SIZE)
    if not code.startswith("INFO-000"):
        sys.exit(f"[오류] API 응답: {code} {message}")
    print(f"전체 {total:,}건 중 {len(rows):,}건 수신")

    all_rows = list(rows)
    start = PAGE_SIZE + 1
    while start <= total:
        end = min(start + PAGE_SIZE - 1, total)
        code, message, _, rows = fetch_page(key, start, end)
        if not code.startswith("INFO-000"):
            sys.exit(f"[오류] API 응답: {code} {message}")
        all_rows.extend(rows)
        print(f"{start:,}~{end:,} 수신 (누적 {len(all_rows):,}건)")
        start = end + 1
        time.sleep(0.3)

    # 원본 저장
    fields = list(all_rows[0].keys())
    with open(DATA_DIR / "farms_raw.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(all_rows)
    with open(DATA_DIR / "farms_raw.json", "w", encoding="utf-8") as f:
        json.dump(all_rows, f, ensure_ascii=False)

    # 시군구 단위 집계
    agg = defaultdict(int)
    for r in all_rows:
        try:
            n = int(r.get("FARM_CO", "0") or 0)
        except ValueError:
            n = 0
        agg[(r.get("CTPRVN_NM", ""), r.get("SIGUNGU_NM", ""), r.get("LVSTCK_NM", ""))] += n

    with open(DATA_DIR / "farms_sigungu.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["CTPRVN_NM", "SIGUNGU_NM", "LVSTCK_NM", "FARM_CO"])
        for (sido, sigungu, lvstck), n in sorted(agg.items()):
            writer.writerow([sido, sigungu, lvstck, n])

    kinds = sorted({k[2] for k in agg})
    print(f"\n저장 완료: {DATA_DIR}")
    print(f"읍면동 {len(all_rows):,}건, 시군구×축종 {len(agg):,}건")
    print("축종 목록:", ", ".join(kinds))


if __name__ == "__main__":
    main()
