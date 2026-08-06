ABADDON v10.9.2 홈페이지 실시간 ONLINE 연결

1. 이 live-service 폴더를 별도 Render Web Service로 배포합니다.
2. Web Service의 PUBLIC_FEED_RELAY_KEY 값을 확인합니다.
3. 봇 Background Worker에 다음 환경변수를 추가합니다.
   PUBLIC_FEED_RELAY_URL=https://배포한-서비스.onrender.com
   PUBLIC_FEED_RELAY_KEY=같은-비밀키
4. 홈페이지 config.js의 eventFeedUrl에 같은 Web Service 주소를 입력합니다.
5. Discord에서 !실시간피드 켜기, !실시간피드테스트, !실시간피드상태 순서로 점검합니다.

API를 아직 연결하지 않아도 v10.9.2 홈페이지는 config.js의 status=ONLINE을 이용해 초록불을 표시합니다.
API가 연결되면 서버 수, 생존자 수, 지연시간, 마지막 심박과 공개 이벤트가 실제 값으로 자동 전환됩니다.
