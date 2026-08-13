(() => {
  const cfg = window.ABADDON_CONFIG || {};
  const apiBase = String(cfg.apiBaseUrl || '').trim().replace(/\/$/, '');
  const invalidApi = !apiBase || apiBase === 'YOUR_RENDER_PUBLIC_URL';
  const botVersion = cfg.botVersion || '19.0.1';
  const webVersion = cfg.websiteVersion || '4.5.1';
  document.querySelectorAll('[data-bot-version]').forEach(el => el.textContent = botVersion);
  document.querySelectorAll('[data-web-version]').forEach(el => el.textContent = webVersion);

  let lang = localStorage.getItem('abaddon-lang') || 'ko';
  const toggle = document.getElementById('langToggle');
  const t = (ko, en) => lang === 'en' ? en : ko;
  const applyLang = () => {
    document.documentElement.lang = lang;
    document.querySelectorAll('[data-ko][data-en]').forEach(el => el.textContent = lang === 'en' ? el.dataset.en : el.dataset.ko);
    if (toggle) toggle.textContent = lang === 'en' ? '한국어' : 'EN';
  };
  toggle?.addEventListener('click', () => { lang = lang === 'en' ? 'ko' : 'en'; localStorage.setItem('abaddon-lang', lang); applyLang(); });
  applyLang();

  const hash = new URLSearchParams(location.hash.replace(/^#/, ''));
  if (hash.get('session')) {
    sessionStorage.setItem('abaddon-session', hash.get('session'));
    history.replaceState({}, '', location.pathname + location.search);
  }
  let session = sessionStorage.getItem('abaddon-session') || '';
  let currentGuild = '';
  let currentSettings = null;
  let currentStructure = null;

  const loginBtn = document.getElementById('loginBtn');
  const logoutBtn = document.getElementById('logoutBtn');
  const saveBtn = document.getElementById('saveBtn');
  const app = document.getElementById('dashboardApp');
  const statusBox = document.getElementById('statusBox');
  const setupNotice = document.getElementById('setupNotice');
  const guildList = document.getElementById('guildList');
  const guildTitle = document.getElementById('guildTitle');
  const form = document.getElementById('settingsForm');

  const authHeaders = () => session ? { Authorization: `Bearer ${session}` } : {};
  const setStatus = (text, type='') => { statusBox.textContent = text; statusBox.className = `dash-notice ${type}`.trim(); };

  if (invalidApi) {
    setupNotice.classList.remove('hidden');
    setupNotice.innerHTML = t(
      '<strong>웹 API 주소 설정 필요</strong><br>config.js의 <code>apiBaseUrl</code>을 Render 공개 서비스 주소로 바꾸세요. 봇 토큰이나 OAuth Secret은 홈페이지에 넣지 않습니다.',
      '<strong>Web API URL required</strong><br>Set <code>apiBaseUrl</code> in config.js to the Render web service that exposes the ABADDON OAuth/dashboard routes. Never put the bot token or OAuth secret in the website.'
    );
    setStatus(t('아직 웹 API가 연결되지 않았습니다.', 'Web API is not connected yet.'), 'warn');
    loginBtn.disabled = true;
  }

  loginBtn?.addEventListener('click', () => {
    if (invalidApi) return;
    location.href = `${apiBase}/auth/discord?lang=${encodeURIComponent(lang)}`;
  });

  logoutBtn?.addEventListener('click', async () => {
    if (session && !invalidApi) {
      try { await fetch(`${apiBase}/auth/logout`, { headers: authHeaders() }); } catch (_) {}
    }
    sessionStorage.removeItem('abaddon-session');
    session = '';
    location.reload();
  });

  async function api(path, options={}) {
    const headers = { ...authHeaders(), ...(options.headers || {}) };
    const res = await fetch(`${apiBase}${path}`, { ...options, headers });
    let data = {};
    try { data = await res.json(); } catch (_) {}
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  }

  const boolIds = ['automod_enabled','invite_block','bad_words_enabled','auto_timeout','anti_raid_enabled','anti_raid_auto_lockdown','destructive_watch_enabled','story_enabled','codex_notifications','tutorial_notifications','temp_voice_enabled'];
  const selectIds = ['welcome_channel_id','leave_channel_id','autorole_id','log_channel_id','ticket_log_channel_id','ticket_category_id','announcement_channel_id','rpg_channel_id'];
  const numberIds = ['destructive_watch_threshold','destructive_watch_window_seconds'];

  const setOptions = (id, rows, current, emptyLabel) => {
    const el = document.getElementById(id);
    el.innerHTML = `<option value="">${emptyLabel}</option>` + rows.map(row => `<option value="${row.id}">${escapeHtml(row.name)}</option>`).join('');
    el.value = current || '';
  };
  const escapeHtml = (value) => String(value || '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));

  function renderSettings(settings, structure) {
    currentSettings = settings;
    currentStructure = structure;
    boolIds.forEach(id => { document.getElementById(id).checked = Boolean(settings[id]); });
    setOptions('welcome_channel_id', structure.text_channels || [], settings.welcome_channel_id, t('미설정', 'Not set'));
    setOptions('leave_channel_id', structure.text_channels || [], settings.leave_channel_id, t('미설정', 'Not set'));
    setOptions('autorole_id', structure.roles || [], settings.autorole_id, t('미설정', 'Not set'));
    setOptions('log_channel_id', structure.text_channels || [], settings.log_channel_id, t('미설정', 'Not set'));
    setOptions('ticket_log_channel_id', structure.text_channels || [], settings.ticket_log_channel_id, t('미설정', 'Not set'));
    setOptions('ticket_category_id', structure.categories || [], settings.ticket_category_id, t('미설정', 'Not set'));
    setOptions('announcement_channel_id', structure.text_channels || [], settings.announcement_channel_id, t('미설정', 'Not set'));
    setOptions('rpg_channel_id', structure.text_channels || [], settings.rpg_channel_id, t('미설정', 'Not set'));
    numberIds.forEach(id => { const el = document.getElementById(id); if (el) el.value = Number(settings[id] || (id.includes('threshold') ? 3 : 20)); });
    const ext = document.getElementById('externalStatus');
    if (ext) ext.textContent = t(
      `YouTube 환경 ${settings.youtube_api_ready ? '✅' : '➖'} · 등록 ${Number(settings.external_youtube_count || 0)}개 / Twitch 환경 ${settings.twitch_api_ready ? '✅' : '➖'} · 등록 ${Number(settings.external_twitch_count || 0)}개`,
      `YouTube env ${settings.youtube_api_ready ? '✅' : '➖'} · ${Number(settings.external_youtube_count || 0)} subscription(s) / Twitch env ${settings.twitch_api_ready ? '✅' : '➖'} · ${Number(settings.external_twitch_count || 0)} subscription(s)`
    );
    const roleSel = document.getElementById('button_role_ids');
    const selected = new Set((settings.button_role_ids || []).map(String));
    roleSel.innerHTML = (structure.roles || []).map(row => `<option value="${row.id}" ${selected.has(String(row.id)) ? 'selected' : ''}>${escapeHtml(row.name)}</option>`).join('');
    form.classList.remove('muted-form');
    saveBtn.disabled = false;
  }

  async function chooseGuild(id, name) {
    currentGuild = id;
    guildTitle.textContent = name;
    saveBtn.disabled = true;
    form.classList.add('muted-form');
    setStatus(t('서버 설정을 불러오는 중...', 'Loading server settings...'));
    document.querySelectorAll('.guild-item').forEach(el => el.classList.toggle('active', el.dataset.id === id));
    try {
      const [settingsData, structureData] = await Promise.all([
        api(`/api/dashboard/settings?guild_id=${encodeURIComponent(id)}`),
        api(`/api/dashboard/structure?guild_id=${encodeURIComponent(id)}`),
      ]);
      renderSettings(settingsData.settings || {}, structureData.structure || {});
      setStatus(t('설정을 불러왔습니다.', 'Settings loaded.'), 'ok');
    } catch (err) {
      setStatus(t(`불러오기 실패: ${err.message}`, `Load failed: ${err.message}`), 'error');
    }
  }

  saveBtn?.addEventListener('click', async () => {
    if (!currentGuild) return;
    saveBtn.disabled = true;
    setStatus(t('설정을 저장하는 중...', 'Saving settings...'));
    const payload = { guild_id: currentGuild };
    boolIds.forEach(id => payload[id] = document.getElementById(id).checked);
    selectIds.forEach(id => payload[id] = document.getElementById(id).value || '');
    numberIds.forEach(id => payload[id] = Number(document.getElementById(id).value || 0));
    payload.button_role_ids = Array.from(document.getElementById('button_role_ids').selectedOptions).map(opt => opt.value).slice(0,25);
    try {
      const data = await api('/api/dashboard/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      currentSettings = data.settings || payload;
      setStatus(t('✅ 저장 완료. Discord 봇 설정에도 바로 반영됩니다.', '✅ Saved. Changes are now active in the Discord bot.'), 'ok');
    } catch (err) {
      setStatus(t(`저장 실패: ${err.message}`, `Save failed: ${err.message}`), 'error');
    } finally {
      saveBtn.disabled = false;
    }
  });

  async function boot() {
    if (invalidApi) return;
    if (!session) {
      setStatus(t('Discord로 로그인하면 관리 가능한 서버가 표시됩니다.', 'Sign in with Discord to see manageable servers.'));
      loginBtn.classList.remove('hidden');
      logoutBtn.classList.add('hidden');
      return;
    }
    loginBtn.classList.add('hidden');
    logoutBtn.classList.remove('hidden');
    setStatus(t('관리 가능한 서버를 확인하는 중...', 'Checking manageable servers...'));
    try {
      const data = await api('/api/dashboard/guilds');
      const guilds = data.guilds || [];
      app.classList.remove('hidden');
      if (!guilds.length) {
        guildList.innerHTML = `<p class="micro">${t('관리 가능한 ABADDON 서버가 없습니다.', 'No manageable ABADDON servers found.')}</p>`;
        setStatus(t('관리 가능한 서버를 찾지 못했습니다.', 'No manageable server found.'), 'warn');
        return;
      }
      guildList.innerHTML = guilds.map(g => `<button class="guild-item" data-id="${g.id}" data-name="${escapeHtml(g.name)}"><span>${escapeHtml(g.name)}</span><small>${Number(g.members || 0).toLocaleString()} ${t('명','members')}</small></button>`).join('');
      guildList.querySelectorAll('.guild-item').forEach(btn => btn.addEventListener('click', () => chooseGuild(btn.dataset.id, btn.dataset.name)));
      setStatus(t(`${guilds.length}개 서버를 불러왔습니다.`, `${guilds.length} server(s) loaded.`), 'ok');
      chooseGuild(guilds[0].id, guilds[0].name);
    } catch (err) {
      if (String(err.message).includes('login_required')) {
        sessionStorage.removeItem('abaddon-session');
        session = '';
        setStatus(t('로그인이 만료되었습니다. 다시 로그인해주세요.', 'Session expired. Please sign in again.'), 'warn');
        loginBtn.classList.remove('hidden');
        logoutBtn.classList.add('hidden');
      } else {
        setStatus(t(`대시보드 연결 실패: ${err.message}`, `Dashboard connection failed: ${err.message}`), 'error');
      }
    }
  }

  boot();
})();
