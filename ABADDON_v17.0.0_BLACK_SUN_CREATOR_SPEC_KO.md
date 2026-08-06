# ABADDON v17.0.0 BLACK SUN CREATOR ERA

## 목표
기존 1,300여 개 기능을 보존하면서 실제 Discord 로그에서 확인된 런타임 오류를 닦고, 코드 수정 없이 서버 사건을 제작하는 공방과 서버 공동 시즌 6을 추가한다.

## 런타임 정책
- 실제 `commands.Cog` 인스턴스만 콜백의 첫 번째 인자로 전달한다.
- Interaction follow-up Webhook에는 `delete_after`를 전달하지 않는다.
- 삭제 예약은 반환된 메시지의 `delete()`를 비동기 예약한다.
- 사용자 저장 데이터가 Mapping이 아니면 성장·결과 집계를 건너뛴다.
- 같은 사용자·같은 명령의 오류 안내는 3초 동안 한 번만 보낸다.

## 콘텐츠 공방 데이터
`creator_forge_v1700.guilds.<guild_id>` 아래에 drafts, events, next_id를 저장한다.

사건은 한국어/English 제목과 설명, 2~5개 선택지, 결과, 보상, 희귀도, 제작자, 공개 상태를 가진다. 테스트 모드는 저장과 보상 정산을 하지 않는다. 공개 사건은 사용자별 1회 보상을 보장한다.

## 시즌 6 데이터
`season6_v1700.guilds.<guild_id>` 아래에 started, completed, chapter, stats, votes, history, participants, claims를 저장한다.

도시 지표는 hope, order, survival, abyss 네 종류다. 5개 장의 선택 효과를 누적해 최종 결말을 계산한다.

## 언어 정책
사용자의 선택 언어 하나만 출력한다. 데이터 키는 공통으로 저장하고 표시 시 한국어 또는 English 문구를 선택한다.

## 보존 정책
기존 명령·별칭·사용자 데이터·월드 데이터 키를 삭제하거나 이름 변경하지 않는다. v17.0은 추가 계층이다.
