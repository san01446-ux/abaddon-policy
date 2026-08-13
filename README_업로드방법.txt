ABADDON 공식 홈페이지 통합 종합본 v4.2.1 · BOT v18.5.0

이 ZIP은 사용자가 보관하던 v18.1.0 전체 홈페이지(기존 명령어/랭킹/마이페이지/Black City/영문 페이지/이미지 자산)와 v4.2.0 웹 대시보드 업데이트를 하나로 다시 합친 전체 업로드본입니다.
기존 파일 위에 여러 패치를 따로 덮을 필요가 없습니다.

[업로드]
1. ZIP을 풉니다.
2. GitHub의 abaddon-policy 저장소 최상위 파일을 이 ZIP 내용으로 교체/덮어씁니다.
3. Commit changes 합니다.
4. GitHub Pages 배포 후 https://san01446-ux.github.io/abaddon-policy/ 를 새로고침합니다.

[이미 적용된 공개 설정]
- Application ID: 1532237253944934431
- Bot invite: https://discord.com/oauth2/authorize?client_id=1532237253944934431
- Support server: https://discord.gg/FN2tX7TVMz
- 장애 문의 Discord: jjonga0022
- Render API base: https://abaddon-live-feed.onrender.com
- BOT: v18.5.0
- Website: v4.2.1

config.js에는 봇 Token 또는 OAuth Client Secret을 넣지 않았고, 넣어서도 안 됩니다.

[Render OAuth / 대시보드 환경변수]
ABADDON_SITE_URL=https://san01446-ux.github.io/abaddon-policy
DISCORD_OAUTH_CLIENT_ID=1532237253944934431
DISCORD_OAUTH_CLIENT_SECRET=<Discord Developer Portal OAuth2 Client Secret>
DISCORD_OAUTH_REDIRECT_URI=<OAuth/dashboard API가 실제로 열려 있는 Render Web Service>/auth/callback
PUBLIC_FEED_ALLOWED_ORIGIN=https://san01446-ux.github.io

중요: v18.5.0 봇 코드에서 OAuth 콜백 경로는 /auth/callback 입니다. /oauth/callback 이 아닙니다. Discord Developer Portal의 OAuth2 Redirects에도 정확히 같은 URL을 등록하세요.

[이번 종합본에서 해결한 덮어쓰기 충돌]
- 최신 홈페이지 CSS를 site-v421.css로 분리: 기존 Black City/language.html이 사용하는 style.css 보존
- config.js를 신/구 호환형으로 통합: 새 대시보드와 기존 명령어/랭킹/마이페이지/실시간 피드 페이지가 같은 설정을 사용
- 기존 이미지/카드/세계관 자산 전체 보존
- dashboard.html / dashboard.js / app.js 포함
- 개인정보처리방침/이용약관을 최신 OAuth·오류감시·서버관리 내용과 통합
- 기존 페이지 메뉴에 대시보드 접근 경로 추가
- 기존 실시간 피드는 eventFeedUrl=https://abaddon-live-feed.onrender.com 로 연결

[배포 후 확인]
1. 홈에서 ABADDON 초대 버튼
2. 공식 지원 서버 버튼
3. 명령어 / 랭킹 / 마이페이지 / 업데이트 페이지
4. Black City 및 언어 선택 페이지 디자인
5. Dashboard 로그인
6. Privacy / Terms

※ Dashboard 로그인에서 404가 발생한다면 홈페이지 문제가 아니라 apiBaseUrl로 지정한 Render Web Service에 /auth/discord, /auth/callback, /api/dashboard/* 라우트가 실제 배포되어 있는지 확인해야 합니다.


추가 메모 (v18.5.1 연동)
- 현재 홈페이지 코드는 그대로 사용해도 됩니다.
- 봇을 v18.5.1로 올린 뒤 !웹대시보드, dashboard.html, config.js의 apiBaseUrl 연결만 다시 점검하세요.
- Desktop 폴더에서 통째 교체 후 커밋하는 방식이 가장 안전합니다.
