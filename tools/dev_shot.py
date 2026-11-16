# -*- coding: utf-8 -*-
"""用 Chrome DevTools Protocol 把 444dsh 的「分析」面板截出来（无需人工点击）。

为什么要脚本：这个画面藏在「教师登录 → 进入 running 课堂 → 右栏『分析』」之后，
headless 浏览器没有可点的登录表单填值能力，用 CDP 在页面上下文里直接完成
登录 + 状态切换最稳，也能保证截的是真页面、真数据。

    .venv\\Scripts\\python.exe tools\\dev_shot.py --section gca
    .venv\\Scripts\\python.exe tools\\dev_shot.py --section agent
    .venv\\Scripts\\python.exe tools\\dev_shot.py --section evidence

产物落在 storage/screenshots/。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

import websocket

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "storage" / "screenshots"
CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

BOOTSTRAP = r"""
(async () => {
  const fd = new FormData();
  fd.append('student_id', '%(user)s');
  fd.append('password', '%(password)s');
  fd.append('device_id', 'cdp-shot-%(stamp)s');
  const login = await axios.post('/api/login', fd);
  if (login.data.status !== 'success') return { ok: false, step: 'login', data: login.data };

  const v = document.querySelector('#app').__vue__;
  v.currentUser = login.data.user;
  v.sessionToken = login.data.session_token;
  if (v.applySessionToken) v.applySessionToken();
  axios.defaults.headers.common['Authorization'] = 'Bearer ' + login.data.session_token;

  v.pageState = 'classroom';
  v.meetingId = %(meeting_id)d;
  v.meetingStatus = 'running';
  v.meetingStartedAt = %(started_at)s;
  v.joined = true;
  v.classroomTab = 'insight';
  v.currentTopic = '光合作用';
  v.classForm = Object.assign({}, v.classForm, { class_code: '100' });

  await v.$nextTick();
  await new Promise((r) => setTimeout(r, 400));

  const section = '%(section)s';
  if (section === 'agent') {
    v.openInsightPanel('agent');
    await new Promise((r) => setTimeout(r, 600));
    await v.runClassroomAgent();
  } else if (section === 'evidence') {
    v.openInsightPanel('agent');
    await new Promise((r) => setTimeout(r, 600));
    await v.runClassroomAgent();          // 证据链由 Agent 结果推导，先跑一次
    await new Promise((r) => setTimeout(r, 400));
    v.switchInsightSection('evidence');
    await new Promise((r) => setTimeout(r, 800));
    await v.loadAgentTranscriptEvidence(true);
  } else {
    v.openInsightPanel('gca');
    await new Promise((r) => setTimeout(r, 1200));
    await v.loadGcaInsights(true);
  }
  await new Promise((r) => setTimeout(r, 2600));
  const panel = document.querySelector('.insight-panel');
  if (panel) panel.scrollTop = %(scroll)d;
  await new Promise((r) => setTimeout(r, 400));
  const radarEl = document.getElementById('gcaRadarChart');
  const charts = {
    hasEcharts: typeof echarts,
    radarW: radarEl ? radarEl.offsetWidth : -1,
    radarH: radarEl ? radarEl.offsetHeight : -1,
    canvases: radarEl ? radarEl.querySelectorAll('canvas').length : -1,
    instances: Object.keys(v.insightCharts || {}),
  };
  const tabBox = document.querySelector('.insight-subtabs');
  const subtabs = {
    containerW: tabBox ? Math.round(tabBox.getBoundingClientRect().width) : -1,
    widths: Array.from(document.querySelectorAll('.insight-subtab'))
      .map((el) => Math.round(el.getBoundingClientRect().width)),
  };
  return {
    charts,
    subtabs,
    tab2: v.classroomTab,
    ok: true,
    section: v.insightSection,
    tab: v.classroomTab,
    gca: v.gcaDashboard ? { status: v.gcaDashboard.status, metrics: v.gcaDashboard.group_metrics } : null,
    agentOk: !!v.agentResult,
    agentError: v.agentError || '',
    findings: (v.agentFindings || []).length,
    interventions: (v.agentInterventions || []).length,
  };
})()
"""


def find_chrome() -> str:
    for path in CHROME_CANDIDATES:
        if Path(path).is_file():
            return path
    found = shutil.which("chrome") or shutil.which("msedge")
    if found:
        return found
    raise SystemExit("找不到 Chrome/Edge 可执行文件")


class CDP:
    def __init__(self, ws_url: str):
        self.ws = websocket.create_connection(ws_url, timeout=120, suppress_origin=True)
        self.next_id = 0

    def call(self, method: str, **params):
        self.next_id += 1
        msg_id = self.next_id
        self.ws.send(json.dumps({"id": msg_id, "method": method, "params": params}))
        while True:
            raw = self.ws.recv()
            data = json.loads(raw)
            if data.get("id") == msg_id:
                if "error" in data:
                    raise RuntimeError(f"{method} -> {data['error']}")
                return data.get("result", {})

    def eval(self, expression: str, await_promise: bool = True):
        result = self.call(
            "Runtime.evaluate",
            expression=expression,
            awaitPromise=await_promise,
            returnByValue=True,
            userGesture=True,
        )
        detail = result.get("result", {})
        if result.get("exceptionDetails"):
            raise RuntimeError(json.dumps(result["exceptionDetails"], ensure_ascii=False)[:1200])
        return detail.get("value")

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def wait_for_target(port: int, timeout: float = 40.0) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1) as resp:
                targets = json.loads(resp.read().decode("utf-8"))
            for target in targets:
                if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                    return target["webSocketDebuggerUrl"]
        except Exception:
            pass
        time.sleep(0.4)
    raise SystemExit("Chrome 调试端口没起来")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--section", default="gca", choices=["gca", "agent", "evidence"])
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--user", default="t01")
    parser.add_argument("--password", default="123456")
    parser.add_argument("--meeting-id", type=int, default=2)
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--out", default="")
    parser.add_argument("--scroll", type=int, default=0)
    parser.add_argument("--port", type=int, default=9333)
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out) if args.out else OUT_DIR / f"insight-{args.section}.png"

    profile = tempfile.mkdtemp(prefix="dsh-shot-")
    chrome = subprocess.Popen(
        [
            find_chrome(),
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-first-run",
            "--no-default-browser-check",
            "--use-fake-ui-for-media-stream",
            "--use-fake-device-for-media-stream",
            "--autoplay-policy=no-user-gesture-required",
            f"--remote-debugging-port={args.port}",
            f"--user-data-dir={profile}",
            f"--window-size={args.width},{args.height}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    cdp = None
    try:
        ws_url = wait_for_target(args.port)
        cdp = CDP(ws_url)
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")
        cdp.call("Emulation.setDeviceMetricsOverride", width=args.width, height=args.height,
                 deviceScaleFactor=1, mobile=False)
        cdp.call("Page.navigate", url=args.base + "/")

        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                ready = cdp.eval(
                    "!!(document.querySelector('#app') && document.querySelector('#app').__vue__ && window.axios)",
                    await_promise=False,
                )
            except Exception:
                ready = False
            if ready:
                break
            time.sleep(0.5)
        else:
            raise SystemExit("页面 60s 内没挂上 Vue 实例")

        stamp = str(int(time.time()))
        script = BOOTSTRAP % {
            "user": args.user,
            "password": args.password,
            "meeting_id": args.meeting_id,
            "section": args.section,
            "stamp": stamp,
            "started_at": "null",
            "scroll": args.scroll,
        }
        result = cdp.eval(script)
        print("[shot] state:", json.dumps(result, ensure_ascii=False))

        shot = cdp.call("Page.captureScreenshot", format="png", captureBeyondViewport=False)
        out_path.write_bytes(base64.b64decode(shot["data"]))
        print(f"[shot] saved {out_path} ({out_path.stat().st_size} bytes)")
        return 0
    finally:
        if cdp:
            cdp.close()
        chrome.terminate()
        try:
            chrome.wait(timeout=10)
        except Exception:
            chrome.kill()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
