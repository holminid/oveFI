import os, re, json, textwrap, base64, requests
from github import Github

GH_TOKEN = os.environ["GH_TOKEN"]
REPO_FULL = os.environ["GITHUB_REPOSITORY"]
EVENT_PATH = os.environ["GITHUB_EVENT_PATH"]

AI_API_KEY = os.environ.get("AI_API_KEY","")
AI_API_BASE = os.environ.get("AI_API_BASE","https://api.openai.com/v1")
AI_MODEL = os.environ.get("AI_MODEL","gpt-4o-mini")

gh = Github(GH_TOKEN)
repo = gh.get_repo(REPO_FULL)
event = json.load(open(EVENT_PATH))

def fetch_context(pr_number):
    pr = repo.get_pull(pr_number)
    issues = list(repo.get_issues(state="open"))[:30]
    files = [f.filename for f in pr.get_files()]
    readme = ""
    try:
        c = repo.get_contents("README.md")
        readme = base64.b64decode(c.content).decode("utf-8","ignore")
    except Exception:
        pass
    return {"pr_title": pr.title, "pr_body": pr.body or "", "files": files,
            "open_issues": [{"n":i.number,"t":i.title,"l":[l.name for l in i.labels]} for i in issues],
            "readme": readme}

def heuristic_summary(ctx):
    steps = []
    if not ctx["files"]: steps.append("Add CI: validate.yml to run ingest/process/validate on PRs")
    if any(f.startswith("scripts/") for f in ctx["files"]): steps.append("Ensure scripts are invoked via Makefile targets")
    if not steps: steps = ["Tag first release v0.0.1","Write docs/Status.md","Create next-step issues for top TODOs"]
    return f'PR: {ctx["pr_title"]}\nFiles: {len(ctx["files"])}\nOpen issues: {len(ctx["open_issues"])}', steps[:3]

def call_ai(ctx):
    prompt = textwrap.dedent(f"""
    You are a maintainer. Output JSON with keys: summary (<=1 paragraph),
    next_steps (exactly 3 short bullets, <=120 chars each).
    README:
    {ctx['readme'][:4000]}
    PR_TITLE: {ctx['pr_title']}
    PR_BODY:
    {ctx['pr_body'][:2000]}
    CHANGED_FILES: {ctx['files']}
    OPEN_ISSUES: {ctx['open_issues']}
    """).strip()
    hdr = {"Authorization": f"Bearer {AI_API_KEY}","Content-Type":"application/json"}
    data={"model":AI_MODEL,"messages":[{"role":"system","content":"Be direct. Output JSON."},{"role":"user","content":prompt}],"temperature":0.2}
    r=requests.post(f"{AI_API_BASE}/chat/completions",headers=hdr,json=data,timeout=60); r.raise_for_status()
    txt=r.json()["choices"][0]["message"]["content"]
    try:
        j=json.loads(txt); return j.get("summary",""), j.get("next_steps",[])[:3]
    except Exception:
        steps=re.findall(r"- (.+)",txt)[:3]; return txt[:800], steps

def ensure_issues(steps):
    out=[]
    for s in steps:
        issue=repo.create_issue(title=s, body="Auto-proposed next step", labels=["next-step"])
        out.append(f"#{issue.number} {issue.title}")
    return out

def post_comment(pr_number, body):
    pr = repo.get_pull(pr_number)
    pr.create_issue_comment(body)

def main():
    pr_number=None
    if "issue" in event and "pull_request" in event["issue"]:
        if not str(event.get("comment",{}).get("body","")).strip().startswith("/summary"): return
        pr_number = event["issue"]["number"]
    elif event.get("action")=="labeled" and "pull_request" in event:
        if event["label"]["name"]!="ai:review": return
        pr_number = event["pull_request"]["number"]
    else:
        return
    ctx=fetch_context(pr_number)
    if AI_API_KEY: summary,steps=call_ai(ctx)
    else: summary,steps=heuristic_summary(ctx)
    created=ensure_issues(steps)
    body="### AI Summary\n"+summary+"\n\n### Next 3 actions\n"+ "\n".join([f"- {s}" for s in steps]) + "\n\nCreated issues: " + ", ".join(created)
    post_comment(pr_number, body)

if __name__ == "__main__":
    main()
