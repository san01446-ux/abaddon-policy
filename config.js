window.ABADDON_CONFIG = Object.freeze({
  version: "v6.2.3",
  statusText: "AWAITING SIGNAL",
  statusNote: "GAME CENTER · DIGGING · TREASURE APPRAISAL",
  discordInvite: "https://discord.gg/FN2tX7TVMz",
  botInvite: "https://discord.com/oauth2/authorize?client_id=1532237253944934431&permissions=8&integration_type=0&scope=bot+applications.commands",

  // 별도로 만든 실시간 피드 Web Service 주소를 입력하세요. 예: "https://abaddon-live-feed.onrender.com"
  // Background Worker 주소가 아닙니다. 비워두면 실시간 패널만 "연동 대기"로 표시됩니다.
  eventFeedUrl: "https://abaddon-live-feed.onrender.com",
  liveRefreshMs: 15000
});
