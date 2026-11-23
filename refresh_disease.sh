#!/bin/bash
# 가축질병 현황 자동 갱신 (홈서버 cron용). 07·11·15·19·23시에 실행.
# 흐름: 최신 받기 → claude -p 로 disease_status.json 갱신 → 테스트 → 지도 재생성 → 커밋·푸시
set -u
# cron은 매시 정각에 부르고, 한국시간(KST) 07·11·15·19·23시만 실제로 갱신한다(서버 시간대와 무관). 수동 실행은 --now.
if [ "${1:-}" != "--now" ]; then
  case "$(TZ=Asia/Seoul date +%H)" in 07|11|15|19|23) ;; *) exit 0 ;; esac
fi
export HOME=/DATA/Documents/work/home
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
export GIT_SSH_COMMAND="ssh -F $HOME/.ssh/config -o BatchMode=yes"
cd /DATA/Documents/work/hanwoo-map || exit 1
LOG=data/refresh_disease.log; mkdir -p data
exec 9>/tmp/hanwoo_refresh.lock; flock -n 9 || { echo "$(date '+%F %T') 이미 실행 중" >>"$LOG"; exit 0; }
log() { echo "$(date '+%F %T') $*" >>"$LOG"; }

log "시작"
git pull --rebase --autostash -q >>"$LOG" 2>&1 || { log "pull 실패 — 중단"; exit 1; }
cp disease_status.json /tmp/disease_status.bak

timeout 1200 claude -p "$(cat disease_refresh_prompt.md)" \
  --permission-mode acceptEdits \
  --allowedTools "Read,Write,Edit,WebFetch,WebSearch,Bash(python3 *),Bash(curl *),Bash(grep *),Bash(sed *)" \
  >>"$LOG" 2>&1 || log "claude 종료 코드 $?"

if ! python3 -m json.tool disease_status.json >/dev/null 2>&1 \
   || ! python3 test_kosis.py --disease-only >>"$LOG" 2>&1; then
  log "검사 실패 — 이전 파일로 되돌림"; cp /tmp/disease_status.bak disease_status.json; exit 1
fi
if git diff --quiet -- disease_status.json; then log "변경 없음"; exit 0; fi

python3 update_map.py --disease-only >>"$LOG" 2>&1 || { log "지도 재생성 실패 — 되돌림"; git checkout -- disease_status.json; exit 1; }
if grep -q "DATA_GO_KR_KEY\|KOSIS_API_KEY" disease_status.json; then log "키 흔적 — 중단"; exit 1; fi
git add disease_status.json hanwoo_map.html
git commit -q -m "data: 가축질병 현황 자동 갱신 ($(date '+%F %H')시)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>" >>"$LOG" 2>&1
git push -q >>"$LOG" 2>&1 && log "푸시 완료" || log "푸시 실패"
