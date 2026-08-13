ABADDON v18.6.0 UX / RETENTION · 전체 배포용

권장 적용 방법 (현재 Desktop 폴더 + GitHub + Render 방식)
1) Desktop의 현재 봇 폴더를 백업합니다.
2) GitHub 연결을 유지하려면 기존 저장소의 .git 폴더는 유지합니다.
3) 이번 ZIP의 abaddon1860 폴더 안 내용을 기존 봇 저장소 루트에 전체 교체합니다.
4) Render Persistent Disk(/var/data)는 절대 삭제하지 않습니다.
5) Commit/Push 후 apocalypse-bot Background Worker를 재배포합니다.

데이터 유지
- /var/data/survival_data.json
- /var/data/abaddon.sqlite3
- backups
- 기존 티켓/로그/자동관리/임시음성/버튼역할 설정
- 기존 v16.2 즐겨찾기/최근 명령 기록
모두 그대로 재사용합니다.

v18.6.0 핵심
- !즐겨찾기: 기존 데이터를 유지하면서 최대 12개 + 버튼/드롭다운 즉시 실행
- !최근 / !최근명령: 최근 사용 기능을 버튼/드롭다운으로 즉시 재실행
- !추천: 가입/출석/튜토리얼/스토리/장비/스태미나/개인 사용 습관 기반 추천
- !다음할일: 현재 최우선 추천 1개
- !인기기능: v18.6 이후 실제 완료 명령 기준 인기 기능
- !로그 같은 스마트 탐색 결과에 개인 사용 습관을 최대 3칸 정도 가볍게 반영
- 스마트 탐색의 ⭐ 상위 기능 저장 버튼으로 즐겨찾기 추가/해제
- 검색어/완료 명령 통계 집계 (사용자의 메시지 원문/명령 인수 전문은 저장하지 않음)
- 한글 !명령어 / 영문 !help에 즐겨찾기·최근·추천 빠른 재진입 안내
- !패치점검 최신화

apocalypse-bot Environment 확인
- DISCORD_TOKEN
- DATA_FILE (기존 값 유지)
- ABADDON_OWNER_ID = 제작자 Discord 숫자 ID
- ABADDON_SITE_URL = https://san01446-ux.github.io/abaddon-policy
- ABADDON_SUPPORT_URL = 공식 지원 서버 초대 URL (기존 값 유지)
- KoreanBots / PUBLIC_FEED 관련 기존 값 유지

abaddon-live-feed Environment 확인
- DISCORD_OAUTH_CLIENT_ID
- DISCORD_OAUTH_CLIENT_SECRET
- DISCORD_OAUTH_REDIRECT_URI = https://abaddon-live-feed.onrender.com/auth/callback
- PUBLIC_FEED_ALLOWED_ORIGIN = https://san01446-ux.github.io
- 기존 ABADDON_FEED_SECRET / FEED 관련 값 유지

보안
- Bot Token과 DISCORD_OAUTH_CLIENT_SECRET은 GitHub/config.js에 절대 넣지 않습니다.
- OAuth Client Secret은 abaddon-live-feed Render Environment에만 둡니다.

배포 후 점검
1) !패치점검
2) !로그
3) !즐겨찾기 추가 채집 → !즐겨찾기
4) !최근
5) !추천
6) !다음할일
7) !인기기능
8) !명령어
9) !help
10) !커뮤니티센터 → 문의 모달 → 제작자 DM
11) !웹대시보드
12) 소유자: !1860검수
13) 소유자: !UX통계

홈페이지
- 함께 제공되는 ABADDON 공식 홈페이지 v4.3.0 전체본을 사용합니다.
- GitHub Pages abaddon-policy 저장소에 ROOT 파일들을 통째로 교체 후 Commit/Push합니다.
- v4.2.4에서 복구한 site-v424.css 구조를 그대로 유지합니다.


=== v18.9.0 추가 배포 메모 ===
- Desktop의 기존 봇 저장소에서 .git은 유지하고 이 전체 배포본 내용으로 교체 후 Commit/Push 하세요.
- /var/data는 삭제하지 않습니다. 기존 유저/서버/즐겨찾기/티켓/설정 데이터를 그대로 재사용합니다.
- 외부 알림을 사용하지 않으면 YOUTUBE_API_KEY / TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET은 설정하지 않아도 됩니다.
- 외부 알림 사용 시 세 값은 홈페이지/live-feed가 아니라 실제 봇(apocalypse-bot) Environment에 넣으세요.
- 배포 후 가장 먼저 !패치점검, 마지막에 !1890검수를 실행하세요.

[v19.0.0]
- Desktop 저장소 폴더에서 .git은 유지하고 이 배포본 내용으로 전체 교체 후 Commit/Push 하세요.
- /var/data는 삭제하거나 덮어쓰지 마세요.
- 배포 후 !패치점검 → !1900검수 순서로 확인하세요.
- User Install을 실제로 노출하려면 Discord Developer Portal > Installation에서 User Install을 켜야 합니다.
- YouTube 알림 사용 시 apocalypse-bot Render Environment의 YOUTUBE_API_KEY에 Google Cloud API Key를 넣습니다. 유튜브 주소를 넣는 칸이 아닙니다.
