(() => {
  const root = document.querySelector('[data-black-city-root]');
  if (!root) return;
  const lang = document.documentElement.lang === 'ko' ? 'ko' : 'en';
  const t = (ko,en) => lang === 'ko' ? ko : en;
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  fetch((lang === 'ko' ? '' : '../') + 'black_city_public.json', {cache:'no-store'})
    .then(r => { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
    .then(data => {
      const guilds = Object.values(data.guilds || {});
      if (!guilds.length) { root.innerHTML = `<div class="empty-state"><h2>${t('연동 대기','Awaiting connection')}</h2><p>${t('공개를 켠 서버의 안전한 도시 요약만 여기에 표시됩니다. 가짜 수치는 표시하지 않습니다.','Only privacy-safe summaries from guilds that explicitly enable publishing appear here. No fake statistics are shown.')}</p></div>`; return; }
      root.innerHTML = guilds.map(g => `<article class="world-card"><h2>${esc(g.city_name || t('이름 없는 도시','Unnamed City'))}</h2><p>${esc(g.season?.stage || t('시즌 준비','Season setup'))} · ${esc(g.season?.ending_hint || '')}</p><div class="metric-row">${Object.entries(g.metrics || {}).map(([k,v]) => `<span><b>${esc(v)}</b>${esc(k)}</span>`).join('')}</div><div class="district-grid">${(g.districts || []).map(d => `<span>${esc(d.name)}<small>${esc(d.owner || t('중립','Neutral'))}</small></span>`).join('')}</div></article>`).join('');
    })
    .catch(() => { root.innerHTML = `<div class="empty-state"><h2>${t('연동 대기','Awaiting connection')}</h2><p>${t('공개 월드 데이터에 연결할 수 없습니다.','Public world data is currently unavailable.')}</p></div>`; });
})();
