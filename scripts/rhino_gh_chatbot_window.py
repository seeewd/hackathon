"""
Rhino 8 Python script (macOS) that opens a chatbot window for Grasshopper.

How to use:
1) Open Grasshopper.
2) Run this script in Rhino ScriptEditor.
3) Type a prompt in the window and click "Generate Nodes".

The script calls Gemini, extracts executable DSL code from the response,
validates it, and creates/links nodes on the active Grasshopper canvas.
"""

import ast
import json
import os
import re
import urllib.error
import urllib.request

import scriptcontext as sc
import System
import System.Drawing as SD
import Rhino
import Rhino.UI
import Eto.Forms as forms
import Eto.Drawing as drawing
import Grasshopper.Kernel as GHK
from Grasshopper import Instances


DEFAULT_MODEL = "gemini-1.5-flash"
DEFAULT_API_KEY = ""
DEFAULT_SYSTEM_PROMPT = (
    "You generate Grasshopper node-building code for Rhino/Grasshopper.\n"
    "Return exactly one fenced python code block and nothing else.\n"
    "Allowed API: node(id, type_name, x, y, nickname=None), wire(from_id, out_index, to_id, in_index).\n"
    "Use only node(...) and wire(...). No imports, variables, loops, or functions."
)

DEFAULT_MAPPING = {
    "Curve": {"search": [["params", "geometry", "curve"], ["curve", "param"]]},
    "Line": {"search": [["curve", "line"], ["line", "sdl"]]},
    "Point": {"search": [["vector", "point"], ["params", "geometry", "point"]]},
    "Archicad.Wall": {"search": [["archicad", "wall"]]},
    "Archicad.Slab": {"search": [["archicad", "slab"]]},
    "Archicad.Column": {"search": [["archicad", "column"]]},
}

ALLOWED_CALLS = set(["node", "wire"])
CODE_BLOCK_RE = re.compile(r"```([a-zA-Z0-9_+-]*)\s*([\s\S]*?)```", re.IGNORECASE)
FORM_KEY = "gh_gemini_chat_window"
NODES_KEY = "gh_gemini_chat_nodes"


def _safe_text(v):
    if v is None:
        return ""
    return str(v)


def _make_text_widget(text):
    # RhinoCode/Eto binding differences can break Label constructors.
    # Use a read-only TextBox fallback so UI still works across runtimes.
    try:
        w = forms.Label()
        w.Text = text
        return w
    except Exception:
        tb = forms.TextBox()
        tb.Text = text
        tb.ReadOnly = True
        return tb


def _to_bool(v, default=False):
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


def _load_mapping_from_file():
    mapping = DEFAULT_MAPPING
    script_dir = os.path.dirname(__file__) if "__file__" in globals() else ""
    if not script_dir:
        return mapping
    path = os.path.join(script_dir, "component_mapping.json")
    if not os.path.isfile(path):
        return mapping
    try:
        obj = json.loads(open(path, "r").read())
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    return mapping


def _is_literal_node(node):
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(_is_literal_node(x) for x in node.elts)
    if isinstance(node, ast.Dict):
        for k in node.keys:
            if k is not None and not _is_literal_node(k):
                return False
        return all(_is_literal_node(v) for v in node.values)
    return False


def _validate_dsl(code_text):
    tree = ast.parse(code_text, mode="exec")
    for stmt in tree.body:
        if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Call):
            raise ValueError("Only direct function-call statements are allowed.")
        call = stmt.value
        if not isinstance(call.func, ast.Name):
            raise ValueError("Only simple calls are allowed.")
        if call.func.id not in ALLOWED_CALLS:
            raise ValueError("Unsupported function: %s" % call.func.id)
        for arg in call.args:
            if not _is_literal_node(arg):
                raise ValueError("Only literal arguments are allowed.")
        for kw in call.keywords:
            if kw.arg is None or not _is_literal_node(kw.value):
                raise ValueError("Only literal keyword arguments are allowed.")
    return True


def _extract_executable_code(text):
    if not text:
        raise ValueError("Empty Gemini response.")

    candidates = []
    for m in CODE_BLOCK_RE.finditer(text):
        lang = (m.group(1) or "").strip().lower()
        body = (m.group(2) or "").strip()
        if not body:
            continue
        priority = 0 if lang in ("python", "py", "") else 1
        candidates.append((priority, body))

    candidates.sort(key=lambda x: x[0])
    for _, body in candidates:
        try:
            _validate_dsl(body)
            return body
        except Exception:
            pass

    lines = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("node(") or s.startswith("wire("):
            lines.append(s)
    if lines:
        merged = "\n".join(lines)
        _validate_dsl(merged)
        return merged

    raw = text.strip()
    _validate_dsl(raw)
    return raw


def _gemini_generate(prompt_text, api_key_text, model_name, system_prompt_text):
    if not api_key_text:
        raise ValueError("Missing Gemini API key.")

    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent?key=%s"
        % (model_name, api_key_text)
    )

    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt_text}]},
        "contents": [{"role": "user", "parts": [{"text": prompt_text}]}],
    }
    body = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=40) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    candidates = result.get("candidates", [])
    if not candidates:
        raise ValueError("Gemini response has no candidates.")
    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts:
        raise ValueError("Gemini response has no text parts.")
    return "".join([p.get("text", "") for p in parts]).strip()


def _proxy_text(proxy):
    desc = getattr(proxy, "Desc", None)
    if desc is None:
        return ""
    return " ".join(
        [
            _safe_text(getattr(desc, "Category", "")),
            _safe_text(getattr(desc, "SubCategory", "")),
            _safe_text(getattr(desc, "Name", "")),
            _safe_text(getattr(desc, "NickName", "")),
        ]
    ).lower()


def _find_proxy_by_tokens(token_groups):
    proxies = Instances.ComponentServer.ObjectProxies
    for tokens in token_groups:
        if isinstance(tokens, str):
            tokens = [tokens]
        tokens = [str(t).lower().strip() for t in tokens if str(t).strip()]
        if not tokens:
            continue
        for proxy in proxies:
            text = _proxy_text(proxy)
            if all(t in text for t in tokens):
                return proxy
    return None


def _emit_object(type_name, mapping):
    cfg = mapping.get(type_name, {})
    guid_text = cfg.get("guid")
    if guid_text:
        return Instances.ComponentServer.EmitObject(System.Guid(guid_text))
    search_groups = cfg.get("search", [[type_name]])
    proxy = _find_proxy_by_tokens(search_groups)
    if proxy is None:
        return None
    return proxy.CreateInstance()


def _source_param(doc_obj, out_index):
    if isinstance(doc_obj, GHK.IGH_Component):
        if out_index < 0 or out_index >= doc_obj.Params.Output.Count:
            raise ValueError("Invalid output index: %s" % out_index)
        return doc_obj.Params.Output[out_index]
    if isinstance(doc_obj, GHK.IGH_Param):
        if out_index != 0:
            raise ValueError("Standalone param supports output index 0 only.")
        return doc_obj
    raise ValueError("Unsupported source object type.")


def _target_param(doc_obj, in_index):
    if isinstance(doc_obj, GHK.IGH_Component):
        if in_index < 0 or in_index >= doc_obj.Params.Input.Count:
            raise ValueError("Invalid input index: %s" % in_index)
        return doc_obj.Params.Input[in_index]
    if isinstance(doc_obj, GHK.IGH_Param):
        if in_index != 0:
            raise ValueError("Standalone param supports input index 0 only.")
        return doc_obj
    raise ValueError("Unsupported target object type.")


def _active_gh_document():
    canvas = Instances.ActiveCanvas
    if canvas is None or canvas.Document is None:
        raise ValueError("Grasshopper canvas/document not found. Open Grasshopper first.")
    return canvas.Document


def _build_from_code(doc, code_text, mapping, clear_prev):
    logs = []
    created_ids = []
    created_objects = {}

    if clear_prev:
        prev_ids = sc.sticky.get(NODES_KEY, [])
        for sid in prev_ids:
            try:
                old_obj = doc.FindObject(System.Guid(sid), True)
                if old_obj is not None:
                    doc.RemoveObject(old_obj, False)
            except Exception:
                pass
        sc.sticky[NODES_KEY] = []
        logs.append("Cleared previous nodes: %s" % len(prev_ids))

    def node(node_id, type_name, x, y, nickname=None):
        sid = str(node_id)
        if sid in created_objects:
            raise ValueError("Duplicate node id: %s" % sid)
        obj = _emit_object(str(type_name), mapping)
        if obj is None:
            raise ValueError("Component not found for type: %s" % type_name)
        if obj.Attributes is None:
            obj.CreateAttributes()
        obj.Attributes.Pivot = SD.PointF(float(x), float(y))
        if nickname and hasattr(obj, "NickName"):
            if hasattr(obj, "MutableNickName"):
                obj.MutableNickName = True
            obj.NickName = str(nickname)
        doc.AddObject(obj, False)
        created_objects[sid] = obj
        created_ids.append(str(obj.InstanceGuid))
        logs.append("Node created: %s (%s)" % (sid, type_name))

    def wire(from_id, out_index, to_id, in_index):
        src = created_objects.get(str(from_id))
        dst = created_objects.get(str(to_id))
        if src is None or dst is None:
            raise ValueError("wire() references unknown node id.")
        src_param = _source_param(src, int(out_index))
        dst_param = _target_param(dst, int(in_index))
        dst_param.AddSource(src_param)
        logs.append("Wire created: %s[%s] -> %s[%s]" % (from_id, out_index, to_id, in_index))

    sandbox = {"__builtins__": {}, "node": node, "wire": wire}

    try:
        exec(compile(code_text, "<gh_chat>", "exec"), sandbox, {})
    except Exception:
        for gid in created_ids:
            try:
                obj = doc.FindObject(System.Guid(gid), True)
                if obj is not None:
                    doc.RemoveObject(obj, False)
            except Exception:
                pass
        raise

    sc.sticky[NODES_KEY] = created_ids
    doc.NewSolution(False)
    return logs, created_ids


class GhGeminiChatForm(forms.Form):
    def __init__(self):
        super(GhGeminiChatForm, self).__init__()
        self.Title = "Grasshopper Gemini Chatbot"
        self.ClientSize = drawing.Size(760, 620)
        self.Padding = drawing.Padding(12)
        self.Resizable = True

        self._mapping = _load_mapping_from_file()

        self.api_key_box = forms.PasswordBox()
        self.api_key_box.Text = DEFAULT_API_KEY

        self.model_box = forms.TextBox()
        self.model_box.Text = DEFAULT_MODEL

        self.clear_check = forms.CheckBox()
        self.clear_check.Checked = True
        self.clear_check.Text = "Clear previously created nodes"

        self.prompt_box = forms.TextArea()
        self.prompt_box.Text = "정육면체 하나와 그 정육면체의 가로 네 면에 정오각형이 올라올 수 있는 지붕을 만들어줘."

        self.status_label = _make_text_widget("Ready.")

        self.code_box = forms.TextArea()
        self.code_box.ReadOnly = True

        self.log_box = forms.TextArea()
        self.log_box.ReadOnly = True

        self.generate_btn = forms.Button()
        self.generate_btn.Text = "Generate Nodes"
        self.generate_btn.Click += self._on_generate

        self.close_btn = forms.Button()
        self.close_btn.Text = "Close"
        self.close_btn.Click += self._on_close

        layout = forms.DynamicLayout()
        layout.Spacing = drawing.Size(6, 6)
        layout.AddRow(_make_text_widget("Gemini API Key"))
        layout.AddRow(self.api_key_box)
        layout.AddRow(_make_text_widget("Model"), self.model_box, self.clear_check)
        layout.AddRow(_make_text_widget("Prompt"))
        layout.AddRow(self.prompt_box)
        layout.AddRow(_make_text_widget("Extracted DSL Code"))
        layout.AddRow(self.code_box)
        layout.AddRow(_make_text_widget("Logs / Status"))
        layout.AddRow(self.log_box)
        layout.AddRow(self.status_label)
        layout.AddSeparateRow(self.generate_btn, self.close_btn, None)
        self.Content = layout

    def _set_busy(self, busy):
        self.generate_btn.Enabled = not busy
        self.status_label.Text = "Running..." if busy else self.status_label.Text

    def _append_log(self, line):
        prev = _safe_text(self.log_box.Text)
        self.log_box.Text = (prev + "\n" + line).strip()

    def _on_close(self, sender, e):
        self.Close()

    def _on_generate(self, sender, e):
        self._set_busy(True)
        try:
            prompt = _safe_text(self.prompt_box.Text).strip()
            if not prompt:
                raise ValueError("Prompt is empty.")

            api_key = _safe_text(self.api_key_box.Text).strip() or DEFAULT_API_KEY
            model = _safe_text(self.model_box.Text).strip() or DEFAULT_MODEL
            if not api_key:
                raise ValueError("Gemini API key is missing.")

            doc = _active_gh_document()
            response_text = _gemini_generate(prompt, api_key, model, DEFAULT_SYSTEM_PROMPT)
            code_text = _extract_executable_code(response_text)
            self.code_box.Text = code_text

            logs, created_ids = _build_from_code(
                doc=doc,
                code_text=code_text,
                mapping=self._mapping,
                clear_prev=_to_bool(self.clear_check.Checked, True),
            )
            for l in logs:
                self._append_log(l)

            self.status_label.Text = "Created %s nodes." % len(created_ids)
            self._append_log("Done.")

        except urllib.error.HTTPError as http_ex:
            self.status_label.Text = "HTTP Error: %s" % http_ex
            self._append_log("HTTP Error: %s" % http_ex)
            self._append_log("Tip: try model 'gemini-1.5-flash' or list available models.")
        except Exception as ex:
            self.status_label.Text = "Error: %s" % ex
            self._append_log("Error: %s" % ex)
        finally:
            self.generate_btn.Enabled = True


def show_chat_window():
    old = sc.sticky.get(FORM_KEY)
    if old is not None:
        try:
            old.BringToFront()
            old.Focus()
            return
        except Exception:
            pass

    form = GhGeminiChatForm()

    def _on_closed(sender, e):
        if sc.sticky.get(FORM_KEY) is sender:
            del sc.sticky[FORM_KEY]

    form.Closed += _on_closed
    form.Owner = Rhino.UI.RhinoEtoApp.MainWindow
    sc.sticky[FORM_KEY] = form
    form.Show()


if __name__ == "__main__":
    show_chat_window()
