#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一球不落 · 一键补跑战报（本机手动触发，不做后台常驻）

用法（在项目根目录，或任意目录直接运行本文件）：
    python scripts/catchup.py                  # 闸门自动挑最近一个「全部终场且线上未发」的比赛日
    python scripts/catchup.py 2026-11-09      # 强制补指定比赛日（美国比赛日），跳过闸门

做什么：
    1. 从 git credential 读取 github.com 凭据（只在内存里，不打印、不落盘）
    2. POST /actions/workflows/daily-report.yml/dispatches
    3. 轮询这次运行直到结束，打印各步骤结论
    4. 打印仓库内与线上 Pages 的比赛日，给出战报链接

为什么要它：GitHub 的 schedule 事件是「尽力而为」，实测这个仓库是按仓库批量投递，
每天只有 4~5 次且窗口逐日后移（11-10 白天到晚上一条都没有）。闸门逻辑本身没问题，
只要触发一次就能补出缺的那期。所以晚上有电脑时跑这一条命令即可，
不用进 GitHub 网页找按钮，也不依赖任何第三方服务或本地计划任务。
"""

import base64
import datetime
import json
import pathlib
import re
import subprocess
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
WF = "/actions/workflows/daily-report.yml"


def repo_of():
    out = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT,
                         capture_output=True, text=True).stdout.strip()
    m = re.search(r"github\.com[:/]([^/]+)/([^/.]+)", out)
    if not m:
        raise SystemExit("origin 不是 GitHub 仓库：" + out)
    return m.group(1), m.group(2)


def token_of():
    p = subprocess.run(["git", "credential", "fill"], cwd=ROOT,
                       input="protocol=https\nhost=github.com\n\n",
                       capture_output=True, text=True)
    tok = dict(l.split("=", 1) for l in p.stdout.strip().splitlines()
               if "=" in l).get("password", "")
    if not tok:
        raise SystemExit("读不到 github.com 凭据。请先在 git 里登录一次（Git Credential Manager）。")
    return tok


def api(owner, repo, tok, path, method="GET", payload=None):
    url = "https://api.github.com/repos/%s/%s%s" % (owner, repo, path)
    headers = {"Authorization": "Bearer " + tok,
               "Accept": "application/vnd.github+json",
               "User-Agent": "yqbl-catchup"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        return r.status, (json.loads(raw) if raw else {})


def latest_in_repo(owner, repo, tok):
    _, c = api(owner, repo, tok, "/contents/docs/latest.json?ref=main")
    return json.loads(base64.b64decode(c["content"]).decode("utf-8")).get("game_date", "?")


def latest_on_pages(owner, repo):
    url = "https://%s.github.io/%s/latest.json?t=%d" % (owner, repo, int(time.time()))
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache",
                                               "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8", "replace")).get("game_date", "?")


def main():
    game_date = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    owner, repo = repo_of()
    tok = token_of()
    print("仓库：%s/%s" % (owner, repo))
    print("补跑前，仓库内比赛日：", latest_in_repo(owner, repo, tok))

    before = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=5)
    api(owner, repo, tok, WF + "/dispatches", "POST",
        {"ref": "main", "inputs": {"game_date": game_date}})
    print("已触发云端运行｜game_date =", game_date or "留空（闸门自动挑）")
    print("等待完成，通常 1~3 分钟…\n")

    run = None
    for _ in range(72):
        _, data = api(owner, repo, tok, WF + "/runs?per_page=5")
        for r in data.get("workflow_runs", []):
            created = datetime.datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
            if r["event"] == "workflow_dispatch" and created >= before:
                run = r
                break
        if run and run["status"] == "completed":
            break
        time.sleep(5)

    if not run:
        raise SystemExit("没找到这次运行记录，去 Actions 页面看一眼。")
    print("运行 %s：%s" % (run["id"], run["conclusion"]))

    _, jobs = api(owner, repo, tok, "/actions/runs/%s/jobs" % run["id"])
    for j in jobs.get("jobs", []):
        for s in j.get("steps", []):
            if s.get("conclusion") not in ("skipped", None):
                print("  %-34s %s" % (s["name"][:34], s["conclusion"]))

    print("\n补跑后，仓库内比赛日：", latest_in_repo(owner, repo, tok))
    try:
        print("线上 Pages 比赛日：  ", latest_on_pages(owner, repo))
    except Exception as ex:
        print("线上 Pages 暂未刷新（部署有延迟）：", str(ex)[:80])
    print("\n战报：https://%s.github.io/%s/report.html" % (owner, repo))
    print("发布台：https://%s.github.io/%s/publish.html" % (owner, repo))


if __name__ == "__main__":
    main()
