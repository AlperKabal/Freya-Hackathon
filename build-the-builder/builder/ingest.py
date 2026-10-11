"""Stage 1: read the brief files and the tool API file.

    briefs = read_briefs(["a.md", "b.md"])     -> [{"path", "name", "text"[, "note"]}]
    tools  = parse_openapi("tool_api.json")     -> {tool_name: ToolSpec}

A ToolSpec is plain data, built only from the OpenAPI file:
    {"name", "url", "method", "summary",
     "request":  {field: Field}, "required": [field, ...],
     "response": {field: Field}}
    Field = {"type", "enum", "description", "format", "items": {field: Field} for arrays of objects}
Nothing here knows a field or a value by name. The seven tool names are fixed by the event (spec_schema.TOOL_NAMES):
an operation is filed under the fixed name its operationId or its path spells, whatever the spelling.

A hidden brief can be raw bank material in any text encoding, or an office file; the tool API can be shaped a little
differently from the one in the kit. So nothing here raises on an odd file: a brief that cannot be read becomes an
empty text with a note, an odd operation is skipped, and the caller decides what to do with what is left.
"""
import html, json, pathlib, re, zipfile, zlib, io

from builder.spec_schema import TOOL_NAMES

METHODS = ("get", "post", "put", "patch", "delete")


# ---------------------------------------------------------------- brief files

def _decode(raw):
    """Bytes -> text, whatever the encoding."""
    if raw[:3] == b"\xef\xbb\xbf":
        return raw[3:].decode("utf-8", errors="replace")
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def _xml_text(xml, para, run):
    """Text of an office XML part: one line per paragraph (or row), the runs of a paragraph joined."""
    lines = []
    for block in re.split(para, xml):
        words = [html.unescape(re.sub(r"<[^>]+>", "", w)) for w in re.findall(run, block, re.S)]
        if words:
            lines.append("".join(words))
    return "\n".join(lines)


def _office(raw):
    """Text of a .docx, .xlsx or .pptx file (a zip of XML parts), read with the standard library only."""
    z = zipfile.ZipFile(io.BytesIO(raw))
    names = z.namelist()
    read = lambda n: z.read(n).decode("utf-8", errors="replace")
    if "word/document.xml" in names:
        run = r"<w:t(?: [^>]*)?>(.*?)</w:t>"

        def table(m):                                    # a table becomes one line per row, the cells apart
            rows = []
            for row in re.findall(r"<w:tr[ >].*?</w:tr>", m.group(0), re.S):
                rows.append(" | ".join("".join(re.findall(run, cell, re.S)) for cell in re.findall(r"<w:tc[ >].*?</w:tc>", row, re.S)))
            return "".join("<w:p><w:t>" + r + "</w:t></w:p>" for r in rows)
        xml = re.sub(r"<w:tbl[ >].*?</w:tbl>", table, read("word/document.xml"), flags=re.S)
        return _xml_text(xml, r"</w:p>", run)
    if any(n.startswith("xl/worksheets/") for n in names):
        shared = []
        if "xl/sharedStrings.xml" in names:
            shared = [html.unescape(re.sub(r"<[^>]+>", "", s)) for s in re.findall(r"<si>(.*?)</si>", read("xl/sharedStrings.xml"), re.S)]
        rows = []
        for n in sorted(x for x in names if x.startswith("xl/worksheets/") and x.endswith(".xml")):
            for row in re.findall(r"<row[^>]*>(.*?)</row>", read(n), re.S):
                cells = []
                for attrs, inner in re.findall(r"<c([^>]*)>(.*?)</c>", row, re.S):
                    v = re.search(r"<v>(.*?)</v>", inner, re.S)
                    t = re.search(r"<t[^>]*>(.*?)</t>", inner, re.S)
                    if 't="s"' in attrs and v and v.group(1).strip().isdigit() and int(v.group(1)) < len(shared):
                        cells.append(shared[int(v.group(1))])
                    else:
                        cells.append(html.unescape((t or v).group(1)) if (t or v) else "")
                rows.append(",".join(cells))
        return "\n".join(rows)
    slides = sorted(n for n in names if n.startswith("ppt/slides/slide") and n.endswith(".xml"))
    if slides:
        return "\n\n".join(_xml_text(read(n), r"</a:p>", r"<a:t>(.*?)</a:t>") for n in slides)
    return ""


def _pdf(raw):
    """Best effort: the text operators of a PDF's (deflated) content streams. Good enough for a plain text PDF."""
    out = []
    for stream in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.S):
        try:
            data = zlib.decompress(stream)
        except Exception:
            data = stream
        for chunk in re.findall(rb"BT(.*?)ET", data, re.S):
            parts = re.findall(rb"\(((?:\\.|[^\\()])*)\)", chunk)
            if parts:
                line = b"".join(parts).decode("latin-1", errors="replace")
                out.append(re.sub(r"\\([()\\])", r"\1", line))
    return "\n".join(out)


def read_text(path):
    """(text, note) of one brief file. Never raises: a file that cannot be read is an empty text with a note."""
    try:
        raw = pathlib.Path(path).read_bytes()
    except Exception as e:
        return "", f"could not be read ({type(e).__name__})"
    try:
        if raw[:2] == b"PK":
            text = _office(raw)
            return text, "office file read as text" if text.strip() else "office file without readable text"
        if raw[:5] == b"%PDF-":
            text = _pdf(raw)
            return text, "PDF read as text (best effort)" if len(text.strip()) > 200 else "PDF without readable text"
        return _decode(raw), ""
    except Exception as e:
        try:
            return _decode(raw), f"read as plain text after {type(e).__name__}"
        except Exception:
            return "", f"could not be read ({type(e).__name__})"


def read_briefs(paths):
    out = []
    for p in paths:
        text, note = read_text(p)
        d = {"path": str(p), "name": pathlib.Path(p).stem, "text": text}
        if note:
            d["note"] = note
        out.append(d)
    return out


# ---------------------------------------------------------------- the tool API file

def load_api(path):
    """The API file as a dict. JSON; YAML when a YAML library happens to be installed."""
    text = _decode(pathlib.Path(path).read_bytes())
    try:
        root = json.loads(text)
    except ValueError:
        import yaml                                      # not a dependency: only used if it is there
        root = yaml.safe_load(text)
    if not isinstance(root, dict):
        raise ValueError("the tool API file is not an object")
    return root


def looks_like_api(path):
    """Is this file a tool API description (and not a brief document that happens to be JSON)?"""
    try:
        root = load_api(path)
        return isinstance(root.get("paths"), dict) and bool(root["paths"])
    except Exception:
        return False


def _resolve(node, root):
    """Follow a local $ref (#/components/...) if there is one."""
    seen = 0
    while isinstance(node, dict) and "$ref" in node and seen < 20:
        ref = node["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/"):
            return {}                                    # a remote reference: nothing we can read
        node = root
        for part in ref[2:].split("/"):
            node = node.get(part.replace("~1", "/").replace("~0", "~"), {}) if isinstance(node, dict) else {}
        seen += 1
    return node


def _flat(schema, root, depth=0):
    """One schema with its allOf / oneOf / anyOf parts merged: (properties, required)."""
    schema = _resolve(schema, root)
    if not isinstance(schema, dict) or depth > 6:
        return {}, []
    props = dict(schema.get("properties") or {}) if isinstance(schema.get("properties"), dict) else {}
    required = [r for r in schema.get("required") or [] if isinstance(r, str)] if isinstance(schema.get("required"), list) else []
    for key in ("allOf", "oneOf", "anyOf"):
        for part in schema.get(key) or []:
            p, r = _flat(part, root, depth + 1)
            for k, v in p.items():
                props.setdefault(k, v)
            if key == "allOf":
                required += [x for x in r if x not in required]
    return props, required


def _type(prop):
    t = prop.get("type", "string")
    if isinstance(t, list):                              # OpenAPI 3.1: ["string", "null"]
        t = next((x for x in t if x != "null"), "string")
    return t if isinstance(t, str) else "string"


def _fields(schema, root, depth=0):
    props, _ = _flat(schema, root)
    out = {}
    for name, prop in props.items():
        prop = _resolve(prop, root)
        if not isinstance(prop, dict):
            prop = {}
        enum = prop.get("enum") if isinstance(prop.get("enum"), list) else ([prop["const"]] if "const" in prop else [])
        f = {"type": _type(prop), "enum": [e for e in enum if e is not None],
             "description": str(prop.get("description") or ""), "format": str(prop.get("format") or "")}
        items = _resolve(prop.get("items"), root) if f["type"] == "array" else None
        if isinstance(items, dict) and depth < 4:
            sub = _fields(items, root, depth + 1)
            if sub:
                f["items"] = sub
        out[str(name)] = f
    return out


def _json_schema(content):
    """The schema of a requestBody / response `content` map: the JSON one, else the first."""
    if not isinstance(content, dict) or not content:
        return {}
    key = next((k for k in content if "json" in str(k).lower()), next(iter(content)))
    return (content.get(key) or {}).get("schema") or {} if isinstance(content.get(key), dict) else {}


def _plain(name):
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def tool_name(operation_id, route):
    """The fixed tool name an operation spells (verifyIdentity, /v1/verify-identity -> verify_identity), else its own."""
    last = str(route).strip("/").split("/")[-1]
    for cand in (operation_id, last):
        for fixed in TOOL_NAMES:
            if cand and _plain(cand) == _plain(fixed):
                return fixed
    return str(operation_id or last)


def _base_url(root):
    servers = root.get("servers") if isinstance(root.get("servers"), list) else []
    if servers and isinstance(servers[0], dict) and servers[0].get("url"):
        url = str(servers[0]["url"])
        for k, v in (servers[0].get("variables") or {}).items() if isinstance(servers[0].get("variables"), dict) else []:
            if isinstance(v, dict) and "default" in v:
                url = url.replace("{" + str(k) + "}", str(v["default"]))
        return url.rstrip("/")
    if root.get("host"):                                 # Swagger 2
        scheme = (root.get("schemes") or ["https"])[0] if isinstance(root.get("schemes"), list) and root.get("schemes") else "https"
        return f"{scheme}://{root['host']}{root.get('basePath') or ''}".rstrip("/")
    return ""


def parse_api(root):
    """A loaded API description -> {"info", "tools"}. An operation it cannot read is skipped, never an error."""
    base, tools = _base_url(root), {}
    for route, ops in (root.get("paths") or {}).items() if isinstance(root.get("paths"), dict) else []:
        ops = _resolve(ops, root)
        if not isinstance(ops, dict):
            continue
        for method, op in ops.items():
            if str(method).lower() not in METHODS or not isinstance(op, dict):
                continue
            try:
                body = _json_schema((_resolve(op.get("requestBody"), root) or {}).get("content"))
                params = [_resolve(p, root) for p in list(ops.get("parameters") or []) + list(op.get("parameters") or [])]
                if not body:                             # Swagger 2: the body is a parameter
                    body = next((p.get("schema") for p in params if isinstance(p, dict) and p.get("in") == "body" and p.get("schema")), {})
                request, required = _fields(body, root), _flat(body, root)[1]
                for p in params:                         # query / form fields count as request fields too
                    if isinstance(p, dict) and p.get("in") in ("query", "formData") and p.get("name"):
                        schema = p.get("schema") if isinstance(p.get("schema"), dict) else p
                        request.update(_fields({"properties": {p["name"]: schema}}, root))
                        if p.get("required"):
                            required.append(str(p["name"]))
                responses = op.get("responses") if isinstance(op.get("responses"), dict) else {}
                ok = next((responses[k] for k in ("200", "201", "2XX", "default") if k in responses),
                          next((v for k, v in responses.items() if str(k).startswith("2")), {}))
                ok = _resolve(ok, root) or {}
                resp = _json_schema(ok.get("content")) or ok.get("schema") or {}
                name = tool_name(op.get("operationId"), route)
                if name in tools and name not in TOOL_NAMES:
                    name = f"{name}_{str(method).lower()}"
                tools.setdefault(name, {"name": name, "url": base + str(route), "method": str(method).upper(), "summary": str(op.get("summary") or op.get("description") or ""),
                                        "request": request, "required": [r for r in required if r in request], "response": _fields(resp, root)})
            except Exception:
                continue
    return {"info": root.get("info") if isinstance(root.get("info"), dict) else {}, "tools": tools}


def parse_openapi(path):
    return parse_api(load_api(path))


if __name__ == "__main__":       # python -m builder.ingest tools/openapi.json
    import sys
    spec = parse_openapi(sys.argv[1])
    for t in spec["tools"].values():
        req = ", ".join(f"{k}{'*' if k in t['required'] else ''}{'=' + '|'.join(map(str, v['enum'])) if v['enum'] else ''}" for k, v in t["request"].items())
        print(f"{t['method']} {t['name']}: {req}")
        for k, v in t["response"].items():
            sub = f" items: {', '.join(v['items'])}" if v.get("items") else ""
            print(f"    -> {k}: {v['type']}{' ' + '|'.join(map(str, v['enum'])) if v['enum'] else ''}{sub}")
