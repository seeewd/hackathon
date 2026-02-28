#!/bin/zsh
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC_SCRIPT="$BASE_DIR/scripts/ghpython_gemini_node_builder.py"
SRC_CHATBOT_SCRIPT="$BASE_DIR/scripts/rhino_gh_chatbot_window.py"
SRC_MAPPING="$BASE_DIR/specs/component_mapping.json"
SRC_PROMPT="$BASE_DIR/specs/gemini_system_prompt.md"

if [[ ! -f "$SRC_SCRIPT" ]]; then
  echo "[ERROR] script not found: $SRC_SCRIPT"
  exit 1
fi
if [[ ! -f "$SRC_CHATBOT_SCRIPT" ]]; then
  echo "[ERROR] script not found: $SRC_CHATBOT_SCRIPT"
  exit 1
fi

TARGET_DIR="$HOME/Library/Application Support/McNeel/Rhinoceros/8.0/scripts/archicad-gemini-node-builder"
mkdir -p "$TARGET_DIR"

API_KEY="${GEMINI_API_KEY:-}"
if [[ -z "$API_KEY" && $# -ge 1 ]]; then
  API_KEY="$1"
fi
if [[ -z "$API_KEY" ]]; then
  read -s "API_KEY?Gemini API key를 입력하세요: "
  echo
fi
if [[ -z "$API_KEY" ]]; then
  echo "[ERROR] API key is required."
  exit 1
fi

TARGET_SCRIPT="$TARGET_DIR/ghpython_gemini_node_builder.py"
TARGET_CHATBOT_SCRIPT="$TARGET_DIR/rhino_gh_chatbot_window.py"
python3 - "$SRC_SCRIPT" "$TARGET_SCRIPT" "$SRC_CHATBOT_SCRIPT" "$TARGET_CHATBOT_SCRIPT" "$API_KEY" <<'PY'
import pathlib
import sys

pairs = [
    (pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])),
    (pathlib.Path(sys.argv[3]), pathlib.Path(sys.argv[4])),
]
api_key = sys.argv[5]

for src, dst in pairs:
    text = src.read_text(encoding="utf-8")
    text = text.replace('DEFAULT_API_KEY = ""', "DEFAULT_API_KEY = %r" % api_key)
    dst.write_text(text, encoding="utf-8")
PY

cp "$SRC_MAPPING" "$TARGET_DIR/component_mapping.json"
cp "$SRC_PROMPT" "$TARGET_DIR/gemini_system_prompt.md"

cat > "$TARGET_DIR/QUICK_START.txt" <<EOF
[Installed]
$TARGET_SCRIPT
$TARGET_CHATBOT_SCRIPT
$TARGET_DIR/component_mapping.json
$TARGET_DIR/gemini_system_prompt.md

[Chatbot Window - Recommended]
1) Rhino ScriptEditor에서 아래 파일 열기:
   $TARGET_CHATBOT_SCRIPT
2) Run 버튼 클릭
3) 뜬 챗봇 창에서 프롬프트 입력 후 "Generate Nodes"
4) Grasshopper 캔버스에 노드 자동 생성

[GhPython Component - Optional]
1) GhPython 컴포넌트 추가
2) $TARGET_SCRIPT 파일 내용을 그대로 붙여넣기
3) 입력 포트:
   run, prompt, use_api, gemini_response, api_key, model, system_prompt, mapping_json, clear_previous
4) use_api=True, prompt 입력, run=True

[Tip]
- api_key 포트를 비워두면 설치 시 주입된 기본 API 키를 사용합니다.
- 보안상 공유용 파일에는 API 키를 포함하지 마세요.
EOF

echo ""
echo "[OK] 설치 완료: $TARGET_DIR"
echo "[NEXT] QUICK_START.txt를 열어 Grasshopper 설정을 진행하세요."
