#!/usr/bin/env python3
"""Fetch GitHub data and render assets/telemetry.svg. Standard library only."""
import datetime as dt
import json
import os
import sys
import urllib.request
from collections import defaultdict
from html import escape

USER = os.environ.get("GH_USER") or os.environ.get("GITHUB_REPOSITORY_OWNER", "")
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
OUT = os.path.join(os.path.dirname(__file__), "..", "assets", "telemetry.svg")
BYTES_PER_LINE = 35  # rough average; LOC is an estimate derived from language bytes


def call(url, payload=None):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "profile-telemetry"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    data = json.dumps(payload).encode() if payload else None
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=30) as r:
        return json.load(r)


def fetch_repos():
    repos, page = [], 1
    while True:
        batch = call(f"https://api.github.com/users/{USER}/repos?per_page=100&type=owner&page={page}")
        repos += batch
        if len(batch) < 100:
            return [r for r in repos if not r["fork"]]
        page += 1


def fetch_contributions(created_year):
    query = """query($login:String!,$from:DateTime!,$to:DateTime!){user(login:$login){
      contributionsCollection(from:$from,to:$to){totalCommitContributions
      contributionCalendar{totalContributions weeks{contributionDays{date contributionCount}}}}}}"""
    commits = total = 0
    days = {}
    now = dt.datetime.now(dt.timezone.utc)
    for year in range(created_year, now.year + 1):
        frm = f"{year}-01-01T00:00:00Z"
        to = f"{year}-12-31T23:59:59Z" if year < now.year else now.strftime("%Y-%m-%dT%H:%M:%SZ")
        res = call("https://api.github.com/graphql",
                   {"query": query, "variables": {"login": USER, "from": frm, "to": to}})
        c = res["data"]["user"]["contributionsCollection"]
        commits += c["totalCommitContributions"]
        total += c["contributionCalendar"]["totalContributions"]
        for w in c["contributionCalendar"]["weeks"]:
            for d in w["contributionDays"]:
                days[d["date"]] = d["contributionCount"]
    return commits, total, days


def collect():
    repos = fetch_repos()
    langs = defaultdict(int)
    for r in repos:
        for k, v in call(r["languages_url"]).items():
            langs[k] += v
    created = call(f"https://api.github.com/users/{USER}")["created_at"]
    commits, total, days = fetch_contributions(int(created[:4]))

    today = dt.date.today()
    months = []
    y, m = today.year, today.month
    for _ in range(12):
        months.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    months.reverse()
    velocity = [sum(n for d, n in days.items() if d[:7] == f"{y}-{m:02d}") for y, m in months]

    stamps = sorted(r["created_at"][:7] for r in repos)
    growth = []
    if stamps:
        y, m = int(stamps[0][:4]), int(stamps[0][5:])
        while (y, m) <= (today.year, today.month):
            growth.append(sum(1 for s in stamps if s <= f"{y}-{m:02d}"))
            m += 1
            if m == 13:
                y, m = y + 1, 1
    return {
        "repos": len(repos),
        "commits": commits,
        "contributions": total,
        "loc": sum(langs.values()) // BYTES_PER_LINE,
        "languages": len(langs),
        "stars": sum(r["stargazers_count"] for r in repos),
        "lang_bytes": sorted(langs.items(), key=lambda kv: -kv[1])[:4],
        "velocity": velocity,
        "growth": growth,
        "synced": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"),
    }


def short(n):
    return f"{n/1000:.1f}K" if n >= 10000 else str(n)


def line_path(values, x, y, w, h):
    if len(values) < 2:
        return ""
    hi, lo = max(values), min(values)
    span = (hi - lo) or 1
    pts = [(x + i * w / (len(values) - 1), y + h - (v - lo) / span * h) for i, v in enumerate(values)]
    return " ".join(f"{px:.1f},{py:.1f}" for px, py in pts)


def render(d):
    W, H = 800, 500
    fg, dim, accent, line = "#d4d4d4", "#7a7a7a", "#7ee787", "#262626"
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
         f'font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="12">',
         f'<rect width="{W}" height="{H}" fill="#0a0a0a"/>',
         f'<rect x="0.5" y="0.5" width="{W-1}" height="{H-1}" fill="none" stroke="{line}"/>',
         f'<text x="24" y="30" fill="{dim}">TELEMETRY / source: github api</text>',
         f'<text x="{W-24}" y="30" fill="{dim}" text-anchor="end">SYNC {escape(d["synced"])}</text>',
         f'<line x1="24" y1="44" x2="{W-24}" y2="44" stroke="{line}"/>']

    stats = [("REPOSITORIES", d["repos"]), ("COMMITS", d["commits"]), ("CONTRIBUTIONS", d["contributions"]),
             ("LINES OF CODE (EST.)", d["loc"]), ("LANGUAGES", d["languages"]), ("STARS", d["stars"])]
    for i, (label, val) in enumerate(stats):
        cx, cy = 24 + (i % 3) * 252, 66 + (i // 3) * 64
        o.append(f'<text x="{cx}" y="{cy+12}" fill="{dim}" font-size="10">{label}</text>')
        o.append(f'<text x="{cx}" y="{cy+40}" fill="{fg}" font-size="26" font-weight="bold">{short(val)}</text>')
    o.append(f'<line x1="24" y1="206" x2="{W-24}" y2="206" stroke="{line}"/>')

    o.append(f'<text x="24" y="230" fill="{dim}" font-size="10">LANGUAGE DISTRIBUTION</text>')
    total = sum(v for _, v in d["lang_bytes"]) or 1
    for i, (name, v) in enumerate(d["lang_bytes"]):
        y = 244 + i * 22
        pct = v / total
        o.append(f'<text x="24" y="{y+11}" fill="{fg}">{escape(name)}</text>')
        o.append(f'<rect x="150" y="{y}" width="{max(pct*420, 2):.0f}" height="12" fill="{accent if i == 0 else "#8b8b8b"}"/>')
        o.append(f'<text x="{150+max(pct*420, 2)+8:.0f}" y="{y+11}" fill="{dim}">{pct*100:.0f}%</text>')
    o.append(f'<line x1="24" y1="342" x2="{W-24}" y2="342" stroke="{line}"/>')

    for gx, title, vals, sub in ((24, "COMMIT VELOCITY", d["velocity"], "contributions / month, last 12 mo"),
                                 (412, "REPOSITORY GROWTH", d["growth"], "cumulative repositories")):
        o.append(f'<text x="{gx}" y="366" fill="{dim}" font-size="10">{title}</text>')
        o.append(f'<line x1="{gx}" y1="440" x2="{gx+364}" y2="440" stroke="{line}"/>')
        pts = line_path(vals, gx, 380, 364, 56)
        if pts:
            o.append(f'<polyline points="{pts}" fill="none" stroke="{accent}" stroke-width="1.5"/>')
        o.append(f'<text x="{gx}" y="460" fill="{dim}" font-size="10">{sub}</text>')
    o.append("</svg>")
    return "\n".join(o)


if __name__ == "__main__":
    if "--placeholder" in sys.argv:
        data = {k: 0 for k in ("repos", "commits", "contributions", "loc", "languages", "stars")}
        data.update(lang_bytes=[("awaiting first sync", 1)], velocity=[], growth=[], synced="PENDING")
    else:
        if not USER:
            sys.exit("Set GH_USER or run inside GitHub Actions.")
        data = collect()
    with open(OUT, "w") as f:
        f.write(render(data))
    print("wrote", os.path.normpath(OUT))
