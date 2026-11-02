# MARKUST Beauty Workflow Skills

MARKUST 뷰티 비포·애프터 이미지와 편집 가능한 Canva 브릿지 썸네일을 제작하는 두 Codex 스킬입니다.

| 스킬 | 역할 |
|---|---|
| `artifact-template-markust` | 비포·중간·애프터 PNG 3장, 각 4각도 제작 및 검수 |
| `markust-bridge-page-thumbnail-canva` | 소구점별 영어 문구와 편집 가능한 1600×1600 Canva 4페이지 제작·검수·팀 폴더 저장 |

각 스킬을 단독으로 사용하거나 함께 호출할 수 있습니다. 함께 호출하면 영상 분석·제품 근거·인물 기준을 한 번 정리하고, 검수한 이미지와 작업 기록을 Canva 단계에 전달합니다.

## 설치

이 저장소를 내려받은 뒤 두 스킬 폴더를 사용자 스킬 디렉터리에 복사하세요. macOS/Linux의 기본 위치는 `~/.agents/skills/`입니다. 기존 같은 이름의 스킬을 업데이트할 때는 해당 폴더를 먼저 백업하세요.

```bash
mkdir -p ~/.agents/skills
cp -R artifact-template-markust ~/.agents/skills/
cp -R markust-bridge-page-thumbnail-canva ~/.agents/skills/
```

Codex에서 새 대화를 열고 두 스킬이 표시되는지 확인하세요. 이미지 생성 기능과 Canva 연결은 각 사용자의 환경에서 사용할 수 있어야 합니다. 로컬 렌더링에는 Python 3.10+와 Pillow가 필요합니다. 응답 저장 JS 도우미는 Codex 도구 실행 환경에서 사용합니다.

개인 기본 팀은 최초 실행 시 A/B/C 중 선택합니다. 개인 설정은 설치 폴더 밖에 저장되며 이 저장소에 포함하지 않습니다. 공개 배포본의 `markust-bridge-page-thumbnail-canva/references/team-folders.json`은 실제 팀 폴더 ID·링크를 비운 초기 설정입니다. 관리자에게 받은 팀 폴더 링크를 각 설치 환경에서 등록하고 Canva 접근 권한을 확인하세요. 기존 설치를 업데이트할 때는 설정된 이 파일을 먼저 별도 백업한 뒤 자신의 설정을 유지하세요.

폴더 등록 예시(아래 값은 실제 팀 링크로 교체):

```bash
python3 ~/.agents/skills/markust-bridge-page-thumbnail-canva/scripts/team_routing.py register-folder --team B --folder-url "ADMIN_PROVIDED_CANVA_FOLDER_URL"
```

## 사용 예시

```text
$artifact-template-markust $markust-bridge-page-thumbnail-canva
첨부 영상에서 소구점을 파악하고, 영상의 인물 조건을 반영한 비포·애프터와 브릿지 썸네일 4장을 제작해줘. B팀 폴더에 저장해줘.
```

문구만 수정할 때는 Canva 스킬과 대상 디자인을 지정합니다. 기존 스타일을 유지하면서 문구 교체 또는 여백 설명 추가 경로를 사용합니다.

## 품질과 실행 기록

- 네 페이지는 서로 다른 소구점 하나씩 다룹니다.
- 사진 수·각도·해상도, 자연스러운 변화와 비교 검수 기준을 유지합니다.
- 실제 Canva 최종 미리보기, 개별 편집성, 도구가 요구하는 저장 승인, 제목·페이지 수·팀 폴더 확인을 수행합니다.
- 생성 비교 이미지를 실제 사용 결과로 주장하지 않습니다.
- 변경 없는 분석·이미지·크롭은 검수 상태와 파일 해시를 확인해 재사용합니다.
- 원본 도구 응답은 작업 폴더에 보존하고, 모델에는 오류·부분 성공·변경 속성을 요약합니다.

세부 실행 기준은 각 폴더의 `SKILL.md`를 확인하세요. `skill-manifest.sha256`은 배포에 포함된 두 스킬 파일의 해시입니다. 스킬 코드·지침·이미지는 설치본과 동일하며, 실제 팀 폴더 설정만 공개 배포용 초기값으로 바꿨습니다. 사용자 영상·작업 결과·로그인 정보·개인 설정은 배포에 포함하지 않습니다.

## 로컬 회귀 검사

아래 검사는 네트워크·Canva 수정·이미지 생성을 실행하지 않습니다.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s markust-bridge-page-thumbnail-canva/scripts -p 'test_*.py'
node markust-bridge-page-thumbnail-canva/scripts/test_receipt_runtime.cjs
```
