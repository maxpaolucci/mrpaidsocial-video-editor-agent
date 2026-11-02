#!/usr/bin/env python3
"""Fallback here.now publisher (public API: create -> PUT uploads -> finalize) for when the here-now
skill's publish.sh is not installed. Prefer publish.sh when it exists.

  python3 publish_api.py <dir> --title T [--slug existing-slug] [--state path/state.json]

Needs ~/.herenow/credentials. Records slug + versionId in the state file (default: <dir>/../.herenow/state.json)
so the next round updates the same URL with stale-base protection."""
import argparse, hashlib, json, mimetypes, subprocess, sys
from pathlib import Path

API = "https://here.now/api/v1"
CLIENT = "claude-code/direct-api"
KEY = (Path.home() / ".herenow/credentials").read_text().strip()
TYPES = {".mjs": "text/javascript", ".js": "text/javascript", ".json": "application/json",
         ".html": "text/html; charset=utf-8", ".mp4": "video/mp4"}


def curl(method, url, body=None, headers=None, data_file=None):
    cmd = ["curl", "-sS", "-X", method, url, "-w", "\n%{http_code}"]
    for k, v in (headers or {}).items():
        cmd += ["-H", f"{k}: {v}"]
    if body is not None:
        cmd += ["-H", "content-type: application/json", "--data-binary", json.dumps(body)]
    if data_file is not None:
        cmd += ["--upload-file", str(data_file)]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    text, code = out.rsplit("\n", 1)
    return int(code), text


def auth():
    return {"authorization": f"Bearer {KEY}", "X-HereNow-Client": CLIENT}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--title", required=True)
    ap.add_argument("--slug")
    ap.add_argument("--state")
    a = ap.parse_args()
    root = Path(a.dir).resolve()
    STATE = Path(a.state) if a.state else root.parent / ".herenow/state.json"
    files = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != ".DS_Store":
            rel = p.relative_to(root).as_posix()
            ctype = TYPES.get(p.suffix) or mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            files.append({"path": rel, "size": p.stat().st_size, "contentType": ctype,
                          "hash": hashlib.sha256(p.read_bytes()).hexdigest(), "_abs": p})
    body = {"files": [{k: v for k, v in f.items() if k != "_abs"} for f in files], "displayName": a.title}
    state = json.loads(STATE.read_text()) if STATE.exists() else {"publishes": {}}
    if a.slug:
        prev = state["publishes"].get(a.slug, {})
        if prev.get("versionId"):
            body["baseVersionId"] = prev["versionId"]
        code, text = curl("PUT", f"{API}/publish/{a.slug}", body, auth())
    else:
        code, text = curl("POST", f"{API}/publish", body, auth())
    if code >= 300:
        sys.exit(f"create/update failed {code}: {text[:500]}")
    res = json.loads(text)
    up = res["upload"]
    by_path = {f["path"]: f for f in files}
    for t in up["uploads"]:
        c, txt = curl("PUT", t["url"], headers=t.get("headers"), data_file=by_path[t["path"]]["_abs"])
        if c >= 300:
            sys.exit(f"upload failed for {t['path']}: {c} {txt[:300]}")
    c, txt = curl("POST", up["finalizeUrl"], {"versionId": up["versionId"]}, auth())
    if c >= 300:
        sys.exit(f"finalize failed {c}: {txt[:500]}")
    fin = json.loads(txt)
    slug = res["slug"]
    url = fin.get("primaryUrl") or res.get("primaryUrl") or res["siteUrl"]
    state["publishes"][slug] = {"siteUrl": res["siteUrl"], "primaryUrl": url, "title": a.title,
                                "versionId": fin.get("versionId") or up["versionId"], "dir": str(root)}
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2))
    print(f"published {slug}: {url}  ({len(up['uploads'])} uploaded, {len(up.get('skipped', []))} unchanged)")


if __name__ == "__main__":
    main()
