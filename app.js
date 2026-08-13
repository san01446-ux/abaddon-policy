(() => {
  const cfg = window.ABADDON_CONFIG || {};
  const botVersion = cfg.botVersion || "18.9.0";
  const webVersion = cfg.websiteVersion || "4.4.0";
  document.querySelectorAll('[data-bot-version]').forEach(el => el.textContent = botVersion);
  document.querySelectorAll('[data-web-version]').forEach(el => el.textContent = webVersion);

  const appId = String(cfg.applicationId || '').trim();
  const directInvite = String(cfg.botInviteUrl || '').trim();
  const invite = directInvite || (appId && appId !== 'YOUR_APPLICATION_ID'
    ? `https://discord.com/oauth2/authorize?client_id=${encodeURIComponent(appId)}&permissions=8&integration_type=0&scope=bot+applications.commands`
    : '#support');
  const inviteBtn = document.getElementById('inviteBtn');
  if (inviteBtn) inviteBtn.href = invite;

  const supportRaw = String(cfg.supportInvite || '').trim();
  const supportUrl = supportRaw && supportRaw !== 'YOUR_PERMANENT_INVITE'
    ? (supportRaw.startsWith('http') ? supportRaw : `https://discord.gg/${supportRaw}`)
    : '#support';
  const supportBtn = document.getElementById('supportBtn');
  if (supportBtn) supportBtn.href = supportUrl;

  let lang = localStorage.getItem('abaddon-lang') || 'ko';
  const toggle = document.getElementById('langToggle');
  const apply = () => {
    document.documentElement.lang = lang;
    document.querySelectorAll('[data-ko][data-en]').forEach(el => {
      el.textContent = lang === 'en' ? el.dataset.en : el.dataset.ko;
    });
    if (toggle) toggle.textContent = lang === 'en' ? '한국어' : 'EN';
  };
  toggle?.addEventListener('click', () => {
    lang = lang === 'en' ? 'ko' : 'en';
    localStorage.setItem('abaddon-lang', lang);
    apply();
  });
  apply();
})();
