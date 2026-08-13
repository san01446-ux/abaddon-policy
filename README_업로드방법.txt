ABADDON OFFICIAL WEBSITE v4.6.1 · BOT v19.1.1

GitHub Pages abaddon-policy 저장소 ROOT에 이 ZIP의 파일/폴더를 전체 덮어쓴 뒤 Commit/Push하세요.
기존 주소는 그대로 사용합니다.
https://san01446-ux.github.io/abaddon-policy/

[v4.6.1 핵심]
- Dashboard 로그인은 abaddon-live-feed Web Service의 Discord OAuth를 사용합니다.
- apocalypse-bot은 Render Background Worker로 유지합니다.
- 웹 설정 요청은 live-feed가 인증한 뒤 Relay Key로 Background Worker에 전달됩니다.
- 서버 설정 / GIF 자동반응 / YouTube·Twitch / LIVE 명령어 센터가 같은 봇 저장 데이터를 사용합니다.

config.js 기본 API
- https://abaddon-live-feed.onrender.com

보안
- 홈페이지에 DISCORD_TOKEN / DISCORD_OAUTH_CLIENT_SECRET / PUBLIC_FEED_RELAY_KEY를 넣지 않습니다.
- OAuth Secret은 live-feed Render Environment에만 둡니다.
- Bot Token은 apocalypse-bot Background Worker Environment에만 둡니다.

배포 순서 권장
1) BOT v19.1.1 배포
2) LIVE FEED v1.1.0 배포
3) Website v4.6.1 배포
4) Discord에서 !웹연결진단
5) Dashboard -> Discord 로그인
