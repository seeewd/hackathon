# Archicad x Rhino-Grasshopper Gemini Node Builder (macOS)

## 목표
- Archicad 연결이 된 Grasshopper에서 자연어 요청을 Gemini에 보내고, Gemini가 만든 코드를 자동 추출해 노드/와이어를 생성

## 원하는 자동화 흐름
1. 사용자 입력: `"~~한 벽 만드는 노드 만들어줘"`
2. GhPython이 Gemini API 호출
3. Gemini 응답에서 `python code block` 자동 추출
4. 코드 DSL 검증(`node(...)`, `wire(...)`만 허용)
5. Grasshopper 캔버스에 노드 생성 + 와이어 연결
6. Archicad 컴포넌트로 전달

## 구현 파일
- GhPython 실행 스크립트: `scripts/ghpython_gemini_node_builder.py`
- Gemini 시스템 프롬프트: `specs/gemini_system_prompt.md`
- 타입 매핑(초안): `specs/component_mapping.json`
- Gemini 응답 예시: `examples/gemini_response_example.md`
- mac 설치파일: `install_mac.command`
- 배포용 zip: `dist/ArchiGhGemini_mac_installer.zip`

## mac 설치 (API 키 주입)
1. 터미널에서 프로젝트 폴더로 이동
2. `./install_mac.command` 실행
3. Gemini API 키 입력
4. 설치 완료 경로 확인:
   - `~/Library/Application Support/McNeel/Rhinoceros/8.0/scripts/archicad-gemini-node-builder`

## 작업 Task (Gemini 중심)

### 1) DSL 계약 고정
- [x] Gemini 출력 포맷 고정 (`python fenced code block`)
- [x] 허용 함수 고정 (`node`, `wire`)
- [x] 타입 매핑 초안 작성 (`Archicad.Wall` 등)
- 완료 조건: Gemini 응답이 그대로 실행 가능한 DSL 코드

### 2) Gemini 연동
- [x] GhPython에서 Gemini API 직접 호출 옵션 구현
- [x] API 호출 없이 `gemini_response` 텍스트만으로 실행하는 옵션 구현
- [ ] 실패 재시도/백오프 추가
- 완료 조건: `use_api=True` 또는 `False` 모두 동작

### 3) 코드 추출/검증/실행
- [x] 코드 블록 추출기 구현
- [x] AST 기반 DSL 검증 구현
- [x] 실행 실패 시 롤백 처리 구현
- [x] 장문 응답에서도 유효한 DSL 코드블록 자동 선택
- 완료 조건: 위험 코드 없이 노드 생성만 수행

### 4) Archicad 호환 보정
- [ ] Archicad 컴포넌트별 정확한 포트 인덱스 검증
- [ ] 프로젝트 환경에서 `component_mapping.json` 토큰 보정
- 완료 조건: Curve -> Archicad.Wall 케이스 안정화

## 빠른 실행 방법 (GhPython)
1. Grasshopper에서 `GhPython` 컴포넌트를 놓고 `scripts/ghpython_gemini_node_builder.py` 코드 붙여넣기
2. 입력 포트 9개 생성:
   - `run`, `prompt`, `use_api`, `gemini_response`, `api_key`, `model`, `system_prompt`, `mapping_json`, `clear_previous`
3. 기본 연결:
   - `system_prompt` <- `specs/gemini_system_prompt.md`의 코드블록 내용
   - `mapping_json` <- `specs/component_mapping.json` 내용
4. 실행 방식 A(권장): `use_api=True`, `prompt` 입력, `api_key` 입력 후 `run=True`
5. 실행 방식 B(디버그): `use_api=False`, `gemini_response`에 Gemini 원문 붙여넣고 `run=True`
   - 코드만 따로 뽑을 필요 없음. 원문 전체를 넣으면 자동 파싱됨.

## Gemini 응답 형식 예시
```python
node("curve_src", "Curve", 120, 120, nickname="source_curve")
node("ac_wall", "Archicad.Wall", 360, 120, nickname="wall")
wire("curve_src", 0, "ac_wall", 0)
```

## 주의사항
- 현재 DSL은 의도적으로 제한되어 있음(`node`, `wire`만 허용)
- `component_mapping.json`의 Archicad 검색 토큰은 사용 환경에 맞게 조정 필요
- Rhino/Grasshopper 환경에서만 실제 실행 가능(이 저장소에서는 런타임 테스트 불가)
