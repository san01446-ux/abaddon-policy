"use strict";

const commands = [
  {"c": "스토리", "cmd": "!시즌2", "d": "스토리 시즌 2 백색 방주의 현재 진행 상태와 선택지를 확인합니다."},
  {"c": "스토리", "cmd": "!시즌2 시작", "d": "시즌 1 선택 기록을 계승해 백색 방주 후속 캠페인을 시작합니다."},
  {"c": "스토리", "cmd": "!시즌2 선택 번호", "d": "현재 장면에서 조건에 맞는 선택지를 골라 이야기를 진행합니다."},
  {"c": "스토리", "cmd": "!시즌2 기록", "d": "현재 회차의 선택 기록과 발견한 시즌 2 엔딩을 확인합니다."},
  {"c": "스토리", "cmd": "!시즌2 재시작", "d": "발견 엔딩과 보상 수령 기록을 유지한 채 다른 분기를 시작합니다."},
  {"c": "원정", "cmd": "!원정 도움말", "d": "턴제 원정 전투의 공격·방어·집중·응급·도주 행동을 안내합니다."},
  {"c": "원정", "cmd": "!원정 목록", "d": "원정 지역별 레벨, 평판, 스태미나 조건과 위험도를 확인합니다."},
  {"c": "원정", "cmd": "!원정 출발 지역명", "d": "스태미나를 사용해 선택한 지역의 턴제 전투를 시작합니다."},
  {"c": "원정", "cmd": "!원정 행동 공격", "d": "진행 중인 원정에서 공격, 방어, 집중, 응급 또는 도주 행동을 수행합니다."},
  {"c": "원정", "cmd": "!원정 보급", "d": "하루 한 번 원정 응급 키트와 평판 기반 식량 보급을 받습니다."},
  {"c": "원정", "cmd": "!원정 유물", "d": "원정과 스토리에서 발견한 희귀 유물과 설명을 확인합니다."},
  {"c": "원정", "cmd": "!원정 기록", "d": "최근 원정의 승리, 실패, 도주와 획득 보상을 확인합니다."},
  {"c": "원정", "cmd": "!원정 랭킹", "d": "현재 Discord 서버의 원정 평판 상위 생존자를 확인합니다."},
  {"c": "관리", "cmd": "!접수센터도움말", "d": "문의·신고·건의 처리센터의 설치와 운영 명령을 안내합니다."},
  {"c": "관리", "cmd": "!접수초기설정", "d": "문의 카테고리와 처리 로그를 연결하고 유형별 접수 패널을 설치합니다."},
  {"c": "관리", "cmd": "!접수패널", "d": "문의·신고·건의·버그·이의신청 버튼이 있는 비공개 접수 패널을 만듭니다."},
  {"c": "관리", "cmd": "!접수센터상태", "d": "접수 카테고리, 처리 로그, 열린 접수와 누적 통계를 확인합니다."},
  {"c": "관리", "cmd": "!접수현황 [상태]", "d": "열린 접수를 우선순위와 처리 상태 순으로 확인합니다."},
  {"c": "관리", "cmd": "!접수정보", "d": "현재 접수의 번호, 유형, 담당자, 상태와 우선순위를 표시합니다."},
  {"c": "관리", "cmd": "!접수담당 [@운영자]", "d": "현재 접수의 담당 운영자를 지정합니다."},
  {"c": "관리", "cmd": "!접수담당해제", "d": "현재 접수의 담당자 배정을 해제합니다."},
  {"c": "관리", "cmd": "!접수상태 처리중", "d": "접수 상태를 접수, 확인중, 처리중, 사용자대기 또는 보류로 변경합니다."},
  {"c": "관리", "cmd": "!접수우선순위 긴급", "d": "접수 우선순위를 낮음, 보통, 높음 또는 긴급으로 변경합니다."},
  {"c": "관리", "cmd": "!접수메모 내용", "d": "사용자에게 노출되지 않는 운영진 내부 처리 메모를 저장합니다."},
  {"c": "관리", "cmd": "!답변양식추가 이름 | 내용", "d": "자주 사용하는 안내문을 빠른 답변 양식으로 등록합니다."},
  {"c": "관리", "cmd": "!답변양식목록", "d": "현재 서버에 등록된 빠른 답변 양식을 확인합니다."},
  {"c": "관리", "cmd": "!빠른답변 이름", "d": "현재 접수 채널에 저장된 답변 양식을 전송합니다."},
  {"c": "편의", "cmd": "!내접수", "d": "자신의 현재 열린 접수 상태를 DM으로 확인합니다."},
  {"c": "관리", "cmd": "!접수종료 [사유]", "d": "대화 기록을 처리 로그에 보관하고 현재 접수를 종료합니다."},
  {"c": "관리", "cmd": "!보안센터도움말", "d": "통합 보안센터, 분리 로그와 자동관리 설정 명령을 안내합니다."},
  {"c": "관리", "cmd": "!보안초기설정", "d": "운영진 전용 보안센터와 로그 채널 4개를 자동 생성·연결합니다."},
  {"c": "관리", "cmd": "!보안상태", "d": "분리 로그, 자동관리, 초대 예외와 신생 계정 알림 상태를 표시합니다."},
  {"c": "관리", "cmd": "!보안테스트", "d": "보안·메시지·멤버·운영 로그 채널 연결을 테스트합니다."},
  {"c": "관리", "cmd": "!로그채널설정 보안 #채널", "d": "로그 종류별 전송 채널을 개별 지정합니다."},
  {"c": "관리", "cmd": "!자동관리모드 삭제", "d": "자동관리 처리 방식을 알림, 삭제 또는 누적 타임아웃으로 선택합니다."},
  {"c": "관리", "cmd": "!자동관리기준 6 8 5 3 10", "d": "도배 개수·시간, 멘션 수, 누적 횟수와 타임아웃 시간을 설정합니다."},
  {"c": "관리", "cmd": "!초대허용채널 #채널", "d": "Discord 초대 링크 차단에서 제외할 채널을 등록합니다."},
  {"c": "관리", "cmd": "!초대허용해제 #채널", "d": "등록된 초대 링크 허용 채널을 해제합니다."},
  {"c": "관리", "cmd": "!초대허용목록", "d": "Discord 초대 링크가 허용된 채널을 확인합니다."},
  {"c": "관리", "cmd": "!신생계정알림 켜기 7", "d": "기준 일수보다 새 계정이 가입하면 보안 로그로 알립니다."},
  {"c": "편의", "cmd": "!내경고", "d": "자신의 활성 경고와 최근 제재 기록을 DM으로 확인합니다."},
  {"c": "관리", "cmd": "!제재기록 [@멤버] 10", "d": "운영진이 서버 전체 또는 특정 멤버의 최근 제재 기록을 확인합니다."},
  {"c": "관리", "cmd": "!운영편의도움말", "d": "셀프 역할, 가입자 점검과 일반 편의 명령을 안내합니다."},
  {"c": "관리", "cmd": "!셀프역할추가 🎮 @역할 설명", "d": "셀프 역할 패널에 사용할 이모지, 역할과 설명을 등록합니다."},
  {"c": "관리", "cmd": "!셀프역할삭제 🎮", "d": "등록된 셀프 역할 항목을 이모지로 삭제합니다."},
  {"c": "관리", "cmd": "!셀프역할목록", "d": "현재 등록된 셀프 역할 항목을 확인합니다."},
  {"c": "관리", "cmd": "!셀프역할패널 제목", "d": "현재 채널에 반응형 셀프 역할 패널을 생성합니다."},
  {"c": "관리", "cmd": "!셀프역할패널목록", "d": "저장된 셀프 역할 패널의 채널과 메시지 ID를 확인합니다."},
  {"c": "관리", "cmd": "!셀프역할패널삭제 메시지ID", "d": "셀프 역할 패널 등록과 메시지를 삭제합니다."},
  {"c": "관리", "cmd": "!최근가입 10", "d": "최근 서버에 가입한 멤버와 계정 나이를 확인합니다."},
  {"c": "관리", "cmd": "!의심계정 7 20", "d": "생성된 지 얼마 안 된 계정을 운영 점검용으로 표시합니다."},
  {"c": "관리", "cmd": "!역할멤버 @역할 30", "d": "특정 역할을 가진 멤버 목록을 확인합니다."},
  {"c": "편의", "cmd": "!아바타 [@멤버]", "d": "자신 또는 멘션한 멤버의 프로필 이미지를 표시합니다."},
  {"c": "편의", "cmd": "!서버아이콘", "d": "현재 서버 아이콘의 원본 이미지를 표시합니다."},
  {"c": "편의", "cmd": "!가입일 [@멤버]", "d": "Discord 계정 생성일과 현재 서버 가입일을 표시합니다."},
  {"c": "편의", "cmd": "!핑", "d": "아바돈의 Discord 연결 지연시간을 표시합니다."},
  {"c": "기본", "cmd": "!명령어", "d": "목록"},
  {"c": "관리", "cmd": "!운영초기설정", "d": "SERVER GUARD 운영 채널과 기본 설정을 초기 연결합니다."},
  {"c": "관리", "cmd": "!운영진단", "d": "운영 모듈 등록 상태와 필요한 권한을 진단합니다."},
  {"c": "관리", "cmd": "!운영강화설정", "d": "자동 이모지, 첨부 스마트 반응과 격리 역할을 자동 구성합니다."},
  {"c": "관리", "cmd": "!운영대시보드", "d": "SERVER GUARD 설정과 자동 기능 상태를 한 화면에 표시합니다."},
  {"c": "관리", "cmd": "!봇권한", "d": "현재 서버와 채널에서 아바돈의 관리 권한을 점검합니다."},
  {"c": "관리", "cmd": "!운영설정내보내기", "d": "게임 데이터 없이 현재 서버 운영 설정만 JSON 파일로 내보냅니다."},
  {"c": "관리", "cmd": "!운영메모 내용", "d": "관리자 로그용 운영 메모를 번호와 함께 저장합니다."},
  {"c": "관리", "cmd": "!운영메모목록", "d": "최근 저장된 운영 메모를 확인합니다."},
  {"c": "관리", "cmd": "!채널정보 #채널", "d": "채널 주제, 슬로우모드와 주요 권한을 확인합니다."},
  {"c": "관리", "cmd": "!역할정보 @역할", "d": "역할 서열, 인원, 핵심 권한과 봇 관리 가능 여부를 확인합니다."},
  {"c": "관리", "cmd": "!대화금지 @유저 사유", "d": "현재 채널에서 특정 멤버의 메시지와 반응을 제한합니다."},
  {"c": "관리", "cmd": "!대화허용 @유저", "d": "대화금지 전의 채널 권한 상태로 복구합니다."},
  {"c": "관리", "cmd": "!투표종료 메시지ID", "d": "아바돈이 만든 투표의 반응 수를 집계하고 결과를 표시합니다."},
  {"c": "관리", "cmd": "!자동이모지 상태", "d": "자동 반응의 채널·키워드·첨부·프리셋 설정을 확인합니다."},
  {"c": "관리", "cmd": "!이모지자동설정", "d": "채널 이름을 분석해 적절한 자동 이모지 프리셋을 연결합니다."},
  {"c": "관리", "cmd": "!이모지프리셋목록", "d": "기본 프리셋과 서버 사용자 프리셋을 확인합니다."},
  {"c": "관리", "cmd": "!이모지프리셋추가 이름 | 이모지", "d": "서버 전용 자동 반응 프리셋을 추가하거나 갱신합니다."},
  {"c": "관리", "cmd": "!이모지프리셋삭제 이름", "d": "서버 전용 자동 반응 프리셋을 삭제합니다."},
  {"c": "관리", "cmd": "!이모지첨부반응 켜기", "d": "사진, 영상, 음성, 파일 유형별 스마트 자동 반응을 켭니다."},
  {"c": "관리", "cmd": "!이모지최대개수 5", "d": "메시지 하나에 추가할 자동 반응 최대 개수를 설정합니다."},
  {"c": "관리", "cmd": "!이모지웹훅 켜기", "d": "웹훅 메시지에도 자동 이모지를 추가할지 설정합니다."},
  {"c": "관리", "cmd": "!안티레이드 켜기", "d": "짧은 시간의 대량 가입을 감지하는 안티레이드를 활성화합니다."},
  {"c": "관리", "cmd": "!비상모드 켜기", "d": "안티레이드, 인증 강화, 서버 잠금과 신규 격리를 함께 적용합니다."},
  {"c": "관리", "cmd": "!서버점검", "d": "역할 서열, 권한, 로그 채널과 주요 운영 설정을 점검합니다."}
];
const categories = ["전체", ...new Set(commands.map((item) => item.c))];

function initSharedUI() {
  const cfg = window.ABADDON_CONFIG || {};
  document.querySelectorAll("[data-version]").forEach((el) => { el.textContent = cfg.version || "v4.3.0"; });
  document.querySelectorAll("[data-status]").forEach((el) => { el.textContent = cfg.statusText || "ONLINE"; });
  document.querySelectorAll("[data-status-note]").forEach((el) => { el.textContent = cfg.statusNote || "SERVER GUARD"; });
  document.querySelectorAll("[data-discord-link]").forEach((el) => { el.href = cfg.discordInvite || "#"; el.target = "_blank"; el.rel = "noopener"; });
  document.querySelectorAll("[data-bot-link]").forEach((el) => { el.href = cfg.botInvite || cfg.discordInvite || "#"; el.target = "_blank"; el.rel = "noopener"; });

  const current = location.pathname.split("/").pop() || "index.html";
  document.querySelectorAll(".site-nav a").forEach((link) => {
    const target = (link.getAttribute("href") || "").split("#")[0];
    if (target === current) link.classList.add("active");
  });

  const button = document.querySelector("[data-menu-button]");
  const nav = document.querySelector("[data-site-nav]");
  if (button && nav) {
    button.addEventListener("click", () => nav.classList.toggle("open"));
    nav.addEventListener("click", () => nav.classList.remove("open"));
  }
}

function initCommandPage() {
  const grid = document.getElementById("command-grid");
  if (!grid) return;
  const search = document.getElementById("command-search");
  const tabs = document.getElementById("category-tabs");
  const meta = document.getElementById("command-meta");
  const empty = document.getElementById("empty-state");
  let category = "전체";

  function renderTabs() {
    tabs.innerHTML = "";
    categories.forEach((name) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "category-button" + (name === category ? " active" : "");
      button.textContent = name;
      button.addEventListener("click", () => { category = name; renderTabs(); renderCommands(); });
      tabs.appendChild(button);
    });
  }

  function renderCommands() {
    const query = (search.value || "").trim().toLocaleLowerCase("ko-KR");
    const filtered = commands.filter((item) => {
      const categoryOk = category === "전체" || item.c === category;
      const text = `${item.cmd} ${item.d} ${item.c}`.toLocaleLowerCase("ko-KR");
      return categoryOk && (!query || text.includes(query));
    });
    grid.innerHTML = "";
    filtered.forEach((item) => {
      const card = document.createElement("article");
      card.className = "command-card";
      const top = document.createElement("div");
      top.className = "command-top";
      const code = document.createElement("code");
      code.textContent = item.cmd;
      const label = document.createElement("span");
      label.className = "category-label";
      label.textContent = item.c;
      top.append(code, label);
      const desc = document.createElement("p");
      desc.textContent = item.d;
      card.append(top, desc);
      grid.appendChild(card);
    });
    meta.textContent = `전체 ${commands.length}개 중 ${filtered.length}개 표시`;
    empty.style.display = filtered.length ? "none" : "block";
  }

  search.addEventListener("input", renderCommands);
  renderTabs();
  renderCommands();
}

document.addEventListener("DOMContentLoaded", () => { initSharedUI(); initCommandPage(); });
