"""시군별 한우 사육규모 현황(공공데이터포털 15147310) 받기.

실행:  python fetch_hanwoo.py
- 인증키는 zl2.env 의 DATA_GO_KR_KEY 에서만 읽습니다 (코드·화면에 키가 나오지 않습니다).
- data/hanwoo_scale.csv 로 저장합니다. (두 데이터셋: 20241231, 20260101 을 합칩니다)
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent
ENV_FILES = [BASE / "zl2.env", BASE / "datagokr.env"]
DATA_DIR = BASE / "data"
OUT = DATA_DIR / "hanwoo_scale.csv"
HOST = "https://api.odcloud.kr/api/15147310/v1"
DATASETS = {
    "20260101": "uddi:c156d26e-ee54-4a57-a5d1-a64120871f3b",
    "20241231": "uddi:ff263e38-947c-4fa3-827f-b8e0115ca984",
}
PER_PAGE = 1000


def load_key():
    for f in ENV_FILES:
        if not f.exists():
            continue
        for line in f.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line.startswith("DATA_GO_KR_KEY="):
                v = line.split("=", 1)[1].strip().strip('"').strip("'")
                if v:
                    return v
    sys.exit("[오류] zl2.env 에서 DATA_GO_KR_KEY=... 줄을 찾지 못했습니다.")


def get_all(key, uddi):
    rows, page = [], 1
    while True:
        try:
            r = requests.get(f"{HOST}/{uddi}", params={"serviceKey": key, "page": page, "perPage": PER_PAGE}, timeout=60)
        except Exception as e:  # 키가 메시지에 섞이지 않도록 종류만 표시
            sys.exit(f"[오류] 연결 실패 ({type(e).__name__}). 인터넷 연결을 확인하세요.")
        if r.status_code != 200:
            sys.exit(f"[오류] HTTP {r.status_code} - 인증키가 아직 승인되지 않았거나 잘못되었을 수 있습니다.")
        j = r.json()
        data = j.get("data", [])
        rows.extend(data)
        if len(rows) >= j.get("totalCount", 0) or not data:
            return rows
        page += 1


def main():
    key = load_key()
    DATA_DIR.mkdir(exist_ok=True)
    merged, seen = [], set()
    for tag, uddi in DATASETS.items():
        rows = get_all(key, uddi)
        print(f"{tag}: {len(rows):,}건")
        for r in rows:
            k = (r.get("시도"), r.get("시군"), r.get("년도"))
            if k in seen:
                continue
            seen.add(k)
            merged.append(r)
    if not merged:
        sys.exit("[오류] 받은 자료가 없습니다.")

    fields = list(merged[0].keys())
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(merged)
    print(f"\n저장 완료: {OUT}  (중복 제거 후 {len(merged):,}건)")

    by_year = defaultdict(lambda: [0, 0, 0])
    for r in merged:
        a = by_year[r.get("년도")]
        a[0] += 1
        a[1] += int(r.get("전체호수") or 0)
        a[2] += int(r.get("전체두수") or 0)
    print("\n[년도 / 시군 수 / 전체호수 / 전체두수]")
    for y, (n, h, d) in sorted(by_year.items(), key=lambda x: str(x[0])):
        print(f"{y} / {n:,} / {h:,} / {d:,}")
    print("\n품종 값:", sorted({r.get("품종", "") for r in merged}))
    print("시도 값:", sorted({r.get("시도", "") for r in merged}))


if __name__ == "__main__":
    main()
