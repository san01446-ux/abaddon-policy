const commands = [
 {c:"시작",cmd:"!가입 생존자",d:"아바돈 생존자 계정을 생성합니다."},
 {c:"시작",cmd:"!튜토리얼",d:"초보자 튜토리얼 진행 상황을 확인합니다."},
 {c:"캐릭터",cmd:"!정보",d:"레벨, 경험치, 체력, 감염도 등 내 상태를 확인합니다."},
 {c:"캐릭터",cmd:"!인벤토리",d:"보유 아이템과 장비를 확인합니다."},
 {c:"전투",cmd:"!탐색",d:"지역을 탐색하고 전투와 보상을 획득합니다."},
 {c:"전투",cmd:"!던전",d:"던전 콘텐츠와 관련 명령을 확인합니다."},
 {c:"전투",cmd:"!침공",d:"현재 진행 중인 서버 침공을 확인합니다."},
 {c:"수집",cmd:"!도감",d:"몬스터, 아이템, 펫 수집 현황을 확인합니다."},
 {c:"수집",cmd:"!도감보상",d:"도감 달성 보상을 수령합니다."},
 {c:"스토리",cmd:"!스토리",d:"스토리 시즌과 현재 진행도를 확인합니다."},
 {c:"스토리",cmd:"!스토리 시작",d:"검은 주파수 스토리를 시작합니다."},
 {c:"스토리",cmd:"!스토리 선택 1",d:"현재 장면에서 선택지를 결정합니다."},
 {c:"생활",cmd:"!제작",d:"보유 재료로 아이템을 제작합니다."},
 {c:"생활",cmd:"!상점",d:"상점의 판매 아이템을 확인합니다."},
 {c:"생활",cmd:"!출석",d:"일일 출석 보상을 받습니다."},
 {c:"커뮤니티",cmd:"!길드",d:"길드 관련 기능을 확인합니다."},
 {c:"커뮤니티",cmd:"!파티",d:"파티 관련 기능을 확인합니다."},
 {c:"이벤트",cmd:"!퀴즈알림상태",d:"서버의 일일 퀴즈 알림 상태를 확인합니다."},
 {c:"관리",cmd:"!서버설정",d:"현재 서버에 적용된 설정을 확인합니다."},
 {c:"도움말",cmd:"!명령어",d:"봇의 전체 명령어 안내를 확인합니다."}
];

const cats = ["전체","시작","캐릭터","전투","수집","스토리","생활","커뮤니티","이벤트","관리","도움말"];
let active = "전체";

function renderCommands(){
 const list = document.querySelector("#commandList");
 if(!list) return;
 const q = (document.querySelector("#commandSearch")?.value || "").trim().toLowerCase();
 const filtered = commands.filter(x => (active==="전체" || x.c===active) &&
   (`${x.cmd} ${x.d} ${x.c}`).toLowerCase().includes(q));
 list.innerHTML = filtered.map(x => `<div class="command"><div><code>${x.cmd}</code><p>${x.d}</p></div><span class="tag">${x.c}</span></div>`).join("")
   || `<div class="command"><div><code>검색 결과 없음</code><p>다른 검색어를 입력해 보세요.</p></div></div>`;
}
function mountCategories(){
 const box=document.querySelector("#commandCats"); if(!box)return;
 box.innerHTML=cats.map(c=>`<button class="cat-btn ${c===active?"active":""}" data-cat="${c}">${c}</button>`).join("");
 box.addEventListener("click",e=>{
   const b=e.target.closest("[data-cat]"); if(!b)return;
   active=b.dataset.cat; mountCategories(); renderCommands();
 });
}
function applyConfig(){
 document.querySelectorAll("[data-invite]").forEach(a=>a.href=ABADDON_CONFIG.botInviteUrl);
 document.querySelectorAll("[data-support]").forEach(a=>a.href=ABADDON_CONFIG.supportServerUrl);
 document.querySelectorAll("[data-version]").forEach(e=>e.textContent=ABADDON_CONFIG.version);
 document.querySelectorAll("[data-status]").forEach(e=>e.textContent=ABADDON_CONFIG.statusText);
 document.querySelectorAll("[data-status-note]").forEach(e=>e.textContent=ABADDON_CONFIG.statusNote);
 document.querySelectorAll("[data-github]").forEach(a=>a.href=ABADDON_CONFIG.githubUrl);
}
document.addEventListener("DOMContentLoaded",()=>{
 applyConfig(); mountCategories(); renderCommands();
 document.querySelector("#commandSearch")?.addEventListener("input",renderCommands);
});
