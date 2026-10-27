# 仓库协作与 Git 工作流（0 基础版）

> 先读：[菜鸟教程 Git 教程](https://www.runoob.com/git/git-tutorial.html)
>
> 本文假设你从没系统用过 Git。按顺序读完，再照着命令做即可。

## 0. 先认识这些词

在菜鸟教程里按下面的关键词找对应章节，学到“知道它是干什么的”就够开始干活了：

| 关键词 | 一句话解释 | 本文哪里会用到 |
|---|---|---|
| 仓库（repository） | 存放代码和全部历史的地方 | 全文 |
| 克隆（clone） | 把远程仓库完整复制到本机 | 第一次准备 |
| 远程（remote / origin） | 本机仓库对应的服务器地址 | 拉取、推送 |
| 分支（branch） | 一条独立的开发线，互不干扰 | 全文 |
| 切换（switch / checkout） | 从一条分支换到另一条 | 每天开工 |
| 拉取（pull） | 把远程最新代码取回并合并到当前分支 | 每天开工、组长同步 |
| 获取（fetch） | 只取回远程信息，不自动合并 | 组长同步 main |
| 合并（merge） | 把另一条分支的改动并进当前分支 | 组长同步、冲突处理 |
| 暂存（add） | 挑选这次要提交的文件 | 提交前 |
| 提交（commit） | 在本地留下一版记录 | 开发中 |
| 推送（push） | 把本地提交发到远程仓库 | 提交后 |
| 状态（status） | 看当前改了哪些文件 | 随时 |
| 差异（diff） | 看具体改了哪几行 | 提交前 |
| 日志（log） | 看历史提交 | 排查问题 |
| PR（Pull Request） | GitHub 上的“合并申请”，让别人审核后再合 | 每次交付 |
| 冲突（conflict） | 两个人改了同一处，Git 无法自动决定 | 同步代码时 |

---

## 1. 为什么要改协作方式

以前的做法是：

- 课堂系统（后端 / Agent）一个仓库，按 Git 规范合作；
- 算法组**另开一个独立仓库**，脱离主项目环境开发；
- 最后再把算法仓库的内容“人工迁移”进主仓库。

问题：

- 两边环境、依赖、数据格式不一致，最后合并时才发现；
- 迁移靠人搬代码，沟通和返工成本极大；
- 算法代码进入主仓库前，没人能在真实项目里验证它。

**从今天起改为一个仓库、标准 Git 流程：**

- 算法代码也放进本仓库，在 `feat/gca` 分支开发；
- Agent / 后端在 `feat/agent` 分支开发；
- 两个组各自的成员再从组分支签出个人分支；
- 组长审核后，把组分支合并进 `main`；
- `main` 只存放最终正式版。

---

## 2. 分支模型

```
main                        正式版，只由组长合并
├── feat/agent              Agent / 后端组的集成分支
│   ├── feature/agent-登录拆分
│   ├── feature/agent-GCA工具
│   └── feature/agent-xxx
└── feat/gca                算法组的集成分支
    ├── feature/gca-中文分词
    ├── feature/gca-时间窗口
    └── feature/gca-xxx
```

规则只有五条：

1. **`main` 不直接开发。** 任何人都不在 `main` 上改代码，也不向 `main` 提 PR。
2. **组分支只由组长维护。** `feat/agent` 由 Agent 组长维护，`feat/gca` 由算法组长维护。
3. **个人分支从组分支签出。** 例如 Agent 组：`feat/agent` → `feature/agent-xxx`。
4. **个人 PR 只能提到自己的组分支。** 不能提到 `main`，也不能提到另一个组的分支。
5. **只有组长能把组分支合并到 `main`。** 合并前必须跑测试、有人复核。

---

## 3. 一次性准备

1. 安装 Git（菜鸟教程「Git 安装」一节）。
2. 设置你的身份。**邮箱必须是你在 GitHub 账号里已验证的邮箱**，否则提交不会算到你名下：

```bash
git config --global user.name "你的名字"
git config --global user.email "你的GitHub已验证邮箱"
```

3. 克隆仓库：

```bash
git clone https://github.com/sakura032/algorithm-study-master.git
cd algorithm-study-master
```

4. 确认远程地址：

```bash
git remote -v
```

正常应看到 `origin` 指向上面的仓库。

---

## 4. 开发者每天怎么干活（以 Agent 组为例）

### 第一步：同步组分支

```bash
git switch feat/agent
git pull origin feat/agent
```

> 老版本 Git 没有 `switch`，用 `git checkout feat/agent`。

### 第二步：从组分支签出个人分支

```bash
git switch -c feature/agent-<你的任务名>
```

任务名用英文或拼音，短一点，例如 `feature/agent-login-split`。

### 第三步：开发、查看、提交

```bash
git status                 # 看改了哪些文件
git diff                   # 看具体改了什么
git add <具体文件>          # 一次只加这次要提交的文件
git commit -m "feat(agent): 一句话说明做了什么"
```

**不要用 `git add .`**，它会把无关文件、临时文件、甚至密钥一起提交上去。

提交信息建议格式：

```
feat(agent): 新增 GCA 指标工具
fix(gca): 修复中文分词空文本
docs: 补充协作说明
refactor: 抽出 Transcript 查询服务
test: 补 GCA 指标边界用例
```

### 第四步：推送到远程

```bash
git push -u origin feature/agent-<你的任务名>
```

第一次推送加 `-u`，以后直接 `git push` 即可。

### 第五步：发 PR

在 GitHub 页面上：

1. 点 **Compare & pull request**；
2. **Base 分支必须选 `feat/agent`**，不是 `main`；
3. 写清楚：改了什么、为什么改、怎么验证的（跑了哪些测试）；
4. 指定 Agent 组长 review；
5. 不要自己点合并。

### 第六步：组长要求修改

不需要重新开分支。在原分支继续提交、推送即可，PR 会自动更新：

```bash
git add <文件>
git commit -m "fix(agent): 按 review 意见调整"
git push
```

### 第七步：合并之后

组长合并 PR 后：

```bash
git switch feat/agent
git pull origin feat/agent
git branch -d feature/agent-<你的任务名>   # 删除本地个人分支
```

---

## 5. 组长怎么维护

### 5.1 审核个人 PR

- 只看两点：**改得对不对**、**测试有没有跑**；
- 确认 base 是 `feat/agent`（或 `feat/gca`），不是 `main`；
- 合并方式统一用 **Create a merge commit**，不要用 Rebase；
- 合并后删除远程个人分支。

### 5.2 把组分支合并到 main（发布）

推荐用 PR，让另一位组长复核：

1. 从 `feat/agent` 向 `main` 发 PR；
2. 标题写清楚本次发布内容；
3. 合并前在本地或 CI 跑全量测试；
4. 合并后 `main` 就是正式版。

### 5.3 把 main 的最新内容同步回组分支（非常重要）

`main` 会不断前进。如果不把 `main` 合回 `feat/agent` / `feat/gca`，
组员从组分支同步到的就是旧代码，最后合并时又会爆发冲突。

组长定期执行（建议每次发布后、以及每周至少一次）：

```bash
git switch feat/agent
git pull origin feat/agent
git fetch origin main
git merge origin/main
# 如果有冲突，按第 7 节处理
git push origin feat/agent
```

算法组同理，把 `feat/agent` 换成 `feat/gca`。

### 5.4 组与组之间需要对方的代码

不要让个人分支去合并另一个组的分支。正确顺序：

1. 需要的那部分先由对方组长合进 `main`；
2. 你的组长把 `main` 同步到自己的组分支；
3. 你再从组分支同步。

这样依赖永远只沿 `main → 组分支 → 个人分支` 一个方向流动，不会出现“分支互相合并”的乱麻。

---

## 6. 算法组的额外约定

1. 算法代码放在本仓库内（例如 `gca_engine/`），**不要**再单独建一个脱离项目的仓库；
2. 开发时使用本仓库的虚拟环境和依赖文件，不要在另一个目录另起一套环境；
3. 算法组在 `feat/gca` 上开发，个人分支 `feature/gca-xxx`；
4. 算法与后端的衔接通过固定的 Service 接口完成；接口变更必须在 PR 描述里写明，
   并通知 Agent 组长；
5. 算法代码进入 `main` 前，必须能在本仓库的测试体系里跑通。

---

## 7. 遇到冲突怎么办

冲突的意思是：两个人改了同一个文件的同一处，Git 不知道该听谁的。

处理步骤：

```bash
git switch feature/agent-<任务>
git fetch origin feat/agent
git merge origin/feat/agent
```

Git 会列出冲突文件。打开文件，会看到：

```
<<<<<<< HEAD
你的版本
=======
组分支的版本
>>>>>>> origin/feat/agent
```

1. 手工保留正确的内容，删掉 `<<<<<<<`、`=======`、`>>>>>>>` 这三行标记；
2. 确认代码还能跑；
3. 继续：

```bash
git add <解决完的文件>
git commit
git push
```

不会处理时，**不要随便删别人的代码**，在群里叫上改动另一方一起看。

---

## 8. 0 基础最容易犯的错

| 错误 | 后果 | 正确做法 |
|---|---|---|
| 在 `main` 上直接改代码 | 正式版被污染 | 先切到组分支，再签个人分支 |
| PR 的 base 选成 `main` | 绕过组长审核 | base 必须是 `feat/agent` 或 `feat/gca` |
| 很久不 `pull` | 分支落后，合并时大冲突 | 每天开工先 `git pull origin <组分支>` |
| `git add .` | 把临时文件/密钥提交上去 | 只 `git add` 本次改的文件 |
| 冲突时直接删对方代码 | 功能丢失 | 叫上对方一起确认 |
| `git push --force` 到共享分支 | 覆盖别人的提交 | 禁止对 `feat/*`、`main` 强推 |
| 用错邮箱提交 | GitHub 不显示你的贡献 | 按第 3 节设置已验证邮箱 |
| 还在用“独立算法仓库” | 重复旧的高成本合并 | 算法代码直接进本仓库 `feat/gca` |

---

## 9. 一页速查

```bash
# 每天开工
git switch feat/agent          # 或 feat/gca
git pull origin feat/agent

# 开新任务
git switch -c feature/agent-xxx

# 提交
git status
git diff
git add <文件>
git commit -m "feat(agent): ..."
git push -u origin feature/agent-xxx

# 组长同步 main 到组分支
git switch feat/agent
git pull origin feat/agent
git fetch origin main
git merge origin/main
git push origin feat/agent

# 组分支发布到 main
git switch main
git pull origin main
git merge --no-ff feat/agent
git push origin main
```

---

## 10. 记住三句话

1. **`main` 只进不出（对人）：只有组长能合进去。**
2. **个人分支只往组分支提 PR，永远不提给 `main`。**
3. **组长要定期把 `main` 同步回组分支，组员才能拿到最新代码。**

---

## 11. 术语对照（看教程时用）

- 菜鸟教程里的「工作区」= 你正在编辑的文件；
- 「暂存区」= `git add` 之后、`git commit` 之前的那一层；
- 「版本库」= `.git` 目录里的提交历史；
- 「远程仓库」= GitHub 上的 `origin`；
- 「快进合并（fast-forward）」= 没有分叉时直接移动分支指针；
- 「合并提交（merge commit）」= 有分叉时生成的一次合并记录。

遇到教程和本文命令写法不同（例如 `checkout` 与 `switch`），以能完成同样动作为准；
团队内统一优先使用本文的写法。
