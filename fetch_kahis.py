"""KAHIS 법정가축전염병 발생현황 → disease_status.json 의 recent (최근 30일, 전 쪽을 받아 묶음).

- 농장명·농장주·리 주소는 읽자마자 버리고 '시도·시군·읍면동'만 남긴다(개인정보 규칙).
- 같은 (날짜, 질병, 축종)은 한 줄로 묶고 시군·읍면동을 모은다.
- KAHIS 표에 없는 'H5형 AI 항원 확인'(농식품부 화면 기준) 줄은 기존 값을 30일 안에서 유지한다.
사용: python3 fetch_kahis.py [--dry]   (--dry: 파일을 쓰지 않고 요약만 출력)
"""
import datetime, html, json, logging, os, re, sys, time, urllib.parse, urllib.request
from zoneinfo import ZoneInfo
from collections import OrderedDict
from pathlib import Path

BASE = Path(__file__).parent
DISEASE = BASE / "disease_status.json"
URL = "https://home.kahis.go.kr/home/lkntscrinfo/selectLkntsOccrrncList.do"
DAYS = 30
log = logging.getLogger("kahis")

SIDO = {"서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천", "대전광역시": "대전",
        "울산광역시": "울산", "세종특별자치시": "세종", "경기도": "경기", "강원특별자치도": "강원", "강원도": "강원",
        "충청북도": "충북", "충청남도": "충남", "전북특별자치도": "전북", "전라북도": "전북", "전라남도": "전남광주",
        "광주광역시": "전남광주", "전남광주통합특별시": "전남광주", "경상북도": "경북", "경상남도": "경남", "제주특별자치도": "제주"}
DIS = {"럼피스킨병": "럼피스킨", "고병원성 조류인플루엔자": "고병원성 AI", "아프리카돼지열병": "아프리카돼지열병"}


def fetch_page(page, frm, to):
    body = urllib.parse.urlencode({"pageIndex": page, "turmGubun": "01", "occrFromDt": frm, "occrToDt": to,
                                   "dissCl": "", "lstkspCl": "", "legalIctsdGradSe": ""}).encode()
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(URL, body, {"User-Agent": "Mozilla/5.0"}), timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:              # URL이 섞이지 않게 예외 종류만 기록
            log.warning("쪽 %s 받기 실패(%s) %d/3", page, type(e).__name__, attempt + 1)
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"쪽 {page} 받기 3회 실패")


def parse_rows(s):
    """표의 (질병, 주소, 날짜, 축종) 만 뽑는다. 농장명(2번째 칸)은 버린다."""
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", s, re.S):
        c = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", x))).strip() for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if len(c) >= 6 and re.match(r"\d{4}-\d\d-\d\d", c[3]):
            m = re.search(r"\((\d{4}-\d\d-\d\d)\)", c[3])      # "발생일 (진단일)" → 진단일 사용(KAHIS 조회·정렬 기준)
            out.append((c[0], c[2], m.group(1) if m else c[3][:10], c[4]))
    return out


def place(addr):
    """주소 → (시도 약칭, 시군, '시군 읍면동' 또는 None). 리·번지는 버린다."""
    t = addr.split()
    if not t or t[0] not in SIDO:
        return None
    if len(t) < 2:                            # 시도만 있는 주소
        return SIDO[t[0]], SIDO[t[0]], None
    sido = SIDO[t[0]]
    if sido == "세종":                        # 시군구 없이 바로 읍면동
        emd = next((x for x in t[1:] if re.fullmatch(r"\S+[읍면동]", x)), None)
        return sido, "세종", (f"세종시 {emd}" if emd else None)
    sg = next((x for x in t[1:] if re.fullmatch(r"\S+[시군]", x)), None)
    if sg is None:                            # 광역시: 구·군
        sg = t[1]
    emd = next((x for x in t[2:] if re.fullmatch(r"\S+[읍면동]", x) and not x.endswith("리")), None)
    return sido, re.sub(r"[시군구]$", "", sg) if len(sg) > 2 else sg, (f"{sg} {emd}" if emd else None)


def group(rows):
    g = OrderedDict()
    for dis, addr, d, sp in rows:
        p = place(addr)
        if not p:                                 # 조용한 누락 방지: 하나라도 못 읽으면 중단
            raise SystemExit(f"[오류] 주소를 해석하지 못함(시도 '{addr.split()[0] if addr else ''}') — 파일을 바꾸지 않음")
        sido, sgs, emd = p
        k = (d, DIS.get(dis, dis), sp.split("-")[-1])
        e = g.setdefault(k, {"sg": OrderedDict(), "emd": []})
        e["sg"].setdefault(sido, [])
        if sgs not in e["sg"][sido]:
            e["sg"][sido].append(sgs)
        if emd and emd not in e["emd"]:
            e["emd"].append(emd)
    res = []
    for (d, dis, sp), e in g.items():
        loc = " · ".join(s if v == [s] else f"{s} {'·'.join(v)}" for s, v in e["sg"].items())
        r = {"d": d, "dis": dis, "sp": sp, "loc": loc}
        if e["emd"]:
            r["emd"] = e["emd"]
        res.append(r)
    return sorted(res, key=lambda r: r["d"], reverse=True)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    today = datetime.datetime.now(ZoneInfo("Asia/Seoul")).date()   # 서버 시간대와 무관하게 한국 날짜
    frm, to = (today - datetime.timedelta(days=DAYS)).isoformat(), today.isoformat()
    first = fetch_page(1, frm, to)
    m = re.search(r"전체 : ([\d,]+)건\((\d+)쪽/(\d+)쪽\)", first)
    if not m:
        raise SystemExit("[오류] 전체 건수를 못 찾음 — KAHIS 화면 구조가 바뀐 듯")
    total, pages = int(m.group(1).replace(",", "")), int(m.group(3))
    rows = parse_rows(first)
    for p in range(2, pages + 1):
        time.sleep(0.5)
        rows += parse_rows(fetch_page(p, frm, to))
    log.info("KAHIS %s~%s: 표시 %d건, 읽은 줄 %d (%d쪽)", frm, to, total, len(rows), pages)
    if len(rows) != total:                    # 조용한 실패 방지: 건수가 다르면 쓰지 않는다
        raise SystemExit(f"[오류] 표시 {total}건 ≠ 읽은 {len(rows)}건 — 파일을 바꾸지 않음")
    recent = group(rows)
    d = json.loads(DISEASE.read_text(encoding="utf-8"))
    keep = [r for r in d.get("recent", []) if "항원" in r["dis"] and r["d"] >= frm]   # KAHIS 표에 없는 줄 유지
    recent = sorted(recent + keep, key=lambda r: r["d"], reverse=True)
    print(f"묶음 {len(recent)}줄 (KAHIS {len(recent) - len(keep)} + 유지 {len(keep)}) · 읍면동 점 {sum(len(r.get('emd', [])) for r in recent)}개")
    for r in recent[:8]:
        print(" ", r["d"], r["dis"], r["sp"], r["loc"][:60], f"· 읍면동 {len(r.get('emd', []))}")
    if "--dry" in sys.argv:
        return
    d["recent"] = recent
    tmp = DISEASE.with_suffix(".tmp")           # 쓰다 끊겨도 원본이 깨지지 않게 임시 파일 → 교체
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, DISEASE)
    log.info("disease_status.json recent 갱신")


if __name__ == "__main__":
    main()
