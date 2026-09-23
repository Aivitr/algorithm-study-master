"""
简单的 Gemma API 测试
"""
import requests

OLLAMA_URL = "http://localhost:11434"
MODEL = "gemma4:e4b"

print("=" * 50)
print("1. 检查 Ollama 服务状态")
print("=" * 50)

try:
    response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
    print(f"✓ 服务正常: {response.status_code}")
    data = response.json()
    print(f"可用模型: {[m['name'] for m in data.get('models', [])]}")
except Exception as e:
    print(f"✗ 服务连接失败: {e}")
    exit(1)

print("\n" + "=" * 50)
print("2. 测试 Gemma API 调用 (/api/chat)")
print("=" * 50)

prompt = """你是一个面部情绪识别专家。根据以下面部特征描述，判断人物情绪。

面部特征: 嘴角上扬，呈现微笑表情，嘴巴闭合，眼睛睁大

可选情绪标签: happy, sad, angry, surprised, neutral, excited, confused, thinking, calm

请仅输出:
emotion: [情绪标签]
confidence: [0.0-1.0]
"""

try:
    response = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": False,  # 禁用 thinking 模式
            "options": {"temperature": 0.1, "num_predict": 100}
        },
        timeout=60
    )
    print(f"响应状态: {response.status_code}")
    print(f"响应内容: {response.text[:800]}")

    if response.status_code == 200:
        result = response.json()
        content = result.get("message", {}).get("content", "")
        if not content:
            content = result.get("message", {}).get("thinking", "")
        print(f"\n✓ Gemma 回答: {content}")
    else:
        print(f"✗ API 错误")

except Exception as e:
    print(f"✗ 调用失败: {e}")

print("\n" + "=" * 50)
print("测试完成!")
print("=" * 50)
