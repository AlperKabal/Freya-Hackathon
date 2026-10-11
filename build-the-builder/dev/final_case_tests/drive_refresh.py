"""Compare the organisers' shared Drive folder with the local copy of the case pack, file by file.

    python3 -I dev/final_case_tests/drive_refresh.py <drive_folder_id> <empty_download_dir> <local_pack_dir>

Lists the public folder recursively (its HTML page, no login), downloads every file into the download directory and
prints for each one SAME, CHANGED or NEW against the local pack, then the local files the Drive does not have.
It copies nothing into the pack: look at a new or changed file first, then copy it by hand.
The downloads are other people's files: keep the download directory apart from any code and run with `python3 -I`.
"""
import hashlib, html, pathlib, re, subprocess, sys

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def fetch(url, to=None):
    cmd = ["curl", "-s", "-L", "-m", "60", "-A", UA, url] + (["-o", str(to)] if to else [])
    out = subprocess.run(cmd, capture_output=True)
    return out.stdout.decode("utf-8", "replace")


def rows(folder_id):
    """(id, name, is_folder, modified) for every entry of one folder page."""
    page = fetch("https://drive.google.com/drive/folders/" + folder_id)
    out, seen = [], set()
    starts = [m for m in re.finditer(r'data-id="([A-Za-z0-9_-]{20,})"[^>]*role="row"', page)]
    for i, m in enumerate(starts):
        seg = page[m.start():starts[i + 1].start() if i + 1 < len(starts) else m.start() + 20000]
        labels = [html.unescape(x) for x in re.findall(r'aria-label="([^"]+)"', seg)]
        texts = [html.unescape(x).strip() for x in re.findall(r">([^<>]{1,200})<", seg)]
        label = labels[0] if labels else ""                 # the row's own label: "<name> <kind> [Shared]"
        name = max((t for t in texts if t and label.startswith(t)), key=len, default="")
        if not name or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        modified = next((t for t in labels if t.startswith("Modified")), "")
        out.append((m.group(1), name, "folder" in label[len(name):].lower(), modified))
    return out


def walk(folder_id, prefix=""):
    for fid, name, is_folder, modified in rows(folder_id):
        if is_folder:
            yield from walk(fid, prefix + name + "/")
        else:
            yield prefix + name, fid, modified


def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def main(argv):
    root, down, local = argv[0], pathlib.Path(argv[1]), pathlib.Path(argv[2])
    down.mkdir(parents=True, exist_ok=True)
    remote = {}
    for rel, fid, modified in walk(root):
        target = down / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        fetch("https://drive.google.com/uc?export=download&id=" + fid, to=target)
        if b"Virus scan warning" in target.read_bytes()[:400]:          # Drive's page for a file type it will not scan
            fetch("https://drive.usercontent.google.com/download?export=download&confirm=t&id=" + fid, to=target)
        remote[rel] = target
        mine = local / rel
        state = "NEW" if not mine.exists() else "SAME" if sha(mine) == sha(target) else "CHANGED"
        print(f"{state:<8}{rel}  ({target.stat().st_size} bytes, {modified})")
    for p in sorted(local.rglob("*")):
        rel = str(p.relative_to(local))
        if p.is_file() and rel not in remote and not any(part.startswith(".") for part in p.parts):
            print(f"LOCAL   {rel}  (not in the Drive folder)")
    print(f"{len(remote)} file(s) in the Drive folder")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
