"""사육지도 갱신: API에서 최신 자료를 받아 hanwoo_map.html 을 다시 만듭니다.

실행:   python update_map.py        (또는 update_map.bat 더블클릭)
옵션:   --offline   API 호출 없이, 이미 받아 둔 data/ 의 자료로만 지도를 다시 만듭니다.

받는 자료
  1) 지역별 농장 통계   Grid_20220824000000000642_1  (농장 수)
  2) 구제역 대상 가축   Grid_20220823000000000635_1  (소 사육 두수)  - 받지 못하면 두수 없이 갱신
  3) 시군별 한우 사육규모 (공공데이터포털 15147310, 연 1회) - 한우만의 호수·두수. 받지 못하면 없이 갱신

필요한 파일(같은 폴더): fetch_data.py, fetch_hanwoo.py, zl.env, zl2.env, map_template.html, map_geo.json
선택: data_info.txt 에 "기준월=2026-09" 처럼 적으면 지도에 자료 기준월이 표시됩니다.
받은 자료는 data/archive/ 에 날짜별로 보관됩니다.
"""
import csv
import datetime
import json
import re
import shutil
import sys
import time
from collections import defaultdict
from pathlib import Path

import fetch_data as fd

BASE = Path(__file__).resolve().parent
DATA_DIR = BASE / "data"
ARCHIVE = DATA_DIR / "archive"
RAW = DATA_DIR / "farms_raw.csv"
HEAD_SERVICE = "Grid_20220823000000000635_1"
HEAD_RAW = DATA_DIR / f"{HEAD_SERVICE}.csv"
HW_RAW = DATA_DIR / "hanwoo_scale.csv"   # 시군별 한우 사육규모 (공공데이터포털 15147310)
GEO = BASE / "map_geo.json"
TEMPLATE = BASE / "map_template.html"
OUT = BASE / "hanwoo_map.html"
INFO = BASE / "data_info.txt"


def read_asof():
    """data_info.txt 의 '기준월=2026-09' 를 읽어 '2026년 9월' 로 돌려줍니다 (없으면 None)."""
    if not INFO.exists():
        return None
    for line in INFO.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.strip() == "기준월":
            m = re.search(r"(\d{4})\D+(\d{1,2})", value)
            if m:
                return f"{m.group(1)}년 {int(m.group(2))}월"
    return None


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def to_int(v):
    try:
        return int(v or 0)
    except ValueError:
        return 0


def species_sum(rows, species="소"):
    return sum(to_int(r.get("FARM_CO")) for r in rows if r.get("LVSTCK_NM") == species)


def fetch_service(service, out_path):
    """다른 Grid 데이터셋 전체를 받아 CSV 로 저장. 실패하면 False (프로그램은 계속 진행)."""
    key = fd.load_key()
    old = fd.SERVICE
    fd.SERVICE = service
    try:
        code, message, total, rows = fd.fetch_page(key, 1, fd.PAGE_SIZE)
        if not code.startswith("INFO-000"):
            print(f"[경고] {service}: API 응답 {code} {message}")
            return False
        all_rows = list(rows)
        start = fd.PAGE_SIZE + 1
        while start <= total:
            end = min(start + fd.PAGE_SIZE - 1, total)
            code, message, _, rows = fd.fetch_page(key, start, end)
            if not code.startswith("INFO-000"):
                print(f"[경고] {service}: API 응답 {code} {message}")
                return False
            all_rows.extend(rows)
            start = end + 1
            time.sleep(0.3)
        with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
            w.writeheader()
            w.writerows(all_rows)
        print(f"{service}: {len(all_rows):,}건 저장")
        return True
    except SystemExit as e:
        print(f"[경고] {service}: {e}")
        return False
    finally:
        fd.SERVICE = old


def hanwoo_units(hw_rows, geo):
    """시군별 한우 사육규모 자료를 지도의 시군구 조각에 연결합니다.

    이 자료는 광역시·일부 시(고양·용인·청주 등)를 구 없이 하나로 집계하므로,
    그런 경우 소속 구 조각에 같은 값을 보여 주고 합계에는 한 번만 넣습니다.
    반환: (year, {feat id: 정보}, 연결 못 한 행 목록)
    """
    years = sorted({r.get("년도") for r in hw_rows}, key=lambda y: str(y))
    year = years[-1]
    prev = years[-2] if len(years) > 1 else None
    by_key = defaultdict(dict)
    for r in hw_rows:
        by_key[(r["시도"], r["시군"].replace(" ", ""))][r["년도"]] = r

    sido_feats = defaultdict(list)
    for g in geo["feats"]:
        sido_feats[g["sido"][:2]].append(g)

    out, unlinked = {}, []
    bins = [("100두 이상", "100두 이상"), ("50~99두", "100두-50두 이상"), ("30~49두", "50두-30두 이상"),
            ("7~29두", "30두-7두 이상"), ("1~6두", "7두-0두 이상")]

    def put(members, yrs, group):
        cur, p = yrs[year], (yrs.get(prev) if prev else None)
        hb = [[lab, to_int(cur.get(f"{k}(호수)")), to_int(cur.get(f"{k}(두수)"))] for lab, k in bins]
        for i, g in enumerate(members):
            out[g["id"]] = {
                "hw": to_int(cur.get("전체두수")), "hwf": to_int(cur.get("전체호수")),
                "hwp": to_int(p.get("전체두수")) if p else 0,
                "hs": to_int(cur.get("전체두수")) if i == 0 else 0,
                "hfs": to_int(cur.get("전체호수")) if i == 0 else 0,
                "hps": (to_int(p.get("전체두수")) if p else 0) if i == 0 else 0,
                "hg": group, "hb": hb,
            }

    # 1차: 이름이 그대로 맞는 시군구
    pending = []
    for (sido, sg), yrs in by_key.items():
        if year not in yrs:
            continue
        members = [g for g in sido_feats.get(sido, []) if g["name"].replace(" ", "") == sg]
        if members:
            put(members, yrs, None)
        else:
            pending.append((sido, sg, yrs))
    # 2차: 구 없이 합쳐서 집계된 지역 (이미 따로 연결된 구는 제외)
    for sido, sg, yrs in pending:
        pool = sido_feats.get(sido, [])
        if sg == sido:                                       # 광역시·세종: 시도 전체
            full, group = pool, pool[0]["sidoFull"] if pool else sido
        else:                                                # 구가 있는 시
            full, group = [g for g in pool if g["name"].replace(" ", "").startswith(sg)], sg
        members = [g for g in full if g["id"] not in out]
        if not members:
            unlinked.append((sido, sg, to_int(yrs[year].get("전체두수"))))
            continue
        if len(members) < len(full):
            group += f"({', '.join(g['name'].replace(group, '').strip() for g in full if g['id'] in out)} 제외)"
        put(members, yrs, group)
    return year, out, unlinked


def build_data(rows, head_rows, geo, fetched, hw_rows=None):
    farms = defaultdict(lambda: defaultdict(int))   # (시도, 시군구, 읍면동) -> 축종 -> 농장 수
    sg_sp = defaultdict(lambda: defaultdict(int))   # (시도, 시군구) -> 축종 -> 농장 수
    emd_sp = defaultdict(list)                      # (시도, 시군구, 축종) -> [(읍면동, 수)]
    unknown = defaultdict(int)
    species_total = defaultdict(int)

    for r in rows:
        n = to_int(r.get("FARM_CO"))
        sido = r.get("CTPRVN_NM", "")
        sg = r.get("SIGUNGU_NM", "").replace(" ", "")
        sp = r.get("LVSTCK_NM", "")
        species_total[sp] += n
        if not sido:
            unknown[sp] += n
            continue
        if sido == "세종특별자치시":
            sg = "세종시"
        emd = r.get("EMD_NM", "")
        farms[(sido, sg, emd)][sp] += n
        sg_sp[(sido, sg)][sp] += n
        emd_sp[(sido, sg, sp)].append((emd, n))

    # 소 사육 두수 (구제역 대상 소)
    head_emd = defaultdict(int)                     # (시도, 시군구, 읍면동) -> 두수
    head_sg = defaultdict(int)                      # (시도, 시군구) -> 두수
    head_list = defaultdict(list)                   # (시도, 시군구) -> [(읍면동, 두수)]
    unknown_h = 0
    for r in head_rows or []:
        if r.get("LVSTCK_NM") != "소":
            continue
        n = to_int(r.get("FARM_CO"))
        sido = r.get("CTPRVN_NM", "")
        sg = r.get("SIGUNGU_NM", "").replace(" ", "")
        if not sido:
            unknown_h += n
            continue
        if sido == "세종특별자치시":
            sg = "세종시"
        emd = r.get("EMD_NM", "")
        head_emd[(sido, sg, emd)] += n
        head_sg[(sido, sg)] += n
        head_list[(sido, sg)].append((emd, n))
    has_head = bool(head_emd)

    key_of, code_of, feats = {}, {}, []
    for g in geo["feats"]:
        sido, sg = g["sidoFull"], g["name"].replace(" ", "")
        key_of[g["id"]] = (sido, sg)
        code_of[(sido, sg)] = g["id"]
        f = dict(sg_sp.get((sido, sg), {}))
        t = {sp: [[a, b] for a, b in sorted(emd_sp[(sido, sg, sp)], key=lambda x: -x[1])[:5]] for sp in f}
        top_h = [[a, b] for a, b in sorted(head_list.get((sido, sg), []), key=lambda x: -x[1])[:5] if b > 0]
        feats.append({"id": g["id"], "sido": g["sido"], "name": g["name"], "d": g["d"],
                      "f": f, "t": t, "h": head_sg.get((sido, sg), 0), "th": top_h})
    hw_year, hw_map, hw_unlinked = (None, {}, [])
    if hw_rows:
        hw_year, hw_map, hw_unlinked = hanwoo_units(hw_rows, geo)
        for ft in feats:
            ft.update(hw_map.get(ft["id"], {}))

    emds, used, used_h = {}, set(), set()
    for c5, lst in geo["emds"].items():
        sido, sg = key_of[c5]
        out = []
        for name, d in lst:
            key = (sido, sg, name)
            if key in farms:
                used.add(key)
            if key in head_emd:
                used_h.add(key)
            out.append([name, d, dict(farms.get(key, {})), head_emd.get(key, 0)])
        emds[c5] = out

    unmatched = defaultdict(lambda: defaultdict(int))
    for key, v in farms.items():
        if key in used:
            continue
        c5 = code_of.get((key[0], key[1]))
        if c5:
            for sp, n in v.items():
                unmatched[c5][sp] += n
    unmatched_h = defaultdict(int)
    for key, n in head_emd.items():
        if key in used_h:
            continue
        c5 = code_of.get((key[0], key[1]))
        if c5 and n > 0:
            unmatched_h[c5] += n

    return {
        "feats": feats,
        "borders": geo["borders"],
        "unknown": dict(unknown),
        "speciesTotal": dict(species_total),
        "emds": emds,
        "unmatched": {k: dict(v) for k, v in unmatched.items()},
        "hasHead": has_head,
        "hasHanwoo": bool(hw_map),
        "hwYear": hw_year,
        "hwUnlinked": hw_unlinked,
        "unknownH": unknown_h,
        "unmatchedH": dict(unmatched_h),
        "meta": {"fetched": fetched, "asof": read_asof()},
    }


def main():
    offline = "--offline" in sys.argv
    for p in (GEO, TEMPLATE):
        if not p.exists():
            sys.exit(f"[오류] {p.name} 파일이 없습니다. 이 스크립트와 같은 폴더에 두세요.")

    before = species_sum(read_csv(RAW)) if RAW.exists() else None

    if offline:
        if not RAW.exists():
            sys.exit("[오류] data/farms_raw.csv 가 없습니다. --offline 없이 실행해서 먼저 받아 주세요.")
        fetched = datetime.date.fromtimestamp(RAW.stat().st_mtime).isoformat()
        print(f"[오프라인] 기존 자료({fetched})로 지도를 다시 만듭니다.")
    else:
        fd.main()  # 농장 통계: API 에서 받아 data/ 에 저장 (실패하면 여기서 멈춤)
        fetched = datetime.date.today().isoformat()
        ARCHIVE.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(RAW, ARCHIVE / f"farms_raw_{fetched}.csv")
        print("\n사육 두수 자료를 받는 중...")
        if fetch_service(HEAD_SERVICE, HEAD_RAW):
            shutil.copyfile(HEAD_RAW, ARCHIVE / f"{HEAD_SERVICE}_{fetched}.csv")
        elif HEAD_RAW.exists():
            print("[경고] 두수 자료를 새로 받지 못해, 이전에 받아 둔 두수 자료를 사용합니다.")
        else:
            print("[경고] 두수 자료가 없어 농장 수만 표시합니다.")
        print("\n한우 사육규모 자료를 받는 중...")
        try:
            import fetch_hanwoo
            fetch_hanwoo.main()
            shutil.copyfile(HW_RAW, ARCHIVE / f"hanwoo_scale_{fetched}.csv")
        except SystemExit as e:
            print(f"[경고] 한우 사육규모 자료를 새로 받지 못했습니다: {e}")
            if HW_RAW.exists():
                print("       이전에 받아 둔 자료를 사용합니다.")

    rows = read_csv(RAW)
    head_rows = read_csv(HEAD_RAW) if HEAD_RAW.exists() else None
    geo = json.loads(GEO.read_text(encoding="utf-8"))
    hw_rows = read_csv(HW_RAW) if HW_RAW.exists() else None
    data = build_data(rows, head_rows, geo, fetched, hw_rows)

    html = TEMPLATE.read_text(encoding="utf-8").replace(
        "__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    OUT.write_text(html, encoding="utf-8")

    after = species_sum(rows)
    print(f"\n지도 갱신 완료: {OUT}")
    print(f"소 농장 수: {after:,}곳", end="")
    if before is not None and not offline:
        diff = after - before
        print(f" (이전 {before:,}곳, 변화 {diff:+,})" if diff else " (이전과 같음 - 아직 갱신되지 않았을 수 있습니다)")
    else:
        print()
    if data["hasHead"]:
        print(f"소 사육 두수: {species_sum(head_rows):,}두")
    if data["hasHanwoo"]:
        tot = sum(f.get("hs", 0) for f in data["feats"])
        print(f"한우 사육 두수({data['hwYear']}년 기준): {tot:,}두")
        for u in data["hwUnlinked"]:
            print(f"[알림] 지도와 연결하지 못한 한우 자료: {u[0]} {u[1]} {u[2]:,}두")
    print("브라우저에서 hanwoo_map.html 을 새로고침(Ctrl+F5)하세요.")


if __name__ == "__main__":
    main()
