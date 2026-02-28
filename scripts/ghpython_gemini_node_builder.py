"""
GhPython Script Component for macOS Rhino/Grasshopper.

Inputs (recommended):
- run: bool
- prompt: str
- use_api: bool
- gemini_response: str
- api_key: str
- model: str
- system_prompt: str
- mapping_json: str
- clear_previous: bool

Outputs:
- ok: bool
- status: str
- code: str
- logs: list[str]
"""

import ast
import json
import re
import urllib.request

import scriptcontext as sc
import System
import System.Drawing as SD
import Grasshopper
import Grasshopper.Kernel as GHK
from Grasshopper import Instances


DEFAULT_MODEL = "gemini-1.5-pro"
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


def _safe_text(v):
    if v is None:
        return ""
    return str(v)


def _to_bool(v, default=False):
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    s = str(v).strip().lower()
    return s in ("1", "true", "yes", "y", "on")


def _load_mapping(mapping_json_text):
    if mapping_json_text and str(mapping_json_text).strip():
        try:
            obj = json.loads(mapping_json_text)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    return DEFAULT_MAPPING


def _extract_code_block(text):
    if not text:
        return ""
    match = CODE_BLOCK_RE.search(text)
    if match:
        return match.group(2).strip()
    return text.strip()


def _is_literal_node(node):
    allowed_literals = (
        ast.Constant,
        ast.List,
        ast.Tuple,
        ast.Dict,
        ast.Set,
    )
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(_is_literal_node(x) for x in node.elts)
    if isinstance(node, ast.Dict):
        for k in node.keys:
            if k is not None and not _is_literal_node(k):
                return False
        return all(_is_literal_node(v) for v in node.values)
    return isinstance(node, allowed_literals)


def _validate_dsl(code_text):
    tree = ast.parse(code_text, mode="exec")
    for stmt in tree.body:
        if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Call):
            raise ValueError("Only direct function-call statements are allowed.")
        call = stmt.value
        if not isinstance(call.func, ast.Name):
            raise ValueError("Only simple calls are allowed.")
        fn = call.func.id
        if fn not in ALLOWED_CALLS:
            raise ValueError("Unsupported function: %s" % fn)
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

    # Fallback: parse lines that look like DSL calls from free-form text.
    line_candidates = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("node(") or s.startswith("wire("):
            line_candidates.append(s)
    if line_candidates:
        merged = "\n".join(line_candidates)
        _validate_dsl(merged)
        return merged

    raw = text.strip()
    _validate_dsl(raw)
    return raw


def _gemini_generate(prompt_text, api_key_text, model_name, system_prompt_text):
    if not api_key_text:
        raise ValueError("Missing Gemini API key.")

    model_name = model_name or DEFAULT_MODEL
    system_prompt_text = system_prompt_text or DEFAULT_SYSTEM_PROMPT

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

    with urllib.request.urlopen(req, timeout=30) as resp:
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
    values = [
        _safe_text(getattr(desc, "Category", "")),
        _safe_text(getattr(desc, "SubCategory", "")),
        _safe_text(getattr(desc, "Name", "")),
        _safe_text(getattr(desc, "NickName", "")),
    ]
    return " ".join(values).lower()


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


def _build_from_code(doc, code_text, mapping, clear_prev, comp_guid_text):
    sticky_key = "ai_nodes_%s" % comp_guid_text
    logs_local = []
    created_ids = []
    created_objects = {}

    if clear_prev:
        prev_ids = sc.sticky.get(sticky_key, [])
        for sid in prev_ids:
            try:
                old_obj = doc.FindObject(System.Guid(sid), True)
                if old_obj is not None:
                    doc.RemoveObject(old_obj, False)
            except Exception:
                pass
        sc.sticky[sticky_key] = []
        logs_local.append("Cleared previous AI-created nodes: %s" % len(prev_ids))

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
        gid = str(obj.InstanceGuid)
        created_ids.append(gid)
        logs_local.append("Node created: %s (%s)" % (sid, type_name))

    def wire(from_id, out_index, to_id, in_index):
        src = created_objects.get(str(from_id))
        dst = created_objects.get(str(to_id))
        if src is None or dst is None:
            raise ValueError("wire() references unknown node id.")
        src_param = _source_param(src, int(out_index))
        dst_param = _target_param(dst, int(in_index))
        dst_param.AddSource(src_param)
        logs_local.append(
            "Wire created: %s[%s] -> %s[%s]"
            % (from_id, out_index, to_id, in_index)
        )

    sandbox = {
        "__builtins__": {},
        "node": node,
        "wire": wire,
    }

    try:
        exec(compile(code_text, "<ai_graph>", "exec"), sandbox, {})
    except Exception:
        for gid in created_ids:
            try:
                o = doc.FindObject(System.Guid(gid), True)
                if o is not None:
                    doc.RemoveObject(o, False)
            except Exception:
                pass
        raise

    sc.sticky[sticky_key] = created_ids
    return logs_local, created_ids


ok = False
status = "Idle"
code = ""
logs = []

try:
    do_run = _to_bool(run, False)
    if not do_run:
        status = "Set run=True to execute."
    else:
        doc = ghenv.Component.OnPingDocument()
        if doc is None:
            raise ValueError("Grasshopper document not found.")

        mapping = _load_mapping(_safe_text(mapping_json))
        do_api = _to_bool(use_api, False)
        prompt_text = _safe_text(prompt).strip()
        raw_response_text = _safe_text(gemini_response).strip()
        model_name = _safe_text(model).strip() or DEFAULT_MODEL
        api_key_text = _safe_text(api_key).strip() or DEFAULT_API_KEY
        sys_prompt = _safe_text(system_prompt).strip() or DEFAULT_SYSTEM_PROMPT

        if do_api:
            if not prompt_text:
                raise ValueError("Prompt is required when use_api=True.")
            raw_response_text = _gemini_generate(
                prompt_text, api_key_text, model_name, sys_prompt
            )
            logs.append("Gemini response received.")
        else:
            if not raw_response_text:
                raise ValueError("gemini_response is required when use_api=False.")

        code = _extract_executable_code(raw_response_text)
        logs.append("Code extracted and DSL validation passed.")

        local_logs, created_ids = _build_from_code(
            doc=doc,
            code_text=code,
            mapping=mapping,
            clear_prev=_to_bool(clear_previous, True),
            comp_guid_text=str(ghenv.Component.InstanceGuid),
        )
        logs.extend(local_logs)
        status = "Created %s nodes." % len(created_ids)
        ok = True

except Exception as ex:
    ok = False
    status = "Error: %s" % ex
    logs.append(status)
