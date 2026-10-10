"""Stage 1: read the brief files and the tool API file.

    briefs = read_briefs(["a.md", "b.md"])     -> [{"path", "name", "text"}]
    tools  = parse_openapi("tool_api.json")     -> {tool_name: ToolSpec}

A ToolSpec is plain data, built only from the OpenAPI file:
    {"name", "url", "method", "summary",
     "request":  {field: Field}, "required": [field, ...],
     "response": {field: Field}}
    Field = {"type", "enum", "description", "format", "items": {field: Field} for arrays of objects}
Nothing here knows any tool, field or value by name.
"""
import json, pathlib


def read_briefs(paths):
    out = []
    for p in paths:
        p = pathlib.Path(p)
        out.append({"path": str(p), "name": p.stem, "text": p.read_text(encoding="utf-8")})
    return out


def _resolve(node, root):
    """Follow a local $ref (#/components/...) if there is one."""
    seen = 0
    while isinstance(node, dict) and "$ref" in node and seen < 20:
        ref = node["$ref"]
        if not ref.startswith("#/"):
            raise ValueError(f"only local $ref is supported, got {ref}")
        node = root
        for part in ref[2:].split("/"):
            node = node[part]
        seen += 1
    return node


def _fields(schema, root):
    schema = _resolve(schema, root) or {}
    out = {}
    for name, prop in (schema.get("properties") or {}).items():
        prop = _resolve(prop, root) or {}
        f = {"type": prop.get("type", "string"), "enum": list(prop.get("enum") or []),
             "description": prop.get("description", ""), "format": prop.get("format", "")}
        items = _resolve(prop.get("items"), root) if prop.get("type") == "array" else None
        if isinstance(items, dict) and items.get("properties"):
            f["items"] = _fields(items, root)
        out[name] = f
    return out


def parse_openapi(path):
    root = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    servers = root.get("servers") or [{}]
    base = (servers[0].get("url") or "").rstrip("/")
    tools = {}
    for route, ops in (root.get("paths") or {}).items():
        for method, op in ops.items():
            if method.lower() not in ("get", "post", "put", "patch", "delete"):
                continue
            body = _resolve(((op.get("requestBody") or {}).get("content") or {}).get("application/json", {}).get("schema"), root) or {}
            ok = (op.get("responses") or {}).get("200") or (op.get("responses") or {}).get("201") or {}
            resp = _resolve((ok.get("content") or {}).get("application/json", {}).get("schema"), root) or {}
            name = op.get("operationId") or route.strip("/").split("/")[-1]
            tools[name] = {"name": name, "url": base + route, "method": method.upper(), "summary": op.get("summary", ""),
                           "request": _fields(body, root), "required": list(body.get("required") or []),
                           "response": _fields(resp, root)}
    return {"info": root.get("info") or {}, "tools": tools}


if __name__ == "__main__":       # python -m builder.ingest tools/openapi.json
    import sys
    spec = parse_openapi(sys.argv[1])
    for t in spec["tools"].values():
        req = ", ".join(f"{k}{'*' if k in t['required'] else ''}{'=' + '|'.join(v['enum']) if v['enum'] else ''}" for k, v in t["request"].items())
        print(f"{t['method']} {t['name']}: {req}")
        for k, v in t["response"].items():
            sub = f" items: {', '.join(v['items'])}" if v.get("items") else ""
            print(f"    -> {k}: {v['type']}{' ' + '|'.join(v['enum']) if v['enum'] else ''}{sub}")
