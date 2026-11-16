# -*- coding: utf-8 -*-
"""本地假 LLM（OpenAI 兼容 /v1/chat/completions），只为把 Agent 链路跑到出结果。

用途：没有真实 DeepSeek Key 时，让 `POST /api/agents/group-analysis` 走完
openai-agents SDK 的整条链路（结构化输出解析、证据编号、动作卡），从而在页面上
看到「Agent 分析」与「证据与动作」两页签的真实渲染。

它不理解自然语言，只回一段符合 `GroupAnalysisOutput` schema 的 JSON；证据编号
是预先写死的 T# 号，需要与 `tools/dev_cli.py seed` 灌进去的那批发言对应。

    .venv\\Scripts\\python.exe tools\\dev_mock_llm.py 8899

配套 .env：
    LLM_BASE_URL=http://127.0.0.1:8899/v1
    LLM_API_KEY=sk-local-mock
    LLM_MODEL=mock-deepseek
"""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ANALYSIS = {
    "summary": (
        "四人发言分布均匀（各占 25%），讨论沿着「光反应—暗反应—限制因素—对照实验」"
        "逐步推进，信息新度 66% 说明后半段开始出现新的实验设计内容。"
        "风险在于观点集中在李同学与赵同学身上，王同学与陈同学的追问还没有被系统回应。"
    ),
    "structure": {"groups": [], "bridges": [], "isolates": []},
    "metrics_reading": [
        {
            "metric": "participation",
            "layer": "quality",
            "value": 0.25,
            "reading": "四名成员发言条数一致，参与结构均衡，没有边缘成员。",
            "evidence": ["M:participation", "T#14", "T#20"],
        },
        {
            "metric": "newness",
            "layer": "quality",
            "value": 0.66,
            "reading": "后段出现对照实验与同位素标记的新信息，讨论没有原地重复。",
            "evidence": ["M:newness", "T#28"],
        },
        {
            "metric": "internal_cohesion",
            "layer": "quality",
            "value": 0.02,
            "reading": "语义聚合偏低：各人从不同角度切入，尚未收敛到同一结论表述。",
            "evidence": ["M:internal_cohesion"],
        },
    ],
    "findings": [
        {
            "finding": "参与结构均衡，但结论收敛不足，讨论停在并列观点上。",
            "evidence": ["M:participation", "M:internal_cohesion"],
            "confidence": "medium",
        },
        {
            "finding": "王同学两次追问暗反应能否独立进行，第二次没有得到正面回应。",
            "evidence": ["T#15", "T#18"],
            "confidence": "high",
        },
    ],
    "interventions": [
        {
            "target": "王同学",
            "action": "引导沉默成员发言",
            "script": "王同学，你刚才问暗反应能不能独立进行，能结合遮光实验的结果再说说你的判断吗？",
            "expected": "把追问转成结论，补齐暗反应与光反应的耦合关系",
            "risk": "该同学可能因为被点名而紧张，需要给足思考时间",
            "evidence": ["T#15", "T#28"],
        },
        {
            "target": "小组",
            "action": "追加一个反例讨论",
            "script": "如果光照减弱，暗反应会怎样？请举出你们实验数据里的依据。",
            "expected": "把并列观点收敛到「光照是限制因素」这一条结论上",
            "risk": "可能重新打开已经收敛的分歧，需要教师收口",
            "evidence": ["T#20", "T#28"],
        },
    ],
    "product_metrics": [],
    "data_gaps": ["小组结构发现（groups/bridges/isolates）暂未实现，结构层保持空数组。"],
    "unsupported_claims": [],
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/").endswith("/models"):
            self._json({"object": "list", "data": [{"id": "mock-deepseek", "object": "model"}]})
            return
        self._json({"ok": True, "hint": "mock llm; POST /v1/chat/completions"})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            request = json.loads(raw or b"{}")
        except Exception:
            request = {}

        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._json({"error": {"message": "unsupported path"}}, status=404)
            return

        content = json.dumps(ANALYSIS, ensure_ascii=False)
        self._json(
            {
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "created": 0,
                "model": request.get("model", "mock-deepseek"),
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        )

    def log_message(self, fmt: str, *args) -> None:  # 安静点
        sys.stderr.write("[mock-llm] " + fmt % args + "\n")


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8899
    print(f"[mock-llm] listening on http://127.0.0.1:{port}/v1")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
