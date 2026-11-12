"""같은 서버의 다른 Grid 데이터셋을 받아 data/ 에 저장하고, 항목별 합계를 출력합니다.

fetch_data.py 와 같은 폴더에 두고 실행:
    python fetch_head.py Grid_20220823000000000638_1     # 운영상태별 농장 수
    python fetch_head.py Grid_20220823000000000635_1     # 질병·축종별 자료
(번호를 생략하면 ...635_1)

- 인증키는 zl.env 에서 읽습니다 (fetch_data.py 의 load_key 사용).
- data/<데이터셋번호>.csv 로 저장합니다.
- 지역 항목을 뺀 나머지 구분값(예: 운영상태, 질병, 축종)별 행 수와 FARM_CO 합계를 출력합니다.
"""
import csv
import sys
import time
from collections import defaultdict

import fetch_data as fd

DEFAULT_SERVICE = "Grid_20220823000000000635_1"
SKIP = {"ROW_NUM", "CTPRVN_NM", "SIGUNGU_NM", "EMD_NM", "FARM_CO", "INDUTY_CODE"}


def main():
    fd.SERVICE = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SERVICE
    key = fd.load_key()
    fd.DATA_DIR.mkdir(exist_ok=True)
    print(f"데이터셋: {fd.SERVICE}")

    code, message, total, rows = fd.fetch_page(key, 1, fd.PAGE_SIZE)
    if not code.startswith("INFO-000"):
        sys.exit(f"[오류] API 응답: {code} {message}")
    print(f"전체 {total:,}건 중 {len(rows):,}건 수신")

    all_rows = list(rows)
    start = fd.PAGE_SIZE + 1
    while start <= total:
        end = min(start + fd.PAGE_SIZE - 1, total)
        code, message, _, rows = fd.fetch_page(key, start, end)
        if not code.startswith("INFO-000"):
            sys.exit(f"[오류] API 응답: {code} {message}")
        all_rows.extend(rows)
        print(f"{start:,}~{end:,} 수신 (누적 {len(all_rows):,}건)")
        start = end + 1
        time.sleep(0.3)

    fields = list(all_rows[0].keys())
    out = fd.DATA_DIR / f"{fd.SERVICE}.csv"
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(all_rows)

    group_fields = [c for c in fields if c not in SKIP]
    agg = defaultdict(lambda: [0, 0])
    for r in all_rows:
        try:
            n = int(r.get("FARM_CO", "0") or 0)
        except ValueError:
            n = 0
        a = agg[tuple(r.get(c, "") for c in group_fields)]
        a[0] += 1
        a[1] += n

    print(f"\n저장 완료: {out}")
    print(f"\n[{' / '.join(group_fields)} / 행 수 / FARM_CO 합계]")
    for k, (cnt, s) in sorted(agg.items()):
        print(" / ".join(k) + f" / {cnt:,} / {s:,}")


if __name__ == "__main__":
    main()
