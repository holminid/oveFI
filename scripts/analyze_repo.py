import os, re, json, textwrap, time
from pathlib import Path
from collections import Counter
import requests

AI_KEY  = os.getenv("AI_API_KEY","")
AI_BASE = os.getenv("AI_API_BASE","https://api.openai.com/v1")
AI_MODEL= os.getenv("AI_MODEL","gpt-4o")

def iter_files(root):
    ignore = {".git",".venv","node_modules","dist","build","artifacts","__pycache__",".pytest_cache"}
    for p in Path(root).rglob("*"):
        if p.is_file() and not any(part in ignore for part in p.parts):
            yield p

def lang(p):
    m = {".py":"python",".js":"js",".ts":"ts",".tsx":"tsx",".jsx":"jsx",".json":"json",
         ".yml":"yaml",".yaml":"yaml",".md":"md",".toml":"toml",".sh":"sh"}
    return m.get(p.suffix.lower(), p.suffix.lower().lstrip("."))

def summarize_tree():
    files = list(iter_files("."))
    langs = Counter(lang(p) for p in files)
    size  = sum(p.stat().st_size for p in files)
    has = {
      "requirements": Path("requirements.txt").exists(),
      "pyproject": Path("pyproject.toml").exists(),
      "package": Path("package.json").exists(),
      "dockerfile": Path("Dockerfile").exists(),
      "tests": any("test" in "/".join(p.parts).lower() for p in files),
      "replit": Path(".replit").exists() or Path("replit.nix").exists(),
    }
    deps = {"python":[], "node":[]}
    if has["requirements"]:
        for l in Path("requirements.txt").read_text(encoding="utf-8", errors="ignore").splitlines():
            l=l.strip()
            if l and not l.startswith("#"): deps["python"].append(l)
    if has["package"]:
        try:
            deps["node"] = list(json.loads(Path("package.json").read_text()).get("dependencies",{}).keys())
        except: pass
    frameworks=[]
    if any("fastapi" in d.lower() for d in deps["python"]): frameworks.append("FastAPI")
    if any("flask" in d.lower() for d in deps["python"]): frameworks.append("Flask")
    if any(x in deps["node"] for x in ("express","next","react")): frameworks.append("Node/Web")
    return files, langs, size, has, deps, frameworks

def find_endpoints():
    eps=[]
    for p in Path(".").rglob("*.py"):
        if ".venv" in p.parts: continue
        s = p.read_text(encoding="utf-8", errors="ignore")
        if "FastAPI(" in s or "@app.get(" in s or "@app.post(" in s or "Flask(" in s:
            eps.append(str(p))
    return sorted(set(eps))

def collect_todos(files):
    out=[]
    for p in files:
        if p.suffix.lower() in (".py",".js",".ts",".tsx",".md",".yaml",".yml",".json"):
            t=p.read_text(encoding="utf-8", errors="ignore")
            for m in re.finditer(r"(#|//|/\*|^) *(TODO|FIXME|NOTE)[:\- ]+(.*)", t):
                line = t.count("\n", 0, m.start())+1
                out.append({"file":str(p),"line":line,"tag":m.group(2),"text":m.group(3).strip()[:200]})
    return out[:200]

def call_openai_with_backoff(payload, tries=4):
    url = f"{AI_BASE}/chat/completions"
    headers = {"Authorization": f"Bearer {AI_KEY}","Content-Type":"application/json"}
    delay = 2
    last = None
    for attempt in range(1, tries+1):
        r = requests.post(url, headers=headers, json=payload, timeout=60)
        if r.status_code < 400:
            return r
        last = r
        if r.status_code in (429,500,502,503,504):
            ra = r.headers.get("Retry-After")
            sleep_for = int(ra) if ra and ra.isdigit() else delay
            time.sleep(sleep_for)
            delay = min(delay*2, 30)
            continue
        r.raise_for_status()
    last.raise_for_status()

def ai_summary(context_json):
    prompt = textwrap.dedent(f"""
    You are a senior software architect. From this repo context:
    - 1 short paragraph architecture summary
    - exactly 5 prioritized next actions (<=120 chars each)
    Output JSON: {{ "summary": str, "next_actions": [str,str,str,str,str] }}
    CONTEXT (truncated):
    {context_json[:5800]}
    """).strip()
    payload = {
      "model": AI_MODEL,
      "messages":[
        {"role":"system","content":"Be precise, concise, actionable. Output valid JSON only."},
        {"role":"user","content": prompt}
      ],
      "temperature":0.2,
      "max_tokens": 500
    }
    r = call_openai_with_backoff(payload)
    txt = r.json()["choices"][0]["message"]["content"]
    try:
        return json.loads(txt)
    except:
        return {"summary": txt[:800], "next_actions":[]}

def main():
    files, langs, size, has, deps, frameworks = summarize_tree()
    todos = collect_todos(files)
    eps   = find_endpoints()

    context = {
      "languages": dict(langs),
      "size_bytes": size,
      "files_count": len(files),
      "has": has, "dependencies": deps, "frameworks": frameworks,
      "endpoint_files": eps[:40],
      "todo_samples": todos[:20],
    }
    context_json = json.dumps(context, indent=2)

    if AI_KEY:
        ai = ai_summary(context_json)
    else:
        ai = {"summary":"Heuristic summary (no AI key).",
              "next_actions":[
                "Add pytest smoke test",
                "Add Makefile targets: run/ingest/process/validate",
                "Create .gitignore for venv/artifacts",
                "Document env vars & local run",
                "Add README Quickstart"
              ]}

    Path("docs").mkdir(exist_ok=True)
    Path("reports").mkdir(exist_ok=True)
    Path("reports/analysis.json").write_text(context_json, encoding="utf-8")

    lines=[]
    lines+=["# ARCHITECTURE OVERVIEW",""]
    lines+=["## Summary", ai.get("summary",""), ""]
    lines+=["## Detected stack",
            f"- Languages: {dict(langs)}",
            f"- Frameworks: {frameworks}",
            f"- Key files: requirements.txt={has['requirements']}, pyproject={has['pyproject']}, package.json={has['package']}, Dockerfile={has['dockerfile']}, tests={has['tests']}, replit={has['replit']}",
            ""]
    if eps:
        lines+=["## API endpoints (files)"]+[f"- {e}" for e in eps[:30]]+[""]
    if todos:
        lines+=["## TODO/FIXME samples"]+[f"- {t['file']}:{t['line']} [{t['tag']}] {t['text']}" for t in todos[:10]]+[""]
    actions = ai.get("next_actions") or []
    if not actions:
        actions = [
          "Add pytest smoke test",
          "Add Makefile targets: run/ingest/process/validate",
          "Create .gitignore for venv/artifacts",
          "Document env vars & local run",
          "Add README Quickstart"
        ]
    lines+=["## Next 5 actions"]+[f"- {a}" for a in actions[:5]]
    Path("docs/ARCHITECTURE.md").write_text("\n".join(lines), encoding="utf-8")
    print("Wrote docs/ARCHITECTURE.md and reports/analysis.json")

if __name__=="__main__":
    main()
