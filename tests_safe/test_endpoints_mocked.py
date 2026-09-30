"""端点测试：Form 契约 + 外部 LLM 打桩。

来源与订正
----------
移植自 `tests/test_api_endpoints.py`（原文仅 3 条，且**全部用错 payload**）：

    res = client.post("/api/ai-tutor", json={"question": "1+1=?"})   # 原第 8 行

这三个端点声明的都是 `param: str = Form(...)`（`server.py:3799`、`:4336`、`:5739`），
发 `json=` 会在**到达 handler 之前**被 FastAPI 以 422 拒绝。原文那 3 条断言
`status_code == 200`，因此是**恒失败**的；更要命的是，一旦有人"修好"它们把
payload 改成 `data=`，就会立刻真实调用 DeepSeek 生产 API。详见
`docs/legacy-assets-audit.md` §1.2。

本文件同时钉死两侧：
  - 正确契约下行为是什么（打桩 LLM 后断言响应体）
  - 错误契约下**必须**是 422（防止有人无意中把 Form 改成 JSON）

安全
----
本文件所有测试**都不发起真实网络请求**：
  - LLM 调用一律 monkeypatch 掉；
  - 若打桩漏了一处，`conftest.py` 的 socket 兜底会拦截非回环连接并抛错——
    宁可测试失败，也不会打到生产 LLM。

只读性：三条路由均不写库（`/api/suggest-topic` 只查询、无 `commit`），
因此不会污染在其后运行的冒烟基线。
"""

import json
import types

import pytest


def _fake_completion(content: str):
    """构造一个形状与 OpenAI 响应一致的最小对象。

    两个端点都只取 `response.choices[0].message.content`，故只需还原这条路径。
    """
    message = types.SimpleNamespace(content=content)
    choice = types.SimpleNamespace(message=message)
    return types.SimpleNamespace(choices=[choice])


@pytest.fixture
def llm():
    from app.services.llm_service import llm as _llm

    return _llm


@pytest.fixture
def seeded_client(client, seeded_ids):
    """带合成数据的客户端。

    `client` 夹具只保证**建表**，不保证**播种**——`seeded_ids` 是另一个夹具。
    本文件按文件名排在 `tests_safe/` 最前，因而往往最先用到客户端，此时库还是空的。
    `/api/suggest-topic` 需要库里真有一场课堂，漏掉这个依赖就会以
    「会议不存在」失败——那是**数据缺失**，却伪装成**路由行为**，很容易查错方向。
    """
    return client


@pytest.fixture
def stub_chat_completion(llm, monkeypatch):
    """打桩 `llm.client.chat.completions.create`，记录调用次数与入参。"""
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        return _fake_completion("打桩生成的建议内容")

    monkeypatch.setattr(llm.client.chat.completions, "create", fake_create)
    return calls


# ------------------------------------------------------------ Form 契约


@pytest.mark.parametrize(
    "path,json_payload",
    [
        ("/api/ai-tutor", {"question": "1+1=?"}),
        ("/api/suggest-topic", {"meeting_id": 1}),
        ("/api/quiz-error-analysis", {"wrong_questions": "[]"}),
    ],
)
def test_endpoints_reject_json_payloads(seeded_client, path, json_payload):
    """**契约守卫**：这三条端点是 Form，不是 JSON。

    发 JSON 必须是 422，且 handler 根本不会被执行——这既是现状，也是
    "打桩漏了也不会误调生产 API" 的那道保险。若哪天有人把它改成
    `data=`，本测试会失败，从而把这个决定摊到明面上。
    """
    response = seeded_client.post(path, json=json_payload)

    assert response.status_code == 422, (
        f"{path} 对 JSON payload 返回了 {response.status_code}，"
        f"说明它已不再是 Form 契约——请同步更新本文件与路由清单。"
    )


# ------------------------------------------------------------- /api/ai-tutor


def test_ai_tutor_returns_llm_answer(seeded_client, llm, monkeypatch):
    """正常路径：把 LLM 的回答原样放进 `answer` 字段。"""
    monkeypatch.setattr(llm, "ai_tutor", lambda question: f"回答：{question}")

    response = seeded_client.post("/api/ai-tutor", data={"question": "1+1=?"})

    assert response.status_code == 200
    assert response.json() == {"status": "success", "answer": "回答：1+1=?"}


def test_ai_tutor_strips_question_before_calling_llm(seeded_client, llm, monkeypatch):
    """入参应先 `strip()` 再交给 LLM。"""
    seen = []

    def fake_ai_tutor(question):
        seen.append(question)
        return "ok"

    monkeypatch.setattr(llm, "ai_tutor", fake_ai_tutor)
    seeded_client.post("/api/ai-tutor", data={"question": "  1+1=?  "})

    assert seen == ["1+1=?"]


@pytest.mark.parametrize(
    "blank",
    ["   ", "\n\t", " \t \n "],
    ids=["spaces", "newline-tab", "mixed"],
)
def test_ai_tutor_short_circuits_on_blank_question(seeded_client, llm, monkeypatch, blank):
    """纯空白问题直接返回错误，**不调用 LLM**。

    这里专打"省一次 API 调用"这一行为：若哪天有人删掉这段短路，
    测试会在调用计数上暴露出来。
    """
    calls = []
    monkeypatch.setattr(llm, "ai_tutor", lambda q: calls.append(q) or "should-not-happen")

    response = seeded_client.post("/api/ai-tutor", data={"question": blank})

    assert response.status_code == 200
    assert response.json() == {"status": "error", "answer": "问题不能为空"}
    assert calls == [], "空白问题不应触达 LLM"


def test_ai_tutor_empty_form_value_is_indistinguishable_from_missing(seeded_client):
    """**框架层陷阱**：空字符串的表单值会被当作"字段缺失"，压根进不到 handler。

        POST /api/ai-tutor  data={"question": ""}   →  422  type=missing

    后果：`server.py:3805` 那段

        if not question or not question.strip():

    里 `not question` 这半个条件**实际不可达**——空串在框架层就被拒了，
    真正会走到的只有纯空白（`not question.strip()`）。这在"原地跑一下看看"
    时极容易看岔：以为测的是路由的空值分支，其实测的是 FastAPI 的校验。

    记录该边界，也顺带说明上面那条参数化为何**不含 `""`**。
    """
    response = seeded_client.post("/api/ai-tutor", data={"question": ""})

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "missing"


def test_ai_tutor_falls_back_when_llm_returns_empty(seeded_client, llm, monkeypatch):
    """LLM 返回空串/None 时给兜底文案，而不是把空值透传出去。"""
    monkeypatch.setattr(llm, "ai_tutor", lambda q: "")

    response = seeded_client.post("/api/ai-tutor", data={"question": "1+1=?"})

    assert response.json()["answer"] == "抱歉，我暂时无法回答这个问题。"


def test_ai_tutor_reports_error_when_llm_raises(seeded_client, llm, monkeypatch):
    """LLM 抛异常时返回 error 结构，而不是 500。"""

    def boom(question):
        raise RuntimeError("上游炸了")

    monkeypatch.setattr(llm, "ai_tutor", boom)

    response = seeded_client.post("/api/ai-tutor", data={"question": "1+1=?"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert "上游炸了" in body["answer"]


# --------------------------------------------------------- /api/suggest-topic


def test_suggest_topic_returns_llm_suggestion(seeded_client, stub_chat_completion):
    """正常路径：把 LLM 的输出放进 `suggestion` 字段。"""
    response = seeded_client.post("/api/suggest-topic", data={"meeting_id": 1})

    assert response.status_code == 200
    assert response.json() == {"status": "success", "suggestion": "打桩生成的建议内容"}
    assert len(stub_chat_completion) == 1


def test_suggest_topic_prompt_includes_class_topic_and_transcripts(
    seeded_client, stub_chat_completion
):
    """提示词里必须带上课程主题与近期发言——这是该端点的全部价值所在。

    只看"返回了 200"是不够的：把 prompt 拼空的实现同样会返回 200。
    """
    seeded_client.post("/api/suggest-topic", data={"meeting_id": 1})

    prompt = stub_chat_completion[0]["messages"][0]["content"]
    assert "测试课堂：光合作用" in prompt, "提示词缺少课程主题"
    assert "李同学" in prompt, "提示词缺少近期发言"


def test_suggest_topic_missing_meeting_returns_error(seeded_client, stub_chat_completion):
    """课堂不存在时返回 error，且**不调用 LLM**。"""
    response = seeded_client.post("/api/suggest-topic", data={"meeting_id": 99999})

    assert response.json() == {"status": "error", "message": "会议不存在"}
    assert stub_chat_completion == []


# ---------------------------------------------------- /api/quiz-error-analysis


def test_quiz_error_analysis_short_circuits_when_no_wrong_questions(
    seeded_client, stub_chat_completion
):
    """错题列表为空时给表扬文案，**不调用 LLM**。"""
    response = seeded_client.post(
        "/api/quiz-error-analysis",
        data={"wrong_questions": "[]", "topic": "光合作用"},
    )

    assert response.json() == {"status": "success", "analysis": "没有错题，表现很棒！"}
    assert stub_chat_completion == []


def test_quiz_error_analysis_returns_llm_analysis(seeded_client, stub_chat_completion):
    """正常路径：把 LLM 的分析放进 `analysis` 字段。"""
    wrong = [{"question": "光合作用的产物是什么？", "correctAnswer": "葡萄糖和氧气"}]

    response = seeded_client.post(
        "/api/quiz-error-analysis",
        data={"wrong_questions": json.dumps(wrong, ensure_ascii=False), "topic": "光合作用"},
    )

    assert response.json() == {"status": "success", "analysis": "打桩生成的建议内容"}


def test_quiz_error_analysis_prompt_includes_question_and_answer(
    seeded_client, stub_chat_completion
):
    """提示词里必须带上题目与正确答案。"""
    wrong = [{"question": "光合作用的产物是什么？", "correctAnswer": "葡萄糖和氧气"}]

    seeded_client.post(
        "/api/quiz-error-analysis",
        data={"wrong_questions": json.dumps(wrong, ensure_ascii=False), "topic": "光合作用"},
    )

    prompt = stub_chat_completion[0]["messages"][1]["content"]
    assert "光合作用的产物是什么？" in prompt
    assert "葡萄糖和氧气" in prompt
    assert "光合作用" in prompt, "提示词缺少课程主题"


def test_quiz_error_analysis_falls_back_when_llm_fails(seeded_client, llm, monkeypatch):
    """LLM 失败时给本地兜底文案——该端点有意吞掉异常后继续返回 200。

    这条与 `test_ai_tutor_reports_error_when_llm_raises` 形成对照：
    两个端点对上游故障的处理策略**不同**，且都是既有行为，一并钉住。
    """
    wrong = [{"question": "光合作用的产物是什么？", "correctAnswer": "葡萄糖和氧气"}]

    def boom(**kwargs):
        raise RuntimeError("上游炸了")

    monkeypatch.setattr(llm.client.chat.completions, "create", boom)

    response = seeded_client.post(
        "/api/quiz-error-analysis",
        data={"wrong_questions": json.dumps(wrong, ensure_ascii=False), "topic": "光合作用"},
    )

    body = response.json()
    assert body["status"] == "success"
    assert "建议重点复习相关知识点" in body["analysis"]


def test_quiz_error_analysis_rejects_malformed_json(seeded_client, stub_chat_completion):
    """`wrong_questions` 不是合法 JSON 时返回 error，而不是 500。"""
    response = seeded_client.post(
        "/api/quiz-error-analysis",
        data={"wrong_questions": "{not json", "topic": "光合作用"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert stub_chat_completion == []
