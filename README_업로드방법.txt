ABADDON 공식 홈페이지 v4.2.0 · BOT v18.5.0 업로드 방법

공식 주소는 그대로 유지합니다.
https://san01446-ux.github.io/abaddon-policy/

[기본 업로드]
1. 이 ZIP을 풉니다.
2. 기존 abaddon-policy GitHub 저장소 최상위에 파일 전체를 덮어씁니다.
3. 기존 config.js에 실제 초대 주소를 이미 넣어뒀다면 새 config.js에도 같은 값을 옮깁니다.
4. Commit changes 후 GitHub Pages 배포를 기다립니다.

[config.js 필수 확인]
- applicationId: Discord Developer Portal Application ID
- botInviteUrl: 기존 봇 초대 URL이 있으면 그대로 사용
- supportInvite: 공식 지원 서버의 만료 없는 초대 코드/URL
- apiBaseUrl: ABADDON 봇이 실행 중인 Render 공개 서비스 주소
  예: https://YOUR-SERVICE.onrender.com

중요: 봇 TOKEN, DISCORD_OAUTH_CLIENT_SECRET 같은 비밀값은 절대 config.js나 GitHub Pages에 넣지 마세요.

[웹 대시보드 사용을 위한 Render 환경변수]
- ABADDON_SITE_URL=https://san01446-ux.github.io/abaddon-policy
- DISCORD_OAUTH_CLIENT_ID=Discord Application ID
- DISCORD_OAUTH_CLIENT_SECRET=Discord OAuth Client Secret
- DISCORD_OAUTH_REDIRECT_URI=https://YOUR-SERVICE.onrender.com/auth/callback
- PUBLIC_FEED_ALLOWED_ORIGIN=https://san01446-ux.github.io

Discord Developer Portal OAuth2 Redirects에도 위 DISCORD_OAUTH_REDIRECT_URI와 같은 주소를 등록해야 합니다.

[대시보드 동작]
- 홈페이지 dashboard.html에서 Discord 로그인
- 로그인한 사람이 관리 권한을 가진 서버 중 ABADDON이 설치된 서버만 표시
- 자동관리 / 로그채널 / 문의 카테고리 / RPG 알림 / 버튼 역할 등을 웹에서 저장
- 문의 패널 생성, 임시 음성 로비 생성처럼 Discord 채널을 새로 만드는 작업은 안전을 위해 Discord 안에서 명령어로 1회 설치
  · !문의패널 / !접수패널
  · !임시음성설정
  · !버튼역할패널

[현재 반영 내용]
- BOT v18.5.0 표기
- 커뮤니티 센터 / 쉬운 서버 설정 센터
- Discord OAuth 기반 웹 대시보드 1차판
- 버튼 역할
- 기존 문의·모더레이션·서버 로그·임시 음성방 기능 통합 안내
- 30초 상태 순환 및 장애 문의 DM @jjonga0022
- 한/영 전환

ZIP 파일 자체를 GitHub에 올리는 것이 아니라 압축을 푼 파일을 올리세요.
