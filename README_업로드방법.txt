ABADDON OFFICIAL WEBSITE v4.8.1 · BOT v19.3.1

GitHub Pages `abaddon-policy` 저장소 ROOT에 이 ZIP의 파일/폴더를 전체 덮어쓴 뒤 Commit/Push하세요.
ZIP 파일 자체를 올리는 것이 아니라 압축을 푼 내용을 올립니다.
기존 주소는 그대로 사용합니다.
https://san01446-ux.github.io/abaddon-policy/

[v4.8.1 핵심]
- 외부 알림센터를 YouTube / Twitch / CHZZK / SOOP 4개 플랫폼으로 확장
- 한국어 / English Dashboard에 CHZZK·SOOP 등록/삭제/상태 UI 추가
- 메인 홈페이지의 외부 알림 소개와 개인정보처리방침을 4개 플랫폼 기준으로 동기화
- 업데이트 페이지에 v19.3.1 릴리즈 기록 추가
- 기존 v4.7.1 서버 전환 snapshot/cache 최적화와 LIVE FEED 복구를 그대로 유지

[v4.7.0 기반 유지]
- Dashboard 버튼/탭 로딩 잠금 문제 수정
- 설정형 서버 관리 기능 대폭 확대
- 홈페이지 공개 LIVE FEED 복구
- Dashboard 내부 LIVE FEED 탭 추가
- /en/dashboard.html 네이티브 English Dashboard 추가
- 한국어/English 페이지 기능·링크·버전 동기화
- English 전용 페이지의 한국어 잔여 UI 제거
- LIVE 명령어센터는 실제 봇 등록 명령을 Relay로 읽음

[구조]
Browser (GitHub Pages)
 -> abaddon-live-feed Render Web Service (OAuth / API / public LIVE)
 -> apocalypse-bot Render Background Worker (실제 world_data 수정 / 명령 레지스트리)

config.js 기본 API
- https://abaddon-live-feed.onrender.com

보안
- 홈페이지에 DISCORD_TOKEN / DISCORD_OAUTH_CLIENT_SECRET / PUBLIC_FEED_RELAY_KEY를 넣지 않습니다.
- OAuth Client Secret은 live-feed Render Environment에만 둡니다.
- Bot Token은 apocalypse-bot Background Worker Environment에만 둡니다.

배포 순서 권장
1) BOT v19.3.1
2) LIVE FEED v1.3.0
3) Website v4.8.1
4) /health version 1.3.0 + worker_online true 확인
5) Discord에서 !웹전체검수, !영문검수
6) Dashboard 한국어/English 양쪽 확인
