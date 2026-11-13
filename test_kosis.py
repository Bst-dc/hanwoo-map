"""KOSIS 한우 자료 연결 점검 (python test_kosis.py). 실패하면 어떤 가정이 깨졌는지 메시지로 알려 줍니다."""
import json
import sys

import update_map as um

sys.stdout.reconfigure(encoding="utf-8")


def row(q, c1, nm, itm, dt, c2=""):
    return {"PRD_DE": q, "C1": c1, "C1_NM": nm, "C2": c2, "C2_NM": "", "ITM_ID": itm, "ITM_NM": "", "DT": dt}


def test_synthetic():
    """극소수 시험: 동명 지역·구 있는 시·광역시를 손으로 만든 4개 지역으로 확인."""
    geo = {"feats": [
        {"id": "32100", "sidoFull": "강원도", "name": "고성군"}, {"id": "38100", "sidoFull": "경상남도", "name": "고성군"},
        {"id": "33041", "sidoFull": "충청북도", "name": "청주시상당구"}, {"id": "33042", "sidoFull": "충청북도", "name": "청주시서원구"},
        {"id": "21010", "sidoFull": "부산광역시", "name": "중구"}, {"id": "21020", "sidoFull": "부산광역시", "name": "동구"}]}
    hw = []
    for q, v in (("202503", "100"), ("202603", "90")):
        hw += [row(q, "32600", "고성군", "T02", v), row(q, "38540", "고성군", "T02", str(int(v) * 2)),
               row(q, "33040", "청주시", "T02", "50"), row(q, "21", "부산광역시", "T02", "7"), row(q, "00", "전국", "T02", "999")]
        hw += [row(q, c, n, "T01", "1") for c, n in (("32600", "고성군"), ("38540", "고성군"), ("33040", "청주시"), ("21", "부산광역시"))]
    quarters, out, scale, rep = um.kosis_units(geo, hw, [], [])
    assert quarters == ["202503", "202603"]
    assert out["32100"]["hw"] == 90 and out["38100"]["hw"] == 180, "고성군 두 곳이 시도로 구분되어야 함"
    assert out["32100"]["hwp"] == 100, "전년 동기(202503) 값이 hwp"
    assert out["33041"]["hw"] == out["33042"]["hw"] == 50 and out["33041"]["hs"] == 50 and out["33042"]["hs"] == 0, "구 없는 시: 대표 구 하나만 합계"
    assert out["21010"]["kg"] == "부산광역시" and out["21010"]["hs"] + out["21020"]["hs"] == 7
    assert rep["unlinked"] == []


def test_real_data():
    geo = json.loads(um.GEO.read_text(encoding="utf-8"))
    rows = [um.read_csv(um.KOSIS_FILES[k]) for k in ("hanwoo", "age", "scale")]
    quarters, out, scale, rep = um.kosis_units(geo, *rows)
    assert len(quarters) >= 20 and quarters == sorted(quarters), "분기가 시간순으로 20개 이상"
    assert all(len(v["kh"]) == len(quarters) for v in out.values())
    total = sum(v["hs"] for v in out.values())
    gap = abs(rep["national"] - total) / rep["national"]
    assert gap < 0.03, f"지도 합계와 KOSIS 전국 합계 차이가 3% 이상: {gap:.1%}"
    gs = [g for g in geo["feats"] if g["name"] == "고성군"]
    assert len(gs) == 2 and out[gs[0]["id"]]["hw"] != out[gs[1]["id"]]["hw"], "고성군 두 곳의 값이 달라야 함"
    cj = [v for k, v in out.items() if k.startswith("3304")]
    assert len(cj) == 4 and sum(v["kr"] for v in cj) == 1, "청주시 4개 구는 같은 값, 대표 1곳"
    assert "00" in scale and all(len(b["h"]) == len(quarters) for b in scale["00"])
    sizes = sum((scale["00"][i]["h"][-1] or 0) for i in range(4))
    assert abs(sizes - rep["national"]) / rep["national"] < 0.01, "규모 구간 합이 전국 두수와 같아야 함"
    print(f"  전국 {rep['national']:,}두 · 지도 합계 {total:,}두({gap:.2%}) · 연결 {rep['linked']}조각 · 미연결 {[u[1] for u in rep['unlinked']]}")


def test_nier_synthetic():
    """극소수 시험: 신 시도명·군위군(대구로 적힘)·시 지역 법정동이 어떻게 이어지는지."""
    geo = {"feats": [{"id": "32100", "sidoFull": "강원도", "name": "춘천시", "sido": "강원"},
                     {"id": "37100", "sidoFull": "경상북도", "name": "군위군", "sido": "경북"}], "emds": {}}
    rows = [{"YEAR": "2024", "CITYNM": "강원특별자치도", "CITICOUNGUNM": "춘천시", "ADIVIDOUNGNM": "동면", "HEADS": "10"},
            {"YEAR": "2024", "CITYNM": "대구광역시", "CITICOUNGUNM": "군위군", "ADIVIDOUNGNM": "소보면", "HEADS": "7"},
            {"YEAR": "2024", "CITYNM": "경기도", "CITICOUNGUNM": "없는시", "ADIVIDOUNGNM": "가동", "HEADS": "3"}]
    year, heads, lost = um.nier_units(rows, geo)
    assert year == "2024" and heads[("강원도", "춘천시", "동면")] == 10, "신 시도명이 옛 이름으로"
    assert heads[("경상북도", "군위군", "소보면")] == 7, "대구로 적힌 군위군은 경북 군위군으로"
    assert lost == 3, "지도에 없는 시군구는 lost 로 집계"


def test_nier_real():
    geo = json.loads(um.GEO.read_text(encoding="utf-8"))
    year, heads, lost = um.nier_units(um.read_csv(um.NIER_RAW), geo)
    total = sum(heads.values()) + lost
    assert lost == 0, f"시군구도 못 이은 두수 {lost:,}"
    emd_keys = {(g["sidoFull"], g["name"].replace(" ", ""), n) for g in geo["feats"] for n, _d in geo["emds"].get(g["id"], [])}
    matched = sum(v for k, v in heads.items() if k in emd_keys)
    assert matched / total > 0.9, f"읍면동 연결 {matched / total:.1%} (90% 이상이어야 함)"
    assert 3_000_000 < total < 4_000_000, f"전국 합계가 이상함: {total:,}"
    print(f"  {year}년 {total:,}두 · 읍면동 연결 {matched / total:.1%}")


def test_disease_status():
    """질병 현황 요약: 구조·단계 범위·개인정보(농장명) 없음."""
    d = json.loads(um.DISEASE.read_text(encoding="utf-8"))
    assert d["asof"] and len(d["gauges"]) == 3
    assert all(g["level"] in (1, 2, 3) and g["basis"] in ("official", "screen") for g in d["gauges"])
    assert d["recent"] and all({"d", "dis", "sp", "loc"} == set(r) for r in d["recent"]), "최근 발생은 날짜·질병·축종·시군만"
    assert [r["d"] for r in d["recent"]] == sorted((r["d"] for r in d["recent"]), reverse=True), "최신순"
    assert d["sources"] and all(s["url"].startswith("https://") for s in d["sources"])


if __name__ == "__main__":
    for fn in (test_synthetic, test_real_data, test_nier_synthetic, test_nier_real, test_disease_status):
        fn()
        print("통과:", fn.__name__)
