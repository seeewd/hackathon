# GH Gemini Node Builder — 자연어로 Grasshopper 노드를 자동 생성

> **해커톤 제출작** | Rhino 8 + Grasshopper + Archicad + Google Gemini

---

## 프로젝트 한 줄 요약

한국어 자연어 프롬프트를 입력하면, Gemini AI가 Grasshopper 노드 배치 코드를 생성하고, 이를 즉시 실행해 Grasshopper 캔버스에 노드와 와이어를 자동으로 생성하는 도구입니다.

---

## 문제 의식

Grasshopper는 건축·제품 설계에 강력한 파라메트릭 모델링 환경이지만, **노드를 하나씩 찾아 연결하는 과정은 전문가에게도 반복적이고 진입 장벽이 높습니다.** 특히 Archicad 연동 컴포넌트는 적절한 포트 연결 방법을 모르면 사용하기 어렵습니다.

이 프로젝트는 "**자연어 한 문장 → 노드 그래프 자동 완성**"을 목표로, 비전문가도 Grasshopper를 사용할 수 있도록 AI가 노드 배치를 대신해 줍니다.

---

## 핵심 기능

| 기능 | 설명 |
|------|------|
| 자연어 → 노드 생성 | 한국어/영어 프롬프트 → Gemini → Grasshopper 노드 자동 배치 |
| DSL 코드 추출 | Gemini 응답에서 `node()` / `wire()` 코드블록만 안전하게 추출 |
| AST 기반 보안 검증 | 허용된 함수 호출만 실행, 임의 코드 주입 차단 |
| 실행 실패 시 롤백 | 노드 생성 중 오류 발생 시 생성된 객체 전체 자동 제거 |
| 챗봇 UI | Rhino 내 Eto 기반 챗봇 창으로 대화형 사용 가능 |
| GhPython 컴포넌트 | Grasshopper 캔버스 안에서 직접 실행하는 컴포넌트 모드 |
| Archicad 호환 | Wall, Slab, Column 등 Archicad 컴포넌트 자동 탐색 및 배치 |

---

## 동작 흐름

```
사용자 입력 (자연어)
        ↓
Gemini API 호출 (systemInstruction + user prompt)
        ↓
응답 텍스트에서 python 코드블록 추출
        ↓
AST 검증 (node / wire 호출만 허용)
        ↓
샌드박스 exec() 실행
        ↓
Grasshopper 캔버스에 노드 + 와이어 생성
        ↓
Archicad로 데이터 전달 (선택)
```

---

## 사용 방법

### A. 챗봇 창 모드 (권장)

1. Rhino 8에서 ScriptEditor 열기
2. `scripts/rhino_gh_chatbot_window.py` 실행
3. Gemini API 키 입력
4. 프롬프트 입력 예시:
   - `"정육면체 하나와 그 네 면에 올라가는 오각형 지붕을 만들어줘"`
   - `"Curve를 Archicad Wall에 연결하는 노드를 만들어줘"`
5. `Generate Nodes` 클릭 → Grasshopper 캔버스에 자동 생성

### B. GhPython 컴포넌트 모드

1. Grasshopper에서 `GhPython` 컴포넌트 추가
2. `scripts/ghpython_gemini_node_builder.py` 코드 붙여넣기
3. 입력 포트 9개 연결:

| 포트 | 타입 | 설명 |
|------|------|------|
| `run` | bool | True로 설정하면 실행 |
| `prompt` | str | 자연어 프롬프트 |
| `use_api` | bool | True: Gemini API 호출, False: 직접 응답 입력 |
| `gemini_response` | str | use_api=False일 때 Gemini 응답 원문 |
| `api_key` | str | Gemini API 키 |
| `model` | str | 모델명 (기본: gemini-2.5-flash-preview) |
| `system_prompt` | str | 시스템 프롬프트 (기본값 내장) |
| `mapping_json` | str | 컴포넌트 타입 매핑 JSON |
| `clear_previous` | bool | 이전 생성 노드 초기화 여부 |

---

## 설치 (macOS)

```bash
# 프로젝트 폴더에서
./install_mac.command
# → Gemini API 키 입력
# → ~/Library/Application Support/McNeel/Rhinoceros/8.0/scripts/ 에 설치
```

또는 `dist/ArchiGhGemini_mac_installer.zip`을 사용하세요.

---

## Gemini DSL 예시

Gemini가 아래와 같은 코드를 반환하면, 스크립트가 자동으로 추출하여 실행합니다:

```python
node("curve_src", "Curve", 120, 120, nickname="source_curve")
node("ac_wall", "Archicad.Wall", 360, 120, nickname="wall")
wire("curve_src", 0, "ac_wall", 0)
```

### 허용된 DSL API

```
node(id, type_name, x, y, nickname=None)  # 노드 생성 및 배치
wire(from_id, out_index, to_id, in_index)  # 노드 간 와이어 연결
```

### 지원 컴포넌트 타입

- `Curve`, `Line`, `Point` (Grasshopper 기본)
- `Archicad.Wall`, `Archicad.Slab`, `Archicad.Column` (Archicad 연동)
- `component_mapping.json`을 수정해 커스텀 타입 추가 가능

---

## 보안 설계

- **AST 파싱 검증**: `node()` / `wire()` 이외의 함수 호출, 변수 선언, 루프, import 등 모두 거부
- **리터럴 인수만 허용**: 동적 표현식 실행 불가
- **샌드박스 실행**: `__builtins__={}`로 격리된 환경에서 exec
- **롤백 처리**: 실행 실패 시 생성된 모든 노드 자동 삭제

---

## 파일 구조

```
hackathon/
├── scripts/
│   ├── rhino_gh_chatbot_window.py     # Rhino 챗봇 창 (Eto UI)
│   └── ghpython_gemini_node_builder.py # GhPython 컴포넌트 스크립트
├── specs/
│   ├── gemini_system_prompt.md        # Gemini 시스템 프롬프트
│   └── component_mapping.json         # 컴포넌트 타입 매핑
├── examples/
│   └── gemini_response_example.md     # Gemini 응답 예시
├── dist/
│   └── ArchiGhGemini_mac_installer.zip
└── install_mac.command                 # macOS 설치 스크립트
```

---

## 기술 스택

- **런타임**: Rhino 8 (CPython 3.11, macOS)
- **UI**: Eto.Forms (Rhino 내장 크로스플랫폼 UI)
- **AI**: Google Gemini API (`gemini-2.5-flash-preview`)
- **CAD**: Rhino/Grasshopper, Archicad (Live Connection)
- **언어**: Python (표준 라이브러리만 사용, 외부 의존성 없음)

---

## 주의사항

- Rhino 8 + Grasshopper 환경에서만 실행 가능
- Gemini API 키 필요 (Google AI Studio에서 발급)
- Archicad 컴포넌트는 Archicad-Grasshopper Live Connection 플러그인 필요
- `component_mapping.json`의 검색 토큰은 사용 환경에 맞게 조정 필요
