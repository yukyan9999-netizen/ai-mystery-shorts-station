# AI 지식 미스터리 쇼츠 방송국

역사·우주·고대문명·과학·자연 미스터리와 가상 시나리오를 흥미 중심으로
선정하고, 사실·학설·기록·전승·목격 주장을 구분해 60초 쇼츠 제작 패키지로 만드는 Python
멀티 에이전트 프로젝트입니다.

커뮤니티 썰 크롤링, 사연 필터, 웃긴 사연 각색 기능은 비활성화되었습니다.
AI는 사용자가 제작 버튼을 누를 때만 실행되며, 최종 업로드 전 사람 승인이
반드시 필요합니다.

## 담당 AI

- `ScheduleManager`: 요일별 카테고리 순환 편성
- `TopicGenerator`: 후보 3개 생성 및 100점 평가
- `FactChecker`: 소재를 탈락시키기보다 사실·학설·전승·주장 등급 분류
- `SourceResearcher`: 국내외 커뮤니티·공식자료·공개 아카이브 조사
- `KnowledgeScriptWriter`: 0~60초 구조의 대본 작성
- `VisualPromptGenerator`: 장면별 이미지 프롬프트, 자막, 썸네일 생성
- `MixedMediaPlanner`: 실제 자료 50~85%와 AI 재구성 장면 혼합
- `ProductionManager`: 실행 상태와 사람 승인 관리

## 자동 편성

- 월: 역사 미스터리
- 화: 우주 미스터리
- 수: 고대문명과 놀라운 기술
- 목: 과학·자연 미스터리
- 금: 가상 시나리오
- 토: 역사/우주 중 최근 고득점 카테고리
- 일: 주간 최고 점수 아이템 리메이크

각 실행에서 AI는 후보를 정확히 3개 만들고 멈춥니다. 관제실에서 사람이
`이 주제로 제작`을 눌러 하나를 채택해야 이후 자료조사와 대본 제작이 진행됩니다.
후킹 35점, 출처 추적 가능성
10점, 시각화 25점, 60초 구성 20점, 댓글 유도 10점으로 평가합니다.
70점 이상만 제작 후보, 85점
이상은 우선 제작 후보입니다. 후보 중 팩트체크를 통과한 최고 점수 아이템으로
대본과 비주얼 패키지를 생성합니다.

## 설치

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

프로젝트 루트의 `.env.local` 또는 `.env`에 API 키를 저장합니다.

```text
OPENAI_API_KEY=sk-...
```

## 실행

오늘 편성만 확인:

```powershell
.\.venv\Scripts\python.exe src\run_knowledge_station.py --schedule
```

후보 3개부터 최종 제작 패키지까지 실행:

```powershell
.\.venv\Scripts\python.exe src\run_knowledge_station.py
```

위 명령은 후보 3개까지만 생성합니다. 사람 선택 후 이어서 제작:

```powershell
.\.venv\Scripts\python.exe src\run_knowledge_station.py --select-run 실행번호 --candidate-index 0
```

특정 날짜 편성 실행:

```powershell
.\.venv\Scripts\python.exe src\run_knowledge_station.py --date 2026-06-22
```

관제실 실행:

```powershell
.\.venv\Scripts\python.exe src\dashboard.py
```

브라우저에서 `http://127.0.0.1:8765/`를 엽니다.

## 저장 결과

```text
agents/                          역할별 독립 프롬프트
ideas/knowledge_items.json       후보·점수·제작 상태 기록
ideas/topic_library.json         지금까지 발굴한 소재 누적 보관함
ideas/video_references.json      사용자 제공 레퍼런스 링크
ideas/reference_style_profile.json 레퍼런스에서 추출한 편집 원칙
outputs/knowledge/<run_id>/
  00_schedule.json
  01_topic_candidates.json
  02_fact_check_*.json
  03_source_research.json
  04_script.json
  05_visual_package.json
  06_mixed_media_plan.json
  final_knowledge_short.json
```

`final_knowledge_short.json`에는 선정 아이템, 100점 평가, 사실성 등급,
국내외 자료 목록, 라이선스 상태, 실제 자료와 AI 장면의 혼합 계획,
60초 대본, 장면별 이미지 프롬프트, 자막, 내레이션, 썸네일 문구,
해시태그가 포함됩니다.

JSON 제작 패키지와 실제 MP4 렌더링은 사람 선택·승인 단계로 분리되어 있습니다.
YouTube 업로드는 자동 실행되지 않습니다. 관제실에서
`승인하고 영상 제작`을 누르면 실제 자료 다운로드, 필요한 AI 보완 장면 생성,
TTS, 자체 BGM, 자막 합성을 거쳐 `final_short.mp4`가 생성됩니다.

완성 영상 파일:

```text
outputs/knowledge/<run_id>/final_short.mp4
outputs/knowledge/<run_id>/thumbnail.png
outputs/knowledge/<run_id>/render_manifest.json
```

이미 MP4가 존재하면 승인 버튼을 다시 눌러도 기존 결과를 재사용하여 중복
API 비용을 막습니다.

## 소재 방향 지정과 누적 보관함

관제실의 `원하는 소재 방향`에 `우주`, `로마 역사`, `고대 이집트`,
`UFO 목격담`처럼 입력한 뒤 후보 생성 버튼을 누르면 해당 방향을 우선합니다.
입력칸을 비워두면 요일별 자동 편성이 그대로 적용됩니다.

CLI에서도 지정할 수 있습니다.

```powershell
.\.venv\Scripts\python.exe src\run_knowledge_station.py --direction "로마 역사"
```

발굴된 모든 후보는 `ideas/topic_library.json`에 누적됩니다. 같은 핵심 제목은
새 항목으로 중복 저장하지 않고 발견 횟수, 최근 발견일, 최고 점수와 지정
방향을 갱신합니다. 관제실의 `누적 소재 보관함`에서 분야별로 검색할 수 있습니다.

## 미스터리 과장·재구성 정책

- 사실성이 약한 예언, UFO, 초능력, 괴담, 목격담도 제작 후보로 허용합니다.
- 조작 의혹이나 진위 논쟁 자체도 반전 소재로 활용합니다.
- 극적 후킹, 가상의 대화, 여러 기록을 합친 압축 재구성, AI 장면을 허용합니다.
- 화면에는 `미스터리 재구성`, `목격자 주장`, `진위 미확인`, `AI 재구성`
  같은 짧은 라벨을 사용합니다.
- 사실성 부족만으로 탈락시키지 않습니다. 실존 개인에 대한 중대한 허위
  범죄 주장, 개인정보 노출, 위험 행동 유도처럼 심각한 안전 문제만 보류합니다.

## 레퍼런스 기반 영상 스타일

- 굵은 고딕 흰색 자막과 검은 외곽선, 핵심 단어의 빨간색 강조
- 실제 사진·유물·문서를 화면 중심에 크게 배치
- 가로 자료는 같은 이미지를 어둡게 블러 처리한 배경 위에 중앙 배치
- 내부 프롬프트, 편집 지시, 영문 사실성 코드, 긴 출처 설명은 화면에 출력 금지
- 사실성 표시는 좌측 하단의 짧은 한글 라벨만 사용
- 반복 줌과 흔들림 없이 정지 화면 중심으로 편집
- `cedar` 음성을 사용한 낮고 심각한 미스터리 다큐 내레이션

완성 영상 카드의 `레퍼런스 스타일로 재제작` 버튼을 누르면 기존 이미지
자료는 재사용하고 프레임·자막·TTS·BGM·MP4만 다시 만듭니다.

## MYSTERY DOCUMENTARY AI STUDIO v3.0

제작 철학은 다음 한 줄입니다.

```text
검증된 현실 → 조사 → 뜻밖의 질문 → 인간적 결과 → 문명적 결과
→ 존재론적 질문 → 잊히지 않는 결말
```

후보 생성 단계:

1. `TrendAnalyst`: 최근 관심 신호와 기회 점수 분석
2. `TopicHunter`: 현실에서 출발하는 미스터리 후보 3개 생성
3. 사람: 세 후보 중 실제 제작할 하나를 선택

선택 이후 제작 단계:

1. `ScientificResearcher`와 `HistoricalResearcher`가 동시에 조사
2. `HumanCuriosityDirector`가 사실을 인간적인 질문으로 변환
3. `FutureConsequenceSimulator`가 개인·사회·문명 파급을 계산
4. `GihwanAgent`가 “그다음은?” 질문을 연쇄 확장
5. `MysteryArchitect`가 반전 공개 시점을 포함한 서사를 설계
6. `KnowledgeScriptWriter`가 60초 다큐 대본 작성
7. `AudienceSimulator`가 CTR·유지율·댓글·혼란 지점을 예측
8. `FactChecker`가 FACT·THEORY·SPECULATION을 최종 분리
9. 비주얼 디렉터가 실제 증거 자료 우선의 장면·혼합 편집안 생성
10. 사람 승인 후에만 MP4 제작

각 단계는 다음 파일로 즉시 저장되므로 중단 후 같은 실행번호를 다시 선택하면
완료된 단계는 재사용하고 미완료 단계부터 이어집니다.

```text
outputs/knowledge/<run_id>/
  00_schedule.json
  01_trend_report.json
  01_topic_candidates.json
  02_scientific_research.json
  03_historical_research.json
  04_curiosity_report.json
  05_consequence_report.json
  06_gihwan_report.json
  07_narrative_architecture.json
  08_script.json
  09_audience_simulation.json
  10_fact_check.json
  11_source_research.json
  12_visual_package.json
  13_mixed_media_plan.json
  final_knowledge_short.json
```

미스터리의 추정과 극적 확대는 허용하지만, 적어도 하나의 검증된 현실에서
출발하고 사실·학설·가정은 서로 다른 것으로 표시합니다.

## 사용자 제공 유튜브 레퍼런스

처음 제공된 유튜브 쇼츠 10개는 `ideas/video_references.json`에 누적 저장되어
있으며 `ideas/reference_style_profile.json`의 공통 연출 원칙과 함께 다음
담당자에게 자동 전달됩니다.

- 트렌드 분석과 주제 후보 선정
- 호기심 질문과 미스터리 구조 설계
- 60초 대본의 문장 길이와 정보 공개 속도
- 시청자 이탈 지점 평가
- 실제 자료 조사와 장면별 비주얼 구성
- 실제 자료·AI 재구성 혼합 편집

관제실의 오늘 편성 카드에서 현재 연결된 레퍼런스 개수를 확인할 수 있고,
`/api/references`에서 저장된 링크와 적용 담당자를 확인할 수 있습니다.

## 사고 설계 REFERENCE LIBRARY v1.0

사용자가 제공한 13개의 사고 설계 사례는
`ideas/concept_reference_library.json`에 별도로 저장됩니다.

대표 패턴:

- 과학 → 사회 → 정체성 → 존재론
- 과학 → 법 → 국가 → 문명
- 과학 → 뇌 → 의식 → 시간 → 공포
- 과학 → 사회 → 경제 → 문명 → 붕괴
- 역사 → 현대 → 재해석
- 상식 → 반전 → 재해석

호기심 연출자, 미래 파급 시뮬레이터, 기환, 미스터리 설계자, 대본 작가는
현재 주제에 맞는 패턴을 반드시 1~3개 선택합니다. 선택 결과는 각 단계 JSON의
`reference_patterns_used`에 저장되며, 시청자 시뮬레이터가 실제 반영 여부를
`reference_pattern_assessment`로 다시 검사합니다.

## 최종 대본 사람 검토

제작 패키지가 완성되어도 MP4 제작은 바로 시작되지 않습니다.

1. 에피소드 카드의 `최종 대본 검토` 버튼을 누릅니다.
2. 0~3초 후킹부터 50~60초 결말까지 시간대별 대본과 실제 TTS 내레이션을 확인합니다.
3. 수정이 필요하면 피드백을 작성하고 `피드백 반영 요청`을 누릅니다.
4. 작가 AI가 대본을 다시 작성하고 시청자 검토·팩트 검토·장면 설계를 갱신합니다.
5. 수정본을 다시 읽고 `이 대본 승인하고 영상 제작`을 눌러야 MP4 제작이 시작됩니다.

피드백과 수정본은 실행 폴더의 `script_feedback_XX.json`,
`08_script_revision_XX.json`에 누적되어 이전 수정 기록도 남습니다.

## 로컬 배경음악 라이브러리

영상 제작 시 프로젝트의 `music/` 폴더에 있는 음원을 우선 사용합니다.
음악 담당 AI는 제목·카테고리·대본 키워드로 분위기를 판단합니다.

- `The Unseen Architecture (1).mp3`: 우주·UAP·시간·미지의 공간
- `Shock Fact.mp3`: 충격적 사실·과학 반전·심리 미스터리
- `The Unseen Architecture.mp3`: 역사·고대문명·제도·문명적 여운

선택한 곡은 원본 파일의 시작 지점과 음색을 유지하며 정규화·페이드·재편집 없이
내레이션 아래에 믹싱합니다. 영상보다 짧을 때만 처음부터 반복하고, 최종 믹스에서는
내레이션을 가리지 않도록 배경음악 볼륨만 조절합니다. 결과는 `music_selection.json`,
`render_manifest.json`과 에피소드 카드에 기록됩니다.

## 내레이션 기준 화면 전환

장면의 예상 시간표보다 실제 TTS 음성이 길더라도 음성을 자르지 않습니다.
각 장면의 WAV 길이를 측정한 뒤 문장이 끝나고 약 0.35초의 여유가 지난 시점에
다음 화면으로 전환합니다.

권장 길이는 90초이고 절대 최대 길이는 120초입니다. 60초에 맞추기 위한
음성 절단이나 부자연스러운 속도 증가는 하지 않습니다. 실제 내레이션 기준
120초를 넘으면 영상을 자르지 않고 대본 축약이 필요하다는 오류를 표시합니다.

`render_manifest.json`의 `scene_timing`에는 장면별 예상 시간, 실제 내레이션
시간, 최종 화면 유지 시간과 기존 방식에서 잘릴 수 있었던 시간이 기록됩니다.

## 프로젝트 매니저 60초 개입

모든 미스터리 제작 에이전트는 공통 실행 감시기를 사용합니다.

- 10초마다 담당자의 경과 시간과 응답 대기 상태를 관제실에 표시
- 한 담당자가 60초를 넘기면 한실장 AI가 병목을 판단
- 필수 근거·안전·출력 형식은 유지하고 장황한 설명과 중복 검토를 줄이도록 지시
- 담당자는 관리자 지시를 받아 최대 45초 동안 긴급 재처리
- 긴급 처리도 실패하면 작업을 무한 대기시키지 않고 중단
- 이미 저장된 체크포인트는 유지되며 같은 에피소드를 실행하면 이어서 시작
## 쉬운 주제 우선 정책

주제 후보는 초등학교 고학년부터 성인까지 제목만 보고 상황을 바로 이해할 수 있어야 합니다.

- 제목은 42자 이하
- 배경 설명은 10초 이하
- 낯선 전문용어는 최대 2개
- `easy`를 우선하고 `hard`는 자동 탈락
- 탈락 후보는 관제실에서 제작 버튼을 표시하지 않음
- 어려운 후보가 생성되면 더 쉬운 각도로 한 번 자동 재선정

좋은 예시는 `달이 사라지면 바다는 어떻게 될까?`, `화성에서 태어난 사람은 지구에서 걸을 수 있을까?`처럼 익숙한 대상과 한 가지 질문이 결합된 주제입니다.

## 채널 마스터 레퍼런스

프로젝트 루트의 `REFERENCE_STYLE.md`는 소재 발굴과 대본 작성의 최상위 규칙입니다.

핵심 흐름은 `실제 사실 → 상상 가능한 미래 → 인간 영향 → 문명 영향`입니다. TopicHunter부터 연구, 호기심 확장, 미래 결과 시뮬레이션, 서사 설계, 대본 작성, 시청자 평가, 사실 검수까지 공통 적용됩니다.

## 스톡/NASA 짧은 영상 클립

영상 제작 단계에서만 `src/media_clip_selector.py`가 실행됩니다. 기존 소재 선정, 대본, 검수, 에이전트 프롬프트에는 영향을 주지 않습니다.

- NASA Scientific Visualization Studio(SVS)는 API 키 없이 검색
- NASA Image and Video Library는 API 키 없이 검색
- Pexels는 `.env.local`의 `PEXELS_API_KEY`가 있을 때 사용
- Pixabay는 `.env.local`의 `PIXABAY_API_KEY`가 있을 때 사용
- SVS는 Search API와 Page API에서 MP4를 찾고 원본 음성을 제거한 뒤
  1~4초만 사용합니다. 영상 자체에 별도 저작권이나 제3자 영상 문구가
  표시되면 자동 삽입하지 않고 `candidates_only`에만 저장합니다.
- 장면별 후보를 최소 3개 확보했을 때만 자동 선택
- 클립 하나는 1~4초
- 한 영상의 외부 클립 총합은 최대 20초
- 같은 원본은 최대 2회
- 나머지 시간과 장면은 기존 AI 이미지·정지 화면·모션그래픽으로 폴백

각 실행 폴더에 `timeline.json`과 `sources.md`가 생성됩니다. 검색 후보는
`media/stock/candidates/`, 라이선스가 불명확한 후보는
`media/stock/candidates_only/`에 메타데이터만 저장됩니다.

## 토픽헌터 직접 지정

관제실의 `토픽헌터와 바로 기획하기` 입력창에 대략적인 아이디어를 적고 `헌터와 상의하고 바로 대본 제작`을 누를 수 있습니다.

토픽헌터는 사용자의 핵심 아이디어를 유지하면서 한 개의 제작 주제로 다듬습니다. 후보 3개 선택 과정은 생략하며, 과학·역사 조사와 최종 대본 작성까지 자동 진행합니다. 영상 제작은 최종 대본을 사람이 승인한 뒤에만 시작됩니다.

## 최종 시나리오 직접 수정

완성 영상 또는 승인 대기 에피소드에서 `시나리오 수정 후 재제작`을 누르면
도입, 핵심 사실, 반전, 결론과 장면별 실제 TTS 대사를 직접 수정할 수 있습니다.
`수정본 저장` 후에는 기존 렌더 결과가 정리되고 다시 사람 승인 대기 상태가
됩니다. 수정 내용을 확인하고 승인하면 새 대사와 자막으로 영상을 다시
제작합니다.

최종 영상은 BGM 길이가 짧더라도 장면별 내레이션 전체 길이를 기준으로
렌더링합니다. 결론이나 마지막 장면보다 먼저 영상이 종료되면 제작 실패로
판정합니다.

대본 승인 화면의 `60초 자동 맞춤`을 선택할 수도 있습니다. 실제 TTS를
생성한 뒤 자연 길이가 60초보다 길고 72초 이하일 때만 말 속도를 필요한
만큼 높이며, 최대 속도는 1.2배입니다. 60초 이하이거나 72초를 넘는 경우에는
지나치게 느리거나 빠른 음성이 되지 않도록 원래 속도를 유지합니다.

## 쇼츠 각색 에디터

`KnowledgeScriptWriter`가 작성한 대본은 사람에게 제출되기 전에
`ShortsAdaptationEditor`를 한 번 거칩니다. 이 에이전트는 기존 대본만
입력받으며 웹 검색, 레퍼런스 자료, 다른 에이전트 보고서, 제작관리자의 대리
작성을 사용하지 않습니다.

각색 단계에서는 사실과 사실/가설 구분을 유지하면서 어려운 표현을 쉬운
말로 바꾸고, 문장을 짧게 나누며, 질문과 중간 반전의 간격을 조정합니다.
결과와 자체 점검은 실행 폴더의 `08_shorts_adaptation.json`, 실제 최종
완성된 영상에서도 `완성본 피드백·수정`을 눌러 AI 피드백 반영이나 직접
대본 수정을 다시 요청할 수 있습니다. 수정 전 MP4와 썸네일·타임라인은
`video_versions/version_XX.*`에 보관되며, 수정 대본을 사람이 다시 승인한
뒤 새 영상으로 교체 제작합니다.

완성 MP4를 재생하면 플레이어 아래의 `완성 영상 장면 피드백`에서
`10번 화면 누락 복구`, `9번 화면을 다른 NASA 영상으로 교체`처럼 장면
번호를 지정할 수 있습니다. 이 기능은 대본·TTS·BGM을 유지하고 지정 장면의
이미지·영상 자료만 다시 찾거나 생성한 뒤 전체 영상을 재렌더링합니다.
교체 전 영상은 `video_versions/`에 보관되며, 실패하면 이전 MP4를 복원합니다.

대본은 `08_shorts_adapted_script.json`에 저장됩니다. 사람 피드백으로
대본이 다시 작성될 때도 동일한 독립 각색 단계를 다시 거칩니다.
