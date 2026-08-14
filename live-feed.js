(() => {
  const cfg = window.ABADDON_CONFIG || {};
  const base = String(cfg.eventFeedUrl || cfg.apiBaseUrl || '').replace(/\/$/, '');
  const root = document.getElementById('publicLiveFeed');
  if (!root || !base || /YOUR_|example\.com/i.test(base)) return;

  const state = document.getElementById('publicLiveState');
  const stats = document.getElementById('publicLiveStats');
  const eventsBox = document.getElementById('publicLiveEvents');
  const updated = document.getElementById('publicLiveUpdated');
  const refreshBtn = document.getElementById('publicLiveRefresh');
  const interval = Math.max(10000, Number(cfg.liveRefreshMs || 15000));
  let timer = null;

  const lang = () => (document.documentElement.lang || 'ko').toLowerCase().startsWith('en') ? 'en' : 'ko';
  const t = (ko, en) => lang() === 'en' ? en : ko;
  const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  const num = (value) => Number(value || 0).toLocaleString();
  const fmtTime = (value) => {
    if (!value) return '-';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat(lang() === 'en' ? 'en-US' : 'ko-KR', {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'}).format(date);
  };
  const rune = (type) => ({
    system:'◆', combat:'⚔', boss:'☠', world:'◈', economy:'₵', guild:'♜', craft:'⚒', story:'✦', event:'✹', casino:'♠', social:'☍'
  }[String(type || '').toLowerCase()] || '◇');

  async function getJson(path) {
    const res = await fetch(`${base}${path}`, {cache:'no-store'});
    let data = {};
    try { data = await res.json(); } catch (_) {}
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  }

  function renderStatus(status) {
    const online = Boolean(status.online || status.worker_fresh);
    if (state) {
      state.textContent = online ? t('● ONLINE', '● ONLINE') : t('○ 연결 대기', '○ CONNECTING');
      state.classList.toggle('online', online);
      state.classList.toggle('offline', !online);
    }
    if (stats) {
      const cards = [
        [t('서버','Servers'), num(status.guilds)],
        [t('멤버','Members'), num(status.members)],
        [t('지연','Latency'), `${num(status.latency_ms)} ms`],
        [t('공개 이벤트','Public events'), num(status.event_count)],
      ];
      stats.innerHTML = cards.map(([label,value]) => `<div class="public-live-stat"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join('');
    }
    if (updated) updated.textContent = `${t('마지막 갱신','Last refresh')} · ${fmtTime(status.generated_at || status.heartbeat_at || new Date().toISOString())}`;
  }

  function renderEvents(rows) {
    if (!eventsBox) return;
    if (!Array.isArray(rows) || !rows.length) {
      eventsBox.innerHTML = `<div class="public-live-empty">${t('아직 공개된 실시간 이벤트가 없습니다.', 'No public live events yet.')}</div>`;
      return;
    }
    eventsBox.innerHTML = rows.slice(0, 8).map(row => {
      const title = (lang() === 'en' ? row.title_en : row.title) || row.title || t('ABADDON 이벤트', 'ABADDON event');
      const message = (lang() === 'en' ? row.message_en : row.message) || (lang() === 'en' ? '' : row.message) || '';
      const guild = row.guild ? `<span class="public-live-guild">${esc(row.guild)}</span>` : '';
      return `<article class="public-live-event">
        <div class="public-live-rune">${esc(rune(row.type))}</div>
        <div class="public-live-copy"><div class="public-live-event-head"><strong>${esc(title)}</strong><time>${esc(fmtTime(row.created_at))}</time></div><p>${esc(message)}</p>${guild}</div>
      </article>`;
    }).join('');
  }

  async function refresh() {
    refreshBtn && (refreshBtn.disabled = true);
    try {
      const [statusResult, eventResult] = await Promise.allSettled([
        getJson('/api/status'), getJson('/api/events?limit=8')
      ]);
      if (statusResult.status === 'fulfilled') renderStatus(statusResult.value || {});
      else if (state) { state.textContent = t('○ LIVE FEED 지연', '○ LIVE FEED DELAYED'); state.classList.add('offline'); }
      if (eventResult.status === 'fulfilled') renderEvents(eventResult.value?.events || []);
      else if (eventsBox) eventsBox.innerHTML = `<div class="public-live-empty">${t('실시간 로그를 불러오지 못했습니다. 잠시 후 자동으로 다시 시도합니다.', 'Could not load the live feed. It will retry automatically.')}</div>`;
    } finally {
      refreshBtn && (refreshBtn.disabled = false);
    }
  }

  refreshBtn?.addEventListener('click', refresh);
  window.addEventListener('abaddon-language-changed', refresh);
  refresh();
  timer = window.setInterval(refresh, interval);
  window.addEventListener('pagehide', () => timer && clearInterval(timer), {once:true});
})();
