# ABADDON v13.3.0 명령 등록 보호기

## 정책
1. 기존에 등록된 명령과 별칭이 우선한다.
2. 새 명령의 별칭만 충돌하면 충돌 별칭만 제거하고 명령 본체는 등록한다.
3. 새 명령 이름 자체가 충돌하면 새 명령을 격리하고 전체 부팅은 계속한다.
4. 충돌 기록에는 토큰, 신규 명령, 기존 명령, 모듈, 줄 번호와 처리 결과를 남긴다.
5. 런타임 검수 명령에서 최근 처리 내역을 확인할 수 있다.

## 이번에 분리한 접근 이름
- 원정: `expedition` 유지 / 축제 탐험: `festivalexpedition`, `chaosadventure`
- 오늘의 운세: `fortune` 유지 / 축제 운세: `festivalfortune`
- 출석: `checkin` 유지 / 축제 출석: `festivalcheckin`
- 기존 등록번호 구매: `marketbuy` 유지 / 도시 거래: `citymarketbuy`
