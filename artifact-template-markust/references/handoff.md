# 같은 작업의 이미지 전달

Canva와 연결할 때만 읽는다. 추가 공통 스킬 설치는 필요 없다. 두 스킬은 하나의 사용자 작업 폴더를 공유한다.

- `brief.json`: 영상 경로/해시, 추출 장면·음성 근거, 제품 근거 파일, 사용자 인물 조건, sourceRole(before/after), appeal ID와 허용 변화 부위. Canva가 먼저 확정한다. 이미 기록된 분석을 다시 하지 않는다.
- `photos/handoff.json`: schemaVersion=1, briefFingerprint, sourceRole, identity constraints, assets, qa, promptsPath. assets의 각 항목에는 상대 path, sha256, state(before/middle/after), appealIds, approximateViews, provenance를 둔다. 각도·검수는 관찰 결과이지 자동 추정값이 아니다.
- qa에는 동일 인물/원본 고정/네 각도/상태 구분/320–400px 비교를 passed·failed·unverified와 근거 경로로 기록한다. 검수 통과한 관련 자산만 하류로 전달한다. 기본 세 상태를 따로 만들고 추가 소구점 pair는 필요한 경우에만 보충한다.
- 다른 소구점이 같은 그림으로 설명되지 않으면 전용 pair를 만든다. 같은 승인된 After 기준은 해당 피부 상태에 적합할 때만 공유한다. 중간을 소구점마다 불필요하게 다시 만들지 않는다.
- source/identity/age/anchor/appeal 조건, 실제 파일 해시와 qa가 모두 일치하면 같은 작업의 결과를 재사용한다. 파일 누락·수정 또는 조건 변경 시 영향을 받는 생성 단계부터 다시 수행한다. 실패/미확인 검수를 캐시 통과로 바꾸지 않는다.
- 독립 실행은 입력 정리 후 동일 형식의 전달 파일도 작성한다. Canva가 설치되어 있지 않아도 세 PNG 제작·전달은 완료된다.
