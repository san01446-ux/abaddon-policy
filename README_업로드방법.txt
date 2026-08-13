ABADDON 공식 홈페이지 v4.3.0 · BOT v18.6.0

업로드 기준
- 이 ZIP은 GitHub Pages 저장소(abaddon-policy) 최상위에 그대로 올리는 ROOT UPLOAD 구조입니다.
- Desktop에서 홈페이지 저장소 폴더를 관리 중이면 기존 파일을 이번 ZIP 내용으로 통째로 교체한 뒤 Commit/Push 하세요.
- site-v424.css는 v4.2.4 긴급복구 때 검증한 CSS를 그대로 유지합니다. 이름을 바꾸거나 삭제하지 마세요.

현재 공개 설정
- Application ID: config.js에 현재 실제 값 반영
- 봇 초대 URL: config.js에 현재 실제 값 반영
- 공식 지원 서버: config.js에 현재 실제 값 반영
- 장애 문의: jjonga0022
- Render API: https://abaddon-live-feed.onrender.com

주의
- DISCORD_OAUTH_CLIENT_SECRET / 봇 TOKEN은 홈페이지 파일에 절대 넣지 않습니다.
- OAuth Secret은 Render abaddon-live-feed Environment에만 둡니다.
- 홈페이지 수정 후 GitHub Pages 캐시가 남으면 Ctrl+F5로 강력 새로고침하세요.

배포 후 점검
1. / 메인 페이지 스타일/카드/버튼
2. BOT v18.6.0 / Website v4.3.0 표기
3. 봇 초대 버튼
4. 공식 지원 서버 버튼
5. /dashboard.html 열기
6. Discord OAuth 로그인
7. 관리 서버 목록 표시
8. 설정 저장
9. privacy.html / terms.html
10. 모바일 폭 레이아웃
