# 프롬프트 작성 예시

피부 편집을 하는 매 호출에 편집 대상, 바꿀 피부 부위, 그대로 유지할 요소를 적는다. 아래 문구는 대상 인물·소구점·원본 역할에 맞게 채운다. 고정한 실제 사용 기간, 개선율, 임상 수치를 만들지 않는다.

**처음부터 썸네일 크기에서 바로 읽히는 초기·최종 대비를 기본값으로 명시한다.** ‘barely perceptible’, ‘very subtle’, ‘slightly more’만으로 첫 비포의 강도를 지시하지 않는다. 차이를 만드는 부위와 특징을 구체적으로 쓰고, 생성 후 축소 비교가 부족하면 사용자 재요청 없이 그 부위만 조정한다. 첫 비포의 차이를 더 보이게 하는 지시도 현재 소구점에 한정한다. 아래 주름·붉은기 예시는 그 소구점이 있을 때만 사용하며, 다른 소구점에 주름·홍조를 자동으로 추가하지 않는다.

## 네 각도 기준 이미지

```text
Use case: identity-preserve.
The user-provided photo is the identity and [BEFORE / AFTER] skin-state reference.
Create one wide landscape sheet, exactly four equal portrait panels in one horizontal row.
Left to right: front 0 degrees; about 30 degrees facing screen right; about 40 degrees facing screen right; true 90-degree right-facing profile. 30 is visibly more frontal than 40.
Show the full head through collarbones, with consistent face scale, eye-line and thin white vertical dividers.
Preserve this person's identity, apparent age, face proportions, hair, clothing, makeup, gentle expression, background, lighting, exposure and white balance.
Match the reference skin state without adding improvement or worsening at this anchor stage. Keep real pores and natural mature skin details.
No text, numerals, titles, captions, date labels, logos or watermarks.
```

## 세 상태: 비포·중간·애프터

새 인물의 동일 기준 사진을 편집 대상으로 삼아 각 단계를 별도로 만든다. 상태를 자연어로 구별하고, 한 이미지의 상태만 요청한다.

- 첫 비포: 지정된 원본 역할을 지키면서 소구점과 관련한 초기 상태. 정면 컷을 폭 약 320–400px로 축소해 최종 애프터와 나란히 봐도 차이가 바로 보이게 한다. 애프터 기준 원본이면 해당 국소 피부 특징을 충분히 눈에 띄게 만든다. 건강한 인상과 자연스러운 피부결을 유지한다. 비포 기준 원본이면 첫 비포를 임의로 악화시키지 않는다.
- 중간: 비포보다 해당 특징이 일부 줄었지만 애프터보다 남아 있는 상태. 양 끝과 구분되는 중간 상태 한 장만 만든다.
- 애프터: 지정된 원본 역할을 지키는 최종 상태. 애프터 기준 원본이면 그 피부 수준을 유지한다. 별도의 애프터 직전 이미지는 만들지 않는다.

```text
Use case: identity-preserve.
Edit this four-angle sheet to the [before / middle / final after] skin stage.
Change only [specific facial skin regions and visible concern].
The intended stage is [describe the remaining concern and how it differs from the adjacent stages].
The DEFAULT early-to-final contrast must be clearly visible at normal thumbnail size (each front portrait approximately 320–400 pixels wide), without zooming, flickering or explanatory captions. Do not default to a barely perceptible edit. If more than one visible concern is specified, make the contrast readable for each concern, not only one of them. Preserve the designated source anchor; do not exaggerate age or alter the entire face to create contrast.
Keep identity, age, face geometry, eyes, nose, lips, expression, hair, clothing, neck/chest, four poses, crop, panel separators, background, lighting, exposure, white balance and sharpness unchanged.
Keep ordinary photographic pores and age-appropriate fine lines.
Do not use altered lighting, makeup, whitening or younger facial features to suggest improvement.
Do not add rough global microtexture, crosshatching, cracks, patterned lines or unrelated blemishes.
Return only one four-column sheet, with no text anywhere.
```

## 주름·붉은기 적용 예시

붉은기는 볼 중심과 코 옆의 부드러운 국소 색감으로 표현하되 첫 비포에서는 썸네일 크기로도 분명히 보이게 한다. 얼굴 전체를 붉게 칠하지 않는다. 주름은 눈가, 눈 밑, 이마에서 자연스러운 얕은 선의 개수·선명도를 충분히 구분한다. 볼·턱·목의 피부결에 새로운 선을 추가하지 않는다. 중간은 그 강조를 일부 줄이되 애프터보다 흔적이 남도록 한다. 애프터 기준 원본을 받은 경우 원본보다 더 매끈한 피부로 만들지 않는다.

애프터 기준 사진에서 첫 비포를 만드는 국소 변화 지시 예시:

```text
Create the earliest BEFORE from this AFTER anchor. Keep the final After skin level unchanged.
Make the first-to-final contrast clearly visible at ordinary thumbnail size from the first attempt, while retaining healthy, believable skin and the same apparent age.
Make shallow fine lines visibly more defined or more numerous only at the eye corners, under the eyes and on the forehead. Make a soft localized rosy flush distinctly visible in the central cheeks and beside the nose, not just faintly pink under magnification.
The difference should read at thumbnail size without relying on changed lighting or globally red skin. Keep the neck, chest, cheek texture, facial geometry and all non-target details unchanged.
Do not add deep folds, etched or intersecting patterns, widespread rough texture, severe inflammation or unrelated blemishes. No text or labels.
```

## 다른 소구점의 국소 표현

아래는 해당 소구점이 실제로 포함된 경우에만 사용한다. 수치·기간·임상 효능이 아닌 설명용 피부 상태의 시각적 차이를 지정한다.

- **모공:** 코와 인접한 안쪽 볼의 불규칙한 개별 모공이 축소 미리보기에서도 구분되도록 가시성을 조절한다. 검은 점·여드름·큰 구멍·지문 같은 물결무늬로 바꾸지 않는다. 주름이나 붉은기는 별도 소구점일 때만 바꾼다.
- **잡티·피부톤:** 국소 색소 흔적과 얼룩져 보이는 정도를 구분한다. 노출·화이트밸런스·얼굴 전체 미백으로 대비를 대신하지 않는다.
- 첫 비포와 애프터의 차이가 작으면 ‘더 강하게’만 반복하지 말고 해당 부위의 개수·분포·선명도 중 무엇을 바꿀지 구체적으로 적는다. 모든 특징을 동시에 과장하지 않는다. 피부 전체의 반복 무늬나 거친 질감은 차이가 아니라 수정할 결함이다.
