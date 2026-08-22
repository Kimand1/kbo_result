# 2026 KBO 팀별 일별 순위

KBO 공식 웹사이트의 2026 시즌 데이터를 수집해 팀 순위와 경기 정보를 한 페이지에서 보여 주는 정적 웹 프로젝트입니다. 별도의 백엔드나 데이터베이스 없이 `index.html`에 데이터를 포함하며, GitHub Pages로 배포할 수 있습니다.

## 주요 기능

- 팀별 일별 순위, 1위와의 게임차, 승패 마진 그래프
- 최신 순위와 최근 10경기 성적
- 최근 완료 경기 결과와 팀별 필터
- 시즌 팀별 상대전적
- 다음 경기 일정, 예고 선발, 경기 미리보기 링크
- 연투 및 직전 경기 30구 이상 투구를 기준으로 한 불펜 체크
- 새 데이터 배포 시 `version.json`을 이용한 브라우저 자동 새로고침

페이지 상단의 **전체 표시**, **전체 숨김**, **현재 상위 5팀** 버튼으로 세 그래프에 표시할 팀을 바꿀 수 있습니다. 날짜 입력이나 **최근 10경기일**, **한달**, **두달**, **세달**, **전체 기간** 버튼을 사용하면 세 그래프의 조회 기간이 함께 변경됩니다. 최신 순위 표의 체크박스나 팀 행을 선택하면 최근 완료 경기 결과를 해당 팀 기준으로 필터링합니다.

## 요구 사항

- Python 3.10 이상
- 최신 Chrome, Edge, Firefox, Safari 등 JavaScript를 지원하는 브라우저
- 데이터 갱신 시 KBO 공식 웹사이트에 접속할 수 있는 인터넷 연결
- 그래프 표시 시 Chart.js CDN에 접속할 수 있는 인터넷 연결

Python 외부 패키지는 사용하지 않으므로 `pip install`이나 `requirements.txt` 설정은 필요하지 않습니다.

## 빠른 시작

저장소를 복제하고 프로젝트 디렉터리로 이동합니다.

```powershell
git clone https://github.com/Kimand1/kbo_result.git
cd kbo_result
```

정적 파일을 로컬 웹 서버로 실행합니다.

```powershell
python -m http.server 8000
```

브라우저에서 <http://localhost:8000>을 열면 됩니다. 서버를 종료하려면 터미널에서 `Ctrl+C`를 누릅니다.

> `index.html`을 파일로 직접 여는 것보다 로컬 웹 서버 사용을 권장합니다. 페이지가 최신 배포 여부를 확인하기 위해 `version.json`을 `fetch`로 읽기 때문입니다.

## Python 파일 사용법

### `update_kbo.py`

KBO 공식 웹사이트에서 다음 정보를 수집하고 정적 페이지 데이터를 갱신합니다.

- 정규시즌 최신 순위 및 일별 순위
- 완료 경기 일정과 점수
- 다음 경기 일정과 예고 선발
- 최근 투수 등판 기록을 이용한 불펜 체크

별도의 명령행 옵션은 없습니다. 어느 디렉터리에서 실행하더라도 스크립트가 있는 프로젝트 디렉터리의 파일을 갱신합니다.

```powershell
python update_kbo.py
```

정상 완료 시 다음 두 파일이 변경됩니다.

- `index.html`: 순위표, 그래프 데이터, 경기 결과, 상대전적, 다음 경기 정보
- `version.json`: 데이터 생성 시각과 최신 완료 경기 날짜

성공 메시지는 다음 형식으로 출력됩니다.

```text
Updated index.html through YYYY-MM-DD: N completed games, next games on YYYY-MM-DD
```

KBO 순위 또는 일별 순위 API 반영이 완료 경기 정보보다 늦으면, 스크립트는 수집한 완료 경기로 순위와 이력을 계산해 보완하고 안내 메시지를 출력합니다. 최신 박스스코어가 아직 없으면 이전 완료 경기일까지 거슬러 올라가 불펜 정보를 구성합니다.

스크립트는 `index.html`과 `version.json`을 직접 덮어씁니다. 실행 전 작업 트리를 확인하고, 실행 후 변경 내용을 검토하는 것이 좋습니다.

```powershell
git status --short
python update_kbo.py
git diff -- index.html version.json
```

현재 시즌과 개막일은 `update_kbo.py` 상단의 `SEASON`, `SEASON_START`에 2026년 기준으로 고정되어 있습니다. 다른 시즌에 사용하려면 이 값과 페이지 제목 등 시즌 표시를 함께 수정해야 합니다.

### `test_update_kbo.py`

완료 경기 판별, 공식 데이터 지연 시 순위 계산, 일별 순위 보완, 불펜 경고 조건, 동명이인 투수 식별 등을 검사하는 `unittest` 테스트입니다. 네트워크 요청은 발생하지 않습니다.

전체 테스트를 자세한 출력으로 실행합니다.

```powershell
python -m unittest -v
```

테스트 파일만 지정해서 실행할 수도 있습니다.

```powershell
python -m unittest -v test_update_kbo.py
```

특정 테스트 클래스나 테스트 하나만 실행하려면 점 표기법을 사용합니다.

```powershell
python -m unittest -v test_update_kbo.DelayedOfficialDataTest
python -m unittest -v test_update_kbo.DelayedOfficialDataTest.test_builds_standings_from_completed_games
```

## 권장 데이터 갱신 절차

```powershell
git switch main
git pull --ff-only origin main
python -m unittest -v
python update_kbo.py
git diff --check
git diff -- index.html version.json
python -m unittest -v
git add index.html version.json
git commit -m "Update KBO data through YYYY-MM-DD"
git push origin main
```

`main` 브랜치에 푸시하면 `.github/workflows/deploy-pages.yml`의 GitHub Actions 워크플로가 저장소 전체를 정적 사이트 아티팩트로 올리고 GitHub Pages에 배포합니다.

## 프로젝트 구조

| 경로 | 설명 |
| --- | --- |
| `index.html` | HTML, CSS, JavaScript와 현재 KBO 데이터가 포함된 단일 정적 페이지 |
| `version.json` | 브라우저의 최신 데이터 버전 확인에 사용하는 메타데이터 |
| `update_kbo.py` | KBO 데이터를 수집·검증하고 정적 파일을 갱신하는 스크립트 |
| `test_update_kbo.py` | 데이터 처리 및 불펜 판정 로직의 단위 테스트 |
| `.github/workflows/deploy-pages.yml` | `main` 푸시 시 GitHub Pages에 배포하는 워크플로 |

## 문제 해결

### KBO API 또는 테이블을 찾지 못했다는 오류

인터넷 연결과 <https://www.koreabaseball.com> 접속 여부를 확인한 뒤 다시 실행합니다. KBO 웹사이트의 응답 형식이나 HTML 구조가 변경되면 `update_kbo.py`의 파싱 로직도 수정해야 할 수 있습니다.

### 완료 경기가 없다는 오류

`No completed KBO games were available`은 설정된 시즌 개막일 이후 완료 경기 데이터를 찾지 못했다는 뜻입니다. `SEASON`, `SEASON_START` 값과 KBO 사이트의 해당 시즌 데이터 제공 여부를 확인합니다.

### 그래프가 보이지 않음

브라우저 개발자 도구의 네트워크 탭에서 Chart.js CDN 요청 실패 여부를 확인합니다. 광고 차단기, 사내 방화벽 또는 오프라인 환경이 CDN 로드를 막을 수 있습니다.

## 데이터 출처 및 참고 사항

데이터 출처는 [KBO 공식 웹사이트](https://www.koreabaseball.com)입니다. 이 프로젝트의 결과는 공식 기록을 편리하게 시각화하기 위한 것이며, 최종 기록은 KBO 공식 발표를 기준으로 확인하세요. 불펜 체크는 최근 등판과 투구 수를 기반으로 한 참고 정보로 실제 선수의 등판 가능 여부를 의미하지 않습니다.
