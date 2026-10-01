# 第三方依赖内置副本 · **本目录有意为空**

归档结构把 `vendors/` 列为归档目标之一。本次**没有归入任何文件**，
这是有意的决定，理由有两条，**任一条都足以否决归档**。

---

## 唯一候选：`_tmp_agora_token_builder/`

### 理由一：它本就不是仓库内容

`_tmp_agora_token_builder/` 被 `.gitignore` 忽略（`.gitignore` 第 49 行）。

把它移进 `archive/vendors/`，在 git 层面等于**什么都没发生**——
源文件不在版本控制里，目标也不会进版本控制。最终只会得到一个
「只有一个文件（README）、内容为空」的目录。归档在这里没有意义。

### 理由二：它是**运行期条件引用**，移走会静默失效

`server.py` 的导入引导段里有这一段（阶段 3 归拢到 `app/core/paths.py` 之后仍在）：

```python
_SERVER_SYSPATH_ADDITIONS = [
    os.path.join(BASE_DIR, '_tmp_agora_token_builder'),
]
for _extra_dir in _SERVER_SYSPATH_ADDITIONS:
    if os.path.isdir(_extra_dir):
        sys.path.append(_extra_dir)
```

关键在 `os.path.isdir` 这个判断：**目录存在就挂 `sys.path`，不存在就跳过——
不报错、不提示、不留痕迹。** 也就是说，把它移走造成的后果是"这条 fallback
无声消失"，而不是"启动报错"。这类失败最难发现。

> 顺带一提：同样是这段代码，`server.py` 早期还**无条件**追加过一个 `'2'`。
> 那一处是空操作——`2/` 目录**从未存在过**，`append` 只是往 `sys.path` 里塞了
> 一条死路径。已在阶段 3 的归档提交中移除，并在
> `tests_safe/test_paths_anchor.py` 留下断言（`_EXPECTED_SYSPATH_DIRS` 只允许
> `_tmp_agora_token_builder` 一项）。

### 结论

`agora-token-builder==1.0.0` 已在 `requirements.txt` 中，本地解包版只是可替代的
fallback。**留着无成本，移走有隐性代价。**

本目录保留，以便将来确有需要内置第三方副本时归入。
