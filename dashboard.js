(() => {
  const cfg = window.ABADDON_CONFIG || {};
  const apiBase = String(cfg.apiBaseUrl || '').trim().replace(/\/$/, '');
  const invalidApi = !apiBase || apiBase === 'YOUR_RENDER_PUBLIC_URL';
  const botVersion = cfg.botVersion || '19.2.0';
  const webVersion = cfg.websiteVersion || '4.7.0';
  document.querySelectorAll('[data-bot-version]').forEach(el => el.textContent = botVersion);
  document.querySelectorAll('[data-web-version]').forEach(el => el.textContent = webVersion);

  const defaultLang = document.documentElement.dataset.defaultLang === 'en' || location.pathname.includes('/en/') ? 'en' : 'ko';
  const forcedEnglishPage = location.pathname.includes('/en/');
  let lang = forcedEnglishPage ? 'en' : (localStorage.getItem('abaddon-lang') === 'en' ? 'en' : (localStorage.getItem('abaddon-lang') === 'ko' ? 'ko' : defaultLang));
  const t = (ko, en) => lang === 'en' ? en : ko;
  const toggle = document.getElementById('langToggle');
  const applyLang = () => {
    document.documentElement.lang = lang;
    document.querySelectorAll('[data-ko][data-en]').forEach(el => { el.textContent = lang === 'en' ? el.dataset.en : el.dataset.ko; });
    if (toggle) toggle.textContent = lang === 'en' ? '한국어' : 'EN';
    renderOverviewFlags();
    renderExternal();
    renderCommands();
    const cs=document.getElementById('commandSearch'); if(cs) cs.placeholder=t('명령어 또는 기능 검색 · 예: 카지노, GIF, 유튜브, 보스','Search commands or features · e.g. casino, GIF, YouTube, boss');
    const yi=document.getElementById('youtubeIdentifier'); if(yi) yi.placeholder=t('@핸들 또는 UC...','@handle or UC...');
    refreshLiveFeed();
  };
  toggle?.addEventListener('click', () => {
    lang = lang === 'en' ? 'ko' : 'en';
    localStorage.setItem('abaddon-lang', lang);
    applyLang();
  });

  const hash = new URLSearchParams(location.hash.replace(/^#/, ''));
  if (hash.get('session')) {
    sessionStorage.setItem('abaddon-session', hash.get('session'));
    history.replaceState({}, '', location.pathname + location.search);
  }
  let session = sessionStorage.getItem('abaddon-session') || '';
  let currentGuild = '';
  let currentSettings = null;
  let currentStructure = null;
  let currentOverview = null;
  let currentReactions = null;
  let currentExternal = null;
  let currentCommands = [];
  let activeCommandCategory = 'all';
  let commandRenderLimit = 120;

  const loginBtn = document.getElementById('loginBtn');
  const logoutBtn = document.getElementById('logoutBtn');
  const saveBtn = document.getElementById('saveBtn');
  const saveReactionBtn = document.getElementById('saveReactionBtn');
  const app = document.getElementById('dashboardApp');
  const statusBox = document.getElementById('statusBox');
  const setupNotice = document.getElementById('setupNotice');
  const guildList = document.getElementById('guildList');
  const guildTitle = document.getElementById('guildTitle');
  const guildMiniStatus = document.getElementById('guildMiniStatus');
  const form = document.getElementById('settingsForm');
  const reactionForm = document.getElementById('reactionForm');

  const authHeaders = () => session ? { Authorization: `Bearer ${session}` } : {};
  const setStatus = (text, type='') => { if (!statusBox) return; statusBox.textContent = text; statusBox.className = `dash-notice ${type}`.trim(); };
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const copyText = async (text) => {
    try {
      await navigator.clipboard.writeText(text);
      setStatus(t(`📋 복사됨: ${text}`, `📋 Copied: ${text}`), 'ok');
    } catch (_) {
      const ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove();
      setStatus(t(`📋 복사됨: ${text}`, `📋 Copied: ${text}`), 'ok');
    }
  };

  if (invalidApi) {
    setupNotice.classList.remove('hidden');
    setupNotice.innerHTML = t(
      '<strong>웹 API 주소 설정 필요</strong><br>config.js의 <code>apiBaseUrl</code>을 ABADDON live-feed Render Web Service 주소로 설정하세요. Discord 봇은 Background Worker로 유지하며 봇 토큰/OAuth Secret은 홈페이지에 넣지 않습니다.',
      '<strong>Web API URL required</strong><br>Set <code>apiBaseUrl</code> in config.js to the public ABADDON live-feed Render Web Service. The Discord bot remains a Background Worker; never place the bot token or OAuth secret in the website.'
    );
    setStatus(t('아직 웹 API가 연결되지 않았습니다.', 'Web API is not connected yet.'), 'warn');
    loginBtn.disabled = true;
  }

  loginBtn?.addEventListener('click', () => {
    if (!invalidApi) location.href = `${apiBase}/auth/discord?lang=${encodeURIComponent(lang)}`;
  });
  logoutBtn?.addEventListener('click', async () => {
    if (session && !invalidApi) { try { await fetch(`${apiBase}/auth/logout`, { headers: authHeaders() }); } catch (_) {} }
    sessionStorage.removeItem('abaddon-session'); session = ''; location.reload();
  });

  async function api(path, options={}) {
    const headers = { ...authHeaders(), ...(options.headers || {}) };
    const res = await fetch(`${apiBase}${path}`, { ...options, headers });
    let data = {};
    try { data = await res.json(); } catch (_) {}
    if (!res.ok) throw new Error(data.error || data.detail || `HTTP ${res.status}`);
    return data;
  }

  function switchPanel(name) {
    document.querySelectorAll('.dash-tab').forEach(btn => btn.classList.toggle('active', btn.dataset.panel === name));
    document.querySelectorAll('.dash-panel').forEach(panel => panel.classList.toggle('active', panel.id === `panel-${name}`));
    if (name === 'live') { refreshLiveFeed(); ensureLiveTimer(); }
  }
  document.querySelectorAll('.dash-tab').forEach(btn => btn.addEventListener('click', () => switchPanel(btn.dataset.panel)));
  document.querySelectorAll('[data-open-panel]').forEach(btn => btn.addEventListener('click', () => switchPanel(btn.dataset.openPanel)));

  const boolIds = ['automod_enabled','spam_block','mention_spam_block','invite_block','bad_words_enabled','auto_timeout','anti_raid_enabled','anti_raid_auto_lockdown','destructive_watch_enabled','story_enabled','codex_notifications','tutorial_notifications','temp_voice_enabled'];
  const selectIds = ['welcome_channel_id','welcome_notice_channel_id','welcome_rules_channel_id','welcome_register_channel_id','leave_channel_id','autorole_id','anti_raid_quarantine_role_id','log_channel_id','log_security_channel_id','log_message_channel_id','log_member_channel_id','log_operation_channel_id','ticket_log_channel_id','ticket_category_id','temp_voice_lobby_id','temp_voice_category_id','announcement_channel_id','rpg_channel_id'];
  const numberIds = ['spam_count','spam_seconds','mention_limit','timeout_minutes','anti_raid_join_limit','anti_raid_window_seconds','anti_raid_min_account_age_days','destructive_watch_threshold','destructive_watch_window_seconds'];

  const setOptions = (id, rows, current, emptyLabel) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.innerHTML = `<option value="">${escapeHtml(emptyLabel)}</option>` + (rows || []).map(row => `<option value="${escapeHtml(row.id)}">${escapeHtml(row.name)}</option>`).join('');
    el.value = current || '';
  };
  const setChannelOptions = (id, current='') => setOptions(id, currentStructure?.text_channels || [], current, t('미설정', 'Not set'));

  function renderSettings(settings, structure) {
    currentSettings = settings; currentStructure = structure;
    boolIds.forEach(id => { const el = document.getElementById(id); if (el) el.checked = Boolean(settings[id]); });
    setOptions('welcome_channel_id', structure.text_channels || [], settings.welcome_channel_id, t('미설정', 'Not set'));
    setOptions('welcome_notice_channel_id', structure.text_channels || [], settings.welcome_notice_channel_id, t('미설정', 'Not set'));
    setOptions('welcome_rules_channel_id', structure.text_channels || [], settings.welcome_rules_channel_id, t('미설정', 'Not set'));
    setOptions('welcome_register_channel_id', structure.text_channels || [], settings.welcome_register_channel_id, t('미설정', 'Not set'));
    setOptions('leave_channel_id', structure.text_channels || [], settings.leave_channel_id, t('미설정', 'Not set'));
    setOptions('autorole_id', structure.roles || [], settings.autorole_id, t('미설정', 'Not set'));
    setOptions('anti_raid_quarantine_role_id', structure.roles || [], settings.anti_raid_quarantine_role_id, t('미설정', 'Not set'));
    setOptions('log_channel_id', structure.text_channels || [], settings.log_channel_id, t('미설정', 'Not set'));
    setOptions('log_security_channel_id', structure.text_channels || [], settings.log_security_channel_id, t('미설정', 'Not set'));
    setOptions('log_message_channel_id', structure.text_channels || [], settings.log_message_channel_id, t('미설정', 'Not set'));
    setOptions('log_member_channel_id', structure.text_channels || [], settings.log_member_channel_id, t('미설정', 'Not set'));
    setOptions('log_operation_channel_id', structure.text_channels || [], settings.log_operation_channel_id, t('미설정', 'Not set'));
    setOptions('ticket_log_channel_id', structure.text_channels || [], settings.ticket_log_channel_id, t('미설정', 'Not set'));
    setOptions('ticket_category_id', structure.categories || [], settings.ticket_category_id, t('미설정', 'Not set'));
    setOptions('temp_voice_lobby_id', structure.voice_channels || [], settings.temp_voice_lobby_id, t('미설정', 'Not set'));
    setOptions('temp_voice_category_id', structure.categories || [], settings.temp_voice_category_id, t('미설정', 'Not set'));
    setOptions('announcement_channel_id', structure.text_channels || [], settings.announcement_channel_id, t('미설정', 'Not set'));
    setOptions('rpg_channel_id', structure.text_channels || [], settings.rpg_channel_id, t('미설정', 'Not set'));
    const numericDefaults = {spam_count:6, spam_seconds:8, mention_limit:5, timeout_minutes:10, anti_raid_join_limit:6, anti_raid_window_seconds:25, anti_raid_min_account_age_days:3, destructive_watch_threshold:3, destructive_watch_window_seconds:20};
    numberIds.forEach(id => { const el = document.getElementById(id); if (el) el.value = Number(settings[id] ?? numericDefaults[id] ?? 0); });
    const roleSel = document.getElementById('button_role_ids');
    if (roleSel) {
      const selected = new Set((settings.button_role_ids || []).map(String));
      roleSel.innerHTML = (structure.roles || []).map(row => `<option value="${escapeHtml(row.id)}" ${selected.has(String(row.id)) ? 'selected' : ''}>${escapeHtml(row.name)}</option>`).join('');
    }
    const modSel = document.getElementById('mod_role_ids');
    if (modSel) {
      const selected = new Set((settings.mod_role_ids || []).map(String));
      modSel.innerHTML = (structure.roles || []).map(row => `<option value="${escapeHtml(row.id)}" ${selected.has(String(row.id)) ? 'selected' : ''}>${escapeHtml(row.name)}</option>`).join('');
    }
    const setMulti = (id, rows, values) => {
      const el = document.getElementById(id); if (!el) return;
      const selected = new Set((values || []).map(String));
      el.innerHTML = (rows || []).map(row => `<option value="${escapeHtml(row.id)}" ${selected.has(String(row.id)) ? 'selected' : ''}>${escapeHtml(row.name)}</option>`).join('');
    };
    setMulti('automod_exempt_channel_ids', structure.text_channels || [], settings.automod_exempt_channel_ids || []);
    setMulti('invite_exempt_channel_ids', structure.text_channels || [], settings.invite_exempt_channel_ids || []);
    const badWords = document.getElementById('bad_word_list'); if (badWords) badWords.value = (settings.bad_word_list || []).join('\n');
    const roleTitle = document.getElementById('button_role_title'); if (roleTitle) roleTitle.value = settings.button_role_title || '';
    const guildLocale = document.getElementById('guild_locale'); if (guildLocale) guildLocale.value = settings.guild_locale === 'en' ? 'en' : 'ko';
    setChannelOptions('youtubeNotifyChannel');
    setChannelOptions('twitchNotifyChannel');
    form.classList.remove('muted-form');
    saveBtn.disabled = false;
  }

  function renderOverview() {
    if (!currentOverview) return;
    document.getElementById('statCommands').textContent = Number(currentOverview.commands || 0).toLocaleString();
    document.getElementById('statMembers').textContent = Number(currentOverview.members || 0).toLocaleString();
    document.getElementById('statGif').textContent = Number(currentOverview.local_gif_count || 0).toLocaleString();
    document.getElementById('statAlerts').textContent = Number((currentOverview.youtube_subscriptions || 0) + (currentOverview.twitch_subscriptions || 0)).toLocaleString();
    document.getElementById('overviewVersion').textContent = `v${currentOverview.version || botVersion}`;
    guildMiniStatus.innerHTML = `<span>👥 ${Number(currentOverview.members || 0).toLocaleString()}</span><span>💬 ${Number(currentOverview.text_channels || 0)}</span><span>🎭 ${Number(currentOverview.roles || 0)}</span>`;
    renderOverviewFlags();
  }

  function renderOverviewFlags() {
    const box = document.getElementById('overviewFlags');
    if (!box || !currentOverview) return;
    const flags = [
      [currentOverview.reaction_enabled, t('자동 GIF', 'Auto GIF')],
      [currentOverview.super_style, t('5개 슈퍼 스타일', '5-reaction Super Style')],
      [Number(currentOverview.youtube_subscriptions || 0) > 0, `YouTube ${Number(currentOverview.youtube_subscriptions || 0)}`],
      [Number(currentOverview.twitch_subscriptions || 0) > 0, `Twitch ${Number(currentOverview.twitch_subscriptions || 0)}`],
      [true, t(`공개 명령 ${Number(currentOverview.commands || 0).toLocaleString()}개`, `${Number(currentOverview.commands || 0).toLocaleString()} public commands`)],
    ];
    box.innerHTML = flags.map(([on,label]) => `<span class="flag ${on ? 'on' : ''}">${on ? '●' : '○'} ${escapeHtml(label)}</span>`).join('');
  }

  function renderReactions() {
    if (!currentReactions) return;
    const map = {
      reaction_enabled: 'enabled', reaction_bot_messages: 'bot_messages', reaction_user_messages: 'user_messages',
      reaction_upgrade: 'upgrade_auto_reactions', reaction_static_fallback: 'allow_static_fallback', reaction_super_style: 'super_style'
    };
    Object.entries(map).forEach(([id,key]) => { const el=document.getElementById(id); if(el) el.checked=Boolean(currentReactions[key]); });
    document.getElementById('reaction_mode').value = currentReactions.mode === 'vivid' ? 'vivid' : 'standard';
    document.getElementById('reactionSourceStatus').textContent = t(
      `현재 서버 GIF ${Number(currentReactions.local_gif_count || 0)}개 · 이모지 뱅크 ${currentReactions.bank_name || '미설정'} / GIF ${Number(currentReactions.bank_gif_count || 0)}개`,
      `Local GIFs ${Number(currentReactions.local_gif_count || 0)} · emoji bank ${currentReactions.bank_name || 'not set'} / ${Number(currentReactions.bank_gif_count || 0)} GIFs`
    );
    const s = currentReactions.stats || {};
    document.getElementById('reactionStats').innerHTML = [
      [t('봇 결과 반응','Bot result reactions'), s.bot_messages_reacted || 0],
      [t('유저 스마트 반응','User smart reactions'), s.user_messages_reacted || 0],
      [t('기존 반응 GIF 변환','Legacy upgrades'), s.auto_reactions_upgraded || 0],
      [t('테스트 실행','Tests'), s.test_runs || 0],
    ].map(([label,value]) => `<div><span>${escapeHtml(label)}</span><strong>${Number(value).toLocaleString()}</strong></div>`).join('');
    reactionForm.classList.remove('muted-form');
    saveReactionBtn.disabled = false;
  }

  const channelName = (id) => currentStructure?.text_channels?.find(row => String(row.id) === String(id))?.name || (id ? String(id) : '-');
  function renderExternal() {
    const env = document.getElementById('externalEnvStatus');
    if (!env || !currentExternal) return;
    env.textContent = `YouTube ${currentExternal.youtube_ready ? '✅' : '❌'} · Twitch ${currentExternal.twitch_ready ? '✅' : '❌'}`;
    env.classList.toggle('warn-pill', !currentExternal.youtube_ready || !currentExternal.twitch_ready);
    const renderList = (platform, rows) => {
      const target = document.getElementById(platform === 'youtube' ? 'youtubeList' : 'twitchList');
      if (!target) return;
      if (!rows.length) {
        target.innerHTML = `<p class="empty-state">${t('등록된 알림이 없습니다.', 'No alerts registered.')}</p>`;
        return;
      }
      target.innerHTML = rows.map(row => {
        const id = platform === 'youtube' ? row.channel_id : row.login;
        const title = platform === 'youtube' ? row.title : row.display_name;
        return `<article class="subscription-row"><div><strong>${escapeHtml(title)}</strong><small>#${escapeHtml(channelName(row.notify_channel_id))} · ${escapeHtml(id)}</small></div><button class="remove-sub" type="button" data-platform="${platform}" data-id="${escapeHtml(id)}">${t('삭제','Remove')}</button></article>`;
      }).join('');
    };
    renderList('youtube', currentExternal.youtube || []);
    renderList('twitch', currentExternal.twitch || []);
  }

  const categoryLabels = {
    setup:['시작·도움','Start & help'], server:['서버 관리','Server admin'], security:['보안','Security'], external:['외부 알림','External alerts'], reaction:['GIF·리액션','GIF & reactions'],
    economy:['경제·생활','Economy & life'], casino:['카지노·미니게임','Casino & games'], social:['커뮤니티·소셜','Community & social'], rpg:['RPG·스토리','RPG & story'], system:['정보·시스템','Info & system'], other:['기타','Other']
  };
  function filteredCommands() {
    const q = String(document.getElementById('commandSearch')?.value || '').trim().toLowerCase();
    return currentCommands.filter(row => {
      if (activeCommandCategory !== 'all' && row.category !== activeCommandCategory) return false;
      if (!q) return true;
      const blob = `${row.name} ${row.name_en || ''} ${(row.aliases || []).join(' ')} ${(row.aliases_en || []).join(' ')} ${row.help || ''} ${row.help_en || ''} ${row.usage || ''} ${row.usage_en || ''}`.toLowerCase();
      return blob.includes(q);
    });
  }
  function renderCommandCategories() {
    const box = document.getElementById('commandCategories');
    if (!box || !currentCommands.length) return;
    const counts = currentCommands.reduce((acc,row) => { acc[row.category]=(acc[row.category]||0)+1; return acc; }, {});
    const ordered = ['setup','server','security','external','reaction','economy','casino','social','rpg','system','other'];
    box.innerHTML = `<button class="category-chip ${activeCommandCategory==='all'?'active':''}" data-category="all">${t('전체','All')} ${currentCommands.length}</button>` + ordered.filter(k => counts[k]).map(key => `<button class="category-chip ${activeCommandCategory===key?'active':''}" data-category="${key}">${escapeHtml(t(...categoryLabels[key]))} ${counts[key]}</button>`).join('');
  }
  function renderCommands() {
    const results = document.getElementById('commandResults');
    const total = document.getElementById('commandTotal');
    if (!results || !total) return;
    if (!currentCommands.length) {
      results.innerHTML = `<p class="micro">${t('명령어 목록을 불러오는 중...', 'Loading command catalog...')}</p>`;
      total.textContent = '- commands';
      return;
    }
    renderCommandCategories();
    const rows = filteredCommands();
    total.textContent = `${rows.length.toLocaleString()} / ${currentCommands.length.toLocaleString()} commands`;
    if (!rows.length) {
      results.innerHTML = `<p class="empty-state">${t('검색 결과가 없습니다.', 'No matching commands.')}</p>`;
      return;
    }
    const visible = rows.slice(0, commandRenderLimit);
    results.innerHTML = `<div class="command-card-grid">${visible.map(row => { const usage=lang==='en'?(row.usage_en||row.usage):row.usage; const help=lang==='en'?(row.help_en||'No description'):row.help; const aliases=lang==='en'?(row.aliases_en||[]):(row.aliases||[]); return `<article class="command-card"><div class="command-card-head"><code>${escapeHtml(usage)}</code><button class="copy-command" type="button" data-command="${escapeHtml(usage)}">${t('복사','Copy')}</button></div><p>${escapeHtml(help || t('설명 없음','No description'))}</p>${aliases.length ? `<small>${t('별칭','Aliases')}: ${escapeHtml(aliases.slice(0,6).join(' · '))}</small>` : ''}</article>`; }).join('')}</div>` + (visible.length < rows.length ? `<button id="loadMoreCommands" class="btn secondary load-more" type="button">${t(`더 보기 · ${rows.length-visible.length}개 남음`, `Load more · ${rows.length-visible.length} remaining`)}</button>` : '');
  }

  let liveTimer = null;
  const liveEscape = escapeHtml;
  const liveTime = (value) => {
    if (!value) return t('방금 전','just now');
    const d = new Date(value); if (Number.isNaN(d.getTime())) return '-';
    return new Intl.DateTimeFormat(lang === 'en' ? 'en-US' : 'ko-KR', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(d);
  };
  async function refreshLiveFeed() {
    const root = document.getElementById('dashboardLiveEvents');
    if (!root || invalidApi) return;
    try {
      const [statusRes, eventsRes] = await Promise.all([
        fetch(`${apiBase}/api/status`, {cache:'no-store'}),
        fetch(`${apiBase}/api/events?limit=12`, {cache:'no-store'}),
      ]);
      const status = await statusRes.json(); const feed = await eventsRes.json();
      if (!statusRes.ok || !eventsRes.ok) throw new Error(`HTTP ${statusRes.status}/${eventsRes.status}`);
      const online = Boolean(status.online || status.worker_fresh);
      const state = document.getElementById('liveFeedState'); if (state) { state.textContent=online?t('온라인','ONLINE'):t('기동/재연결 중','STARTING'); state.classList.toggle('ok-pill',online); }
      const stats = document.getElementById('liveFeedStats');
      if (stats) stats.innerHTML = [
        [t('서버','Guilds'), Number(status.guilds || 0).toLocaleString()],
        [t('멤버','Members'), Number(status.members || 0).toLocaleString()],
        [t('지연','Latency'), `${Number(status.latency_ms || 0)}ms`],
        [t('업데이트','Updated'), liveTime(status.generated_at || status.received_at)],
      ].map(([a,b])=>`<div><span>${liveEscape(a)}</span><strong>${liveEscape(b)}</strong></div>`).join('');
      const rows = Array.isArray(feed.events) ? feed.events : [];
      root.innerHTML = rows.length ? rows.map(ev=>{ const evTitle=(lang==='en'?ev.title_en:ev.title)||ev.title||t('종말 기록','Live event'); const evMessage=(lang==='en'?ev.message_en:ev.message)||(lang==='en'?'':ev.message)||''; return `<article class="dashboard-live-event"><span>${ev.type==='announcement'?'📢':ev.type==='enhance'?'⚒️':'◆'}</span><div><strong>${liveEscape(evTitle)}</strong><p>${liveEscape(evMessage)}</p>${ev.actor?`<small>— ${liveEscape(ev.actor)}</small>`:''}</div><time>${liveEscape(liveTime(ev.created_at))}</time></article>`; }).join('') : `<p class="empty-state">${t('아직 공개 실시간 기록이 없습니다.','No public live events yet.')}</p>`;
    } catch (err) {
      const state = document.getElementById('liveFeedState'); if (state) state.textContent=t('재연결 중','RECONNECTING');
      root.innerHTML = `<p class="empty-state">${t('실시간 피드에 다시 연결하는 중입니다.','Reconnecting to the live feed.')}</p>`;
    }
  }
  function ensureLiveTimer() {
    if (liveTimer) return;
    liveTimer = window.setInterval(() => { if (!document.hidden) refreshLiveFeed(); }, Math.max(10000, Number(cfg.liveRefreshMs)||15000));
  }

  async function chooseGuild(id, name) {
    currentGuild = id; guildTitle.textContent = name;
    currentSettings = currentStructure = currentOverview = currentReactions = currentExternal = null;
    saveBtn.disabled = true; saveReactionBtn.disabled = true; form.classList.add('muted-form'); reactionForm.classList.add('muted-form');
    setStatus(t('서버 기능을 불러오는 중...', 'Loading server features...'));
    document.querySelectorAll('.guild-item').forEach(el => el.classList.toggle('active', el.dataset.id === id));

    const failures = [];
    const [settingsResult, structureResult] = await Promise.allSettled([
      api(`/api/dashboard/settings?guild_id=${encodeURIComponent(id)}`),
      api(`/api/dashboard/structure?guild_id=${encodeURIComponent(id)}`),
    ]);
    if (structureResult.status === 'fulfilled') currentStructure = structureResult.value.structure || {};
    else failures.push(`structure: ${structureResult.reason?.message || 'failed'}`);
    if (settingsResult.status === 'fulfilled') currentSettings = settingsResult.value.settings || {};
    else failures.push(`settings: ${settingsResult.reason?.message || 'failed'}`);
    if (currentSettings && currentStructure) renderSettings(currentSettings, currentStructure);

    const loaders = [
      ['overview', () => api(`/api/dashboard/overview?guild_id=${encodeURIComponent(id)}`), data => { currentOverview=data.overview||{}; renderOverview(); }],
      ['reactions', () => api(`/api/dashboard/reactions?guild_id=${encodeURIComponent(id)}`), data => { currentReactions=data.reactions||{}; renderReactions(); }],
      ['external', () => api(`/api/dashboard/external?guild_id=${encodeURIComponent(id)}`), data => { currentExternal=data.external||{}; renderExternal(); }],
      ['commands', () => currentCommands.length ? Promise.resolve({commands:currentCommands}) : api(`/api/dashboard/commands?guild_id=${encodeURIComponent(id)}`), data => { currentCommands=data.commands||currentCommands||[]; commandRenderLimit=120; renderCommands(); }],
    ];
    const results = await Promise.allSettled(loaders.map(x => x[1]()));
    results.forEach((result, idx) => {
      if (result.status === 'fulfilled') loaders[idx][2](result.value);
      else failures.push(`${loaders[idx][0]}: ${result.reason?.message || 'failed'}`);
    });

    // A slow optional panel must never lock the settings that loaded successfully.
    if (currentSettings && currentStructure) { form.classList.remove('muted-form'); saveBtn.disabled=false; }
    if (currentReactions) { reactionForm.classList.remove('muted-form'); saveReactionBtn.disabled=false; }
    refreshLiveFeed();
    if (!failures.length) setStatus(t('✅ 전체 웹 제어 기능이 연결되었습니다.', '✅ All web control features are connected.'), 'ok');
    else setStatus(t(`⚠️ 일부 기능만 지연/실패했습니다. 가능한 메뉴는 바로 사용할 수 있습니다. · ${failures.join(' | ')}`, `⚠️ Some panels are delayed/unavailable. Loaded controls remain usable. · ${failures.join(' | ')}`), 'warn');
  }

  saveBtn?.addEventListener('click', async () => {
    if (!currentGuild) return;
    saveBtn.disabled = true; setStatus(t('서버 설정을 저장하는 중...', 'Saving server settings...'));
    const payload = { guild_id: currentGuild };
    boolIds.forEach(id => payload[id] = document.getElementById(id).checked);
    selectIds.forEach(id => payload[id] = document.getElementById(id).value || '');
    numberIds.forEach(id => payload[id] = Number(document.getElementById(id)?.value || 0));
    payload.automod_exempt_channel_ids = Array.from(document.getElementById('automod_exempt_channel_ids')?.selectedOptions || []).map(opt => opt.value).slice(0,100);
    payload.invite_exempt_channel_ids = Array.from(document.getElementById('invite_exempt_channel_ids')?.selectedOptions || []).map(opt => opt.value).slice(0,100);
    payload.bad_word_list = String(document.getElementById('bad_word_list')?.value || '').split(/[\n,]+/).map(x => x.trim()).filter(Boolean).slice(0,100);
    payload.button_role_ids = Array.from(document.getElementById('button_role_ids').selectedOptions).map(opt => opt.value).slice(0,25);
    payload.mod_role_ids = Array.from(document.getElementById('mod_role_ids')?.selectedOptions || []).map(opt => opt.value).slice(0,25);
    payload.button_role_title = document.getElementById('button_role_title')?.value || '';
    payload.guild_locale = document.getElementById('guild_locale')?.value || 'ko';
    try {
      const data = await api('/api/dashboard/settings', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
      currentSettings = data.settings || payload;
      setStatus(t('✅ 저장 완료. Discord 명령어에서도 같은 설정이 바로 보입니다.', '✅ Saved. Discord commands now see the same settings.'), 'ok');
    } catch (err) { setStatus(t(`저장 실패: ${err.message}`, `Save failed: ${err.message}`), 'error'); }
    finally { saveBtn.disabled = false; }
  });

  saveReactionBtn?.addEventListener('click', async () => {
    if (!currentGuild) return;
    saveReactionBtn.disabled = true; setStatus(t('GIF 반응 설정을 저장하는 중...', 'Saving GIF reaction settings...'));
    const payload = {
      guild_id: currentGuild,
      enabled: document.getElementById('reaction_enabled').checked,
      mode: document.getElementById('reaction_mode').value,
      super_style: document.getElementById('reaction_super_style').checked,
      bot_messages: document.getElementById('reaction_bot_messages').checked,
      user_messages: document.getElementById('reaction_user_messages').checked,
      upgrade_auto_reactions: document.getElementById('reaction_upgrade').checked,
      allow_static_fallback: document.getElementById('reaction_static_fallback').checked,
    };
    try {
      const data = await api('/api/dashboard/reactions', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
      currentReactions = data.reactions || payload; renderReactions();
      if (currentOverview) { currentOverview.reaction_enabled=currentReactions.enabled; currentOverview.super_style=currentReactions.super_style; renderOverview(); }
      setStatus(t('✅ GIF 설정 저장 완료. Discord의 !이모지센터와 동일한 값입니다.', '✅ GIF settings saved. These are the same values used by !emojicenter.'), 'ok');
    } catch (err) { setStatus(t(`GIF 설정 저장 실패: ${err.message}`, `GIF settings failed: ${err.message}`), 'error'); }
    finally { saveReactionBtn.disabled = false; }
  });

  async function addExternal(platform) {
    if (!currentGuild) return;
    const isYoutube = platform === 'youtube';
    const identifierEl = document.getElementById(isYoutube ? 'youtubeIdentifier' : 'twitchIdentifier');
    const channelEl = document.getElementById(isYoutube ? 'youtubeNotifyChannel' : 'twitchNotifyChannel');
    const btn = document.getElementById(isYoutube ? 'youtubeAddBtn' : 'twitchAddBtn');
    const identifier = identifierEl.value.trim(); const notify = channelEl.value;
    if (!identifier || !notify) { setStatus(t('채널 주소/이름과 Discord 알림 채널을 모두 선택해주세요.', 'Enter a channel and choose a Discord notification channel.'), 'warn'); return; }
    btn.disabled = true; setStatus(t(`${isYoutube?'YouTube':'Twitch'} 채널을 확인하고 등록하는 중...`, `Validating and adding ${isYoutube?'YouTube':'Twitch'} channel...`));
    try {
      const data = await api(`/api/dashboard/external/${platform}`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({guild_id:currentGuild, identifier, notify_channel_id:notify}) });
      currentExternal = data.external || currentExternal; identifierEl.value=''; renderExternal();
      if (currentOverview) { currentOverview.youtube_subscriptions=(currentExternal.youtube||[]).length; currentOverview.twitch_subscriptions=(currentExternal.twitch||[]).length; renderOverview(); }
      setStatus(t(`✅ ${isYoutube?'YouTube':'Twitch'} 알림을 등록했습니다.`, `✅ ${isYoutube?'YouTube':'Twitch'} alert added.`), 'ok');
    } catch (err) { setStatus(t(`등록 실패: ${humanError(err.message)}`, `Add failed: ${humanError(err.message)}`), 'error'); }
    finally { btn.disabled = false; }
  }
  const humanError = (code) => ({
    youtube_identifier_required:t('YouTube 채널을 입력해주세요.','Enter a YouTube channel.'), twitch_identifier_required:t('Twitch 채널을 입력해주세요.','Enter a Twitch channel.'), text_channel_required:t('유효한 Discord 텍스트 채널을 선택해주세요.','Choose a valid Discord text channel.'), youtube_limit_reached:t('YouTube 등록 한도에 도달했습니다.','YouTube alert limit reached.'), twitch_limit_reached:t('Twitch 등록 한도에 도달했습니다.','Twitch alert limit reached.')
  }[code] || code);
  document.getElementById('youtubeAddBtn')?.addEventListener('click', () => addExternal('youtube'));
  document.getElementById('twitchAddBtn')?.addEventListener('click', () => addExternal('twitch'));

  document.addEventListener('click', async (event) => {
    const remove = event.target.closest('.remove-sub');
    if (remove && currentGuild) {
      const platform = remove.dataset.platform, identifier = remove.dataset.id;
      if (!confirm(t(`이 ${platform === 'youtube' ? 'YouTube' : 'Twitch'} 알림을 삭제할까요?`, `Remove this ${platform === 'youtube' ? 'YouTube' : 'Twitch'} alert?`))) return;
      remove.disabled = true;
      try {
        const data = await api('/api/dashboard/external/remove', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({guild_id:currentGuild,platform,identifier})});
        currentExternal = data.external || currentExternal; renderExternal();
        if (currentOverview) { currentOverview.youtube_subscriptions=(currentExternal.youtube||[]).length; currentOverview.twitch_subscriptions=(currentExternal.twitch||[]).length; renderOverview(); }
        setStatus(t('✅ 외부 알림을 삭제했습니다.', '✅ External alert removed.'), 'ok');
      } catch (err) { setStatus(t(`삭제 실패: ${err.message}`, `Remove failed: ${err.message}`), 'error'); }
      return;
    }
    const chip = event.target.closest('.category-chip');
    if (chip) { activeCommandCategory=chip.dataset.category; commandRenderLimit=120; renderCommands(); return; }
    const copy = event.target.closest('.copy-command');
    if (copy) { copyText(copy.dataset.command); return; }
    if (event.target.id === 'loadMoreCommands') { commandRenderLimit += 120; renderCommands(); }
  });

  document.getElementById('commandSearch')?.addEventListener('input', () => { commandRenderLimit=120; renderCommands(); });
  document.getElementById('clearCommandSearch')?.addEventListener('click', () => { document.getElementById('commandSearch').value=''; activeCommandCategory='all'; commandRenderLimit=120; renderCommands(); });
  document.getElementById('copyGifTest')?.addEventListener('click', () => copyText(t('!GIF테스트','!giftest')));
  document.getElementById('dashboardLiveRefresh')?.addEventListener('click', refreshLiveFeed);

  async function boot() {
    applyLang();
    if (invalidApi) return;
    if (!session) {
      setStatus(t('Discord로 로그인하면 관리 가능한 ABADDON 서버와 기능이 표시됩니다.', 'Sign in with Discord to see manageable ABADDON servers and features.'));
      loginBtn.classList.remove('hidden'); logoutBtn.classList.add('hidden'); return;
    }
    loginBtn.classList.add('hidden'); logoutBtn.classList.remove('hidden');
    setStatus(t('관리 가능한 서버를 확인하는 중...', 'Checking manageable servers...'));
    try {
      const data = await api('/api/dashboard/guilds');
      const guilds = data.guilds || []; app.classList.remove('hidden');
      if (!guilds.length) {
        guildList.innerHTML = `<p class="micro">${t('관리 가능한 ABADDON 서버가 없습니다.', 'No manageable ABADDON servers found.')}</p>`;
        setStatus(t('관리 가능한 서버를 찾지 못했습니다.', 'No manageable server found.'), 'warn'); return;
      }
      guildList.innerHTML = guilds.map(g => `<button class="guild-item" data-id="${escapeHtml(g.id)}" data-name="${escapeHtml(g.name)}"><span>${escapeHtml(g.name)}</span><small>${Number(g.members || 0).toLocaleString()} ${t('명','members')}</small></button>`).join('');
      guildList.querySelectorAll('.guild-item').forEach(btn => btn.addEventListener('click', () => chooseGuild(btn.dataset.id, btn.dataset.name)));
      setStatus(t(`${guilds.length}개 서버를 불러왔습니다.`, `${guilds.length} server(s) loaded.`), 'ok');
      chooseGuild(guilds[0].id, guilds[0].name);
    } catch (err) {
      if (String(err.message).includes('login_required')) {
        sessionStorage.removeItem('abaddon-session'); session='';
        setStatus(t('로그인이 만료되었습니다. 다시 로그인해주세요.', 'Session expired. Please sign in again.'), 'warn');
        loginBtn.classList.remove('hidden'); logoutBtn.classList.add('hidden');
      } else setStatus(t(`대시보드 연결 실패: ${err.message}`, `Dashboard connection failed: ${err.message}`), 'error');
    }
  }

  ensureLiveTimer();
  boot();
})();
