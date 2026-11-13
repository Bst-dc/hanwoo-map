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
NIER_RAW = DATA_DIR / "nier_hanwoo.csv"   # 읍면동별 한우 두수 (국립환경과학원 축산계, 공공데이터포털 15057699)
KOSIS_FILES = {k: DATA_DIR / f"kosis_{k}.csv" for k in ("hanwoo", "age", "scale")}   # KOSIS 가축동향조사(분기)
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


KOSIS_SIDO_GROUP = {"21", "22", "23", "24", "25", "26", "29"}   # 구 없이 시도 하나로 집계되는 광역시·세종
OB_RATIO, OB_MIN_HEADS = (0.8, 1.25), 1000      # 15147310 / KOSIS 두수 비가 이 범위를 벗어나면 규모별 값을 숨김
KOSIS_BINS = ["20 미만", "20~50 미만", "50~100 미만", "100 이상"]


def _kv(v):
    return int(float(v)) if v not in ("", None) else None


def kosis_units(geo, hw_rows, age_rows, scale_rows):
    """KOSIS 가축동향조사(분기) 한우 자료를 지도의 시군구 조각에 연결합니다.

    지역 연결: KOSIS 시도 코드(앞 2자리)는 지도 경계와 같고, 시군 코드는 달라서 '시도 코드 + 시군 이름'으로 잇습니다
    (고성군처럼 이름이 같은 지역도 시도로 구분). 구 없이 집계된 곳(광역시·고양·청주 등)은 소속 구가 같은 값을 갖고
    대표 구(kr=1) 하나만 합계에 들어갑니다.
    반환: (quarters, {feat id: 필드}, 시도·전국 규모표, 연결 보고)
    """
    quarters = sorted({r["PRD_DE"] for r in hw_rows})
    qi = {q: i for i, q in enumerate(quarters)}
    names = {r["C1"]: r["C1_NM"] for r in sorted(hw_rows, key=lambda r: r["PRD_DE"])}

    def series(rows, itm):
        s = defaultdict(lambda: [None] * len(quarters))
        for r in rows:
            if r["ITM_ID"] == itm and r["PRD_DE"] in qi and r.get("C2", "") in ("", "0"):
                s[r["C1"]][qi[r["PRD_DE"]]] = _kv(r["DT"])
        return s

    heads, farms = series(hw_rows, "T02"), series(hw_rows, "T01")
    calf, tot = series(age_rows, "T02"), series(age_rows, "T01")
    by_pre = defaultdict(list)
    for g in geo["feats"]:
        by_pre[g["id"][:2]].append(g)
    last = len(quarters) - 1
    yoy = qi.get(f"{int(quarters[-1][:4]) - 1}{quarters[-1][4:]}")

    def at(arr, k):
        return (arr[k] or 0) if k is not None and k >= 0 else 0

    out, unlinked = {}, []
    for code in sorted(heads, key=lambda c: (len(c) != 5, c)):      # 시군(5자리)을 시도 행보다 먼저
        if code == "00" or not any(v is not None for v in heads[code]):
            continue
        pre, name = code[:2], names[code].replace(" ", "")
        pool = by_pre.get(pre, [])
        if len(code) == 2:
            if pre not in KOSIS_SIDO_GROUP:
                continue
            members, group = pool, (pool[0]["sidoFull"] if pool else None)
        else:
            members, group = [g for g in pool if g["name"].replace(" ", "") == name], None
            if not members:
                members = [g for g in pool if g["name"].replace(" ", "").startswith(name)]
                group = name if members else None
        members = [g for g in members if g["id"] not in out]
        if not members:
            unlinked.append((code, names[code], heads[code][last]))
            continue
        h, f = heads[code], farms.get(code, [None] * len(quarters))
        y, t2 = calf.get(code, [None] * len(quarters)), tot.get(code, [None] * len(quarters))
        for i, g in enumerate(members):
            rep_ = 1 if i == 0 else 0
            out[g["id"]] = {
                "kh": h, "kf": f, "ky": y, "kt": t2, "kg": group, "kr": rep_,
                "hw": at(h, last), "hwf": at(f, last), "hwp": at(h, yoy), "hwq": at(h, last - 1),
                "hs": at(h, last) * rep_, "hfs": at(f, last) * rep_, "hps": at(h, yoy) * rep_,
                "hqs": at(h, last - 1) * rep_, "hg": group,
            }

    scale = {}
    for r in scale_rows:
        if r["C2_NM"] in KOSIS_BINS and r["PRD_DE"] in qi:
            sc = scale.setdefault(r["C1"], [{"f": [None] * len(quarters), "h": [None] * len(quarters)} for _ in KOSIS_BINS])
            sc[KOSIS_BINS.index(r["C2_NM"])]["f" if r["ITM_ID"] == "T01" else "h"][qi[r["PRD_DE"]]] = _kv(r["DT"])
    report = {"national": (heads["00"][last] if "00" in heads else None), "unlinked": unlinked,
              "linked": len(out), "groupedFeats": sum(1 for v in out.values() if v["kg"])}
    return quarters, out, scale, report


def make_resolver(geo):
    """자료의 시군구 이름이 2018 경계에 없을 때(옛 행정구역) 경계 쪽 시군구로 바꿔 주는 함수를 만듭니다.

    - 폐지된 구: '부천시원미구' → '부천시' (경계 시군구 이름으로 시작하면 그쪽으로)
    - 통합된 군: '청원군 미원면' → 같은 시도 안에서 그 읍면동이 하나뿐인 시군구('청주시상당구')
    못 찾으면 원래 이름을 그대로 돌려줍니다 (지도에 안 나오는 자료로 남음).
    """
    keys = {(g["sidoFull"], g["name"].replace(" ", "")) for g in geo["feats"]}
    id_key = {g["id"]: (g["sidoFull"], g["name"].replace(" ", "")) for g in geo["feats"]}
    emd_home = defaultdict(set)                      # (시도, 읍면동) -> {시군구}
    for c5, lst in geo["emds"].items():
        sido, sg = id_key[c5]
        for name, _d in lst:
            emd_home[(sido, name)].add(sg)
    cache, moved = {}, defaultdict(int)

    def resolve(sido, sg, emd):
        if (sido, sg) in keys:
            return sg
        ck = (sido, sg, emd)
        if ck not in cache:
            new = sg
            pre = [k[1] for k in keys if k[0] == sido and sg.startswith(k[1])]
            homes = emd_home.get((sido, emd), set())
            if len(pre) == 1:
                new = pre[0]
            elif len(homes) == 1:
                new = next(iter(homes))
            cache[ck] = new
        if cache[ck] != sg:
            moved[f"{sido} {sg} → {cache[ck]}"] += 1
        return cache[ck]

    resolve.moved = moved
    return resolve


NIER_SIDO = {"강원특별자치도": "강원도", "전북특별자치도": "전라북도"}      # 지도 경계(2018)의 옛 시도 이름


def nier_units(rows, geo):
    """읍면동별 한우 두수(국립환경과학원)를 지도 경계의 (시도, 시군구, 읍면동) 키로 바꿉니다.

    시도 이름은 신 명칭을 옛 이름으로, 옛 행정구역(부천시소사구 등)은 make_resolver 로, 다른 시도로 적힌 시군구
    (대구광역시 군위군 → 경북)는 지도에서 이름이 하나뿐일 때 그 시도로 옮깁니다.
    반환: (year, {(시도, 시군구, 읍면동): 두수}, 시군구까지도 못 이은 두수)
    """
    resolve = make_resolver(geo)
    keys = {(g["sidoFull"], g["name"].replace(" ", "")) for g in geo["feats"]}
    by_sg = defaultdict(set)
    for sido, sg in keys:
        by_sg[sg].add(sido)
    heads, lost = defaultdict(int), 0
    for r in rows:
        sido = NIER_SIDO.get(r["CITYNM"], r["CITYNM"])
        sg = (r["CITICOUNGUNM"] or "").replace(" ", "")
        if sido == "세종특별자치시":
            sg = "세종시"
        sg = resolve(sido, sg, r["ADIVIDOUNGNM"])
        if (sido, sg) not in keys and len(by_sg.get(sg, ())) == 1:
            sido = next(iter(by_sg[sg]))
        n = to_int(r["HEADS"])
        if (sido, sg) not in keys:
            lost += n
            continue
        heads[(sido, sg, r["ADIVIDOUNGNM"])] += n
    return (rows[0]["YEAR"] if rows else None), dict(heads), lost


def build_data(rows, head_rows, geo, fetched, hw_rows=None, kosis=None, nier=None):
    resolve = make_resolver(geo)
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
        sg = resolve(sido, sg, emd)
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
        sg = resolve(sido, sg, emd)
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
    kq, k_scale, k_report = None, {}, None
    if kosis:
        # KOSIS 분기 자료가 한우의 주 자료. 15147310(연간)은 규모 5구간(hb)과 100두 이상 비중용 '참고'로 둔다
        kq, k_units, k_scale, k_report = kosis
        empty = {"hw": 0, "hwf": 0, "hwp": 0, "hwq": 0, "hs": 0, "hfs": 0, "hps": 0, "hqs": 0, "hg": None}
        for ft in feats:
            old = {k: ft.pop(k) for k in ("hw", "hwf", "hwp", "hs", "hfs", "hps", "hg") if k in ft}
            ft.update({"ohw": old.get("hw", 0), "ohwf": old.get("hwf", 0), "ohs": old.get("hs", 0),
                       "ohfs": old.get("hfs", 0), "ohg": old.get("hg")})
            ft.update(k_units.get(ft["id"], empty))
            # 15147310(규모 구간)이 KOSIS 와 크게 어긋나는 지역은 규모별 값을 숨긴다 (강원 등). 한우 1,000두 미만이거나
            # 두 자료의 묶음 단위가 다른 곳은 비교가 무의미해 그대로 둔다
            ratio = ft["ohw"] / ft["hw"] if ft["ohw"] > 0 and ft["hw"] > 0 else None
            checkable = ratio is not None and ft["hw"] >= OB_MIN_HEADS and ft.get("ohg") == ft.get("hg")
            ft["obOk"] = not (checkable and not OB_RATIO[0] <= ratio <= OB_RATIO[1])
            ft["obR"] = round(ratio, 2) if ratio is not None else None

    n_year, n_heads, n_lost = nier if nier else (None, {}, 0)
    emds, used, used_h, used_n = {}, set(), set(), set()
    for c5, lst in geo["emds"].items():
        sido, sg = key_of[c5]
        out = []
        for name, d in lst:
            key = (sido, sg, name)
            if key in farms:
                used.add(key)
            if key in head_emd:
                used_h.add(key)
            if key in n_heads:
                used_n.add(key)
            out.append([name, d, dict(farms.get(key, {})), head_emd.get(key, 0), n_heads.get(key, 0)])
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

    unmatched_n = defaultdict(int)
    for key, n in n_heads.items():
        if key not in used_n and n > 0 and code_of.get((key[0], key[1])):
            unmatched_n[code_of[(key[0], key[1])]] += n
    n_total = sum(n_heads.values()) + n_lost

    return {
        "hasEmdHw": bool(n_heads), "emdHwYear": n_year, "unmatchedN": dict(unmatched_n),
        "emdHwReport": {"total": n_total, "matched": sum(n_heads[k] for k in used_n), "lost": n_lost},
        "feats": feats,
        "borders": geo["borders"],
        "unknown": dict(unknown),
        "speciesTotal": dict(species_total),
        "emds": emds,
        "unmatched": {k: dict(v) for k, v in unmatched.items()},
        "hasHead": has_head,
        "hasHanwoo": bool(hw_map) or bool(kq),
        "kq": kq, "kScale": k_scale, "kReport": k_report,
        "hwYear": hw_year,
        "hwUnlinked": hw_unlinked,
        "unknownH": unknown_h,
        "unmatchedH": dict(unmatched_h),
        "oldNames": dict(resolve.moved),
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
        print("\nKOSIS 한우 분기 자료를 받는 중...")
        try:
            import fetch_kosis
            fetch_kosis.main([])
            for k, p in KOSIS_FILES.items():
                shutil.copyfile(p, ARCHIVE / f"kosis_{k}_{fetched}.csv")
        except SystemExit as e:
            print(f"[경고] KOSIS 분기 자료를 새로 받지 못했습니다: {e}")
            if KOSIS_FILES["hanwoo"].exists():
                print("       이전에 받아 둔 자료를 사용합니다.")
        print("\n읍면동별 한우 자료(국립환경과학원)를 받는 중...")
        try:
            import fetch_nier
            fetch_nier.main([])
            shutil.copyfile(NIER_RAW, ARCHIVE / f"nier_hanwoo_{fetched}.csv")
        except SystemExit as e:
            print(f"[경고] 읍면동 한우 자료를 새로 받지 못했습니다: {e}")
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
    kosis = None
    if all(p.exists() for p in KOSIS_FILES.values()):
        kosis = kosis_units(geo, *(read_csv(KOSIS_FILES[k]) for k in ("hanwoo", "age", "scale")))
    else:
        print("[경고] KOSIS 분기 자료(data/kosis_*.csv)가 없어 기존 연간 한우 자료만 표시합니다. fetch_kosis.py 를 먼저 실행하세요.")
    nier = nier_units(read_csv(NIER_RAW), geo) if NIER_RAW.exists() else None
    data = build_data(rows, head_rows, geo, fetched, hw_rows, kosis, nier)

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
    kr = data.get("kReport")
    if kr:
        sg = sum(f.get("hs", 0) for f in data["feats"])
        q = data["kq"][-1]
        print(f"KOSIS 한우 {q[:4]}년 {q[4:].lstrip('0')}분기: 지도 합계 {sg:,}두 / KOSIS 전국 {kr['national']:,}두 "
              f"(차이 {kr['national'] - sg:+,}두, {abs(kr['national'] - sg) / kr['national']:.1%}) · 연결 {kr['linked']}조각")
        for c, n, v in kr["unlinked"]:
            print(f"[알림] 지도와 연결하지 못한 KOSIS 지역: {n}({c}) {v or 0:,}두")
    hidden = [f for f in data["feats"] if f.get("obOk") is False]
    if hidden:
        by = defaultdict(int)
        for f in hidden:
            by[f["sido"]] += 1
        print(f"[알림] 규모별 자료(15147310)가 KOSIS와 크게 달라 숨긴 지역 {len(hidden)}곳: {dict(by)}")
    er = data.get("emdHwReport")
    if data["hasEmdHw"] and er["total"]:
        print(f"읍면동 한우({data['emdHwYear']}년, 환경과학원): 합계 {er['total']:,}두 중 읍면동에 연결 {er['matched'] / er['total']:.1%} "
              f"(나머지는 시군구 합계에만, 시군구도 못 이은 {er['lost']:,}두)")
    for k, cnt in sorted(data["oldNames"].items()):
        print(f"[알림] 옛 행정구역 이름 연결: {k} ({cnt}건)")
    print("브라우저에서 hanwoo_map.html 을 새로고침(Ctrl+F5)하세요.")


if __name__ == "__main__":
    main()
