ABADDON 공식 홈페이지 v4.4.0 · BOT v18.9.0

이 ZIP은 GitHub Pages 저장소 루트에 그대로 덮어쓰는 전체 종합본입니다.
Desktop의 abaddon-policy 폴더에서 .git은 유지하고 나머지 파일을 이 패키지 내용으로 교체한 뒤 Commit/Push 하세요.

필수 확인
1. config.js의 applicationId / botInviteUrl / supportInvite / apiBaseUrl 값이 실제 값인지 확인
2. BOT v18.9.0 / Website v4.4.0 표기
3. index.html · dashboard.html · privacy.html · terms.html 정상 열림
4. dashboard.html에서 Discord 로그인 → 서버 선택 → 자동화/보안 설정 저장
5. CSS는 site-v424.css를 유지합니다. 파일명/경로를 임의 변경하지 마세요.

비밀값 주의
- Bot Token, Discord OAuth Client Secret, Twitch Client Secret, YouTube API Key는 GitHub/config.js에 절대 넣지 않습니다.
- 해당 값들은 Render Environment에만 둡니다.

Render 봇 환경변수(기존 값 유지)
- ABADDON_OWNER_ID
- ABADDON_SITE_URL
- ABADDON_SUPPORT_URL
- DISCORD_TOKEN

외부 알림을 사용할 때만 봇(apocalypse-bot) Environment에 추가
- YOUTUBE_API_KEY
- TWITCH_CLIENT_ID
- TWITCH_CLIENT_SECRET
