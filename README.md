# YunxiaoQA · 云效测试任务（Cursor / Agent Skill）

[![skills.sh](https://skills.sh/b/15810879921-coder/YunxiaoQA)](https://skills.sh/15810879921-coder/YunxiaoQA)

测试同学在 Cursor / Claude Code 等 Agent 里操作**阿里云效 Projex**：拉【测试】任务、发起缺陷、关闭/再次打开、闭环测试任务。  
**只做测试侧**；不建【开发】/【测试】任务、不创建迭代、不代开发标「已修复」。

## 发给测试 AI / 同事的一键安装

按同事用的 **Agent 选一段**（不要混用）。写死 `-a cursor` 时，**Codex 装不上 / 装完也读不到**。

### A. Cursor

```text
根据以下命令帮我安装该 skills（全局 · Cursor）：
npx skills add 15810879921-coder/YunxiaoQA -a cursor -g -y
装完后对新开对话说「拉取测试任务」，并确认可用。
依赖：本机需 Python3，以及 pip3 install requests browser_cookie3；Chrome 已登录 devops.aliyun.com。
```

### B. Codex（测试同事常用）

```text
根据以下命令帮我安装该 skills（全局 · Codex）：
npx skills add 15810879921-coder/YunxiaoQA -a codex -g -y
# 若 Codex 仍列不出 YunxiaoQA，再执行保险链接：
mkdir -p ~/.codex/skills && ln -sfn ~/.agents/skills/yunxiaoqa ~/.codex/skills/yunxiaoqa
pip3 install requests browser_cookie3
装完后重启 Codex / 新开会话，说「拉取测试任务」或用 $YunxiaoQA。
依赖：Node.js（npx）、Python3、Chrome 已登录 devops.aliyun.com。
```

### C. 终端（多 Agent 一次装齐）

```bash
# Cursor + Codex（推荐给测试同学）
npx skills add 15810879921-coder/YunxiaoQA -a cursor -a codex -g -y
mkdir -p ~/.codex/skills && ln -sfn ~/.agents/skills/yunxiaoqa ~/.codex/skills/yunxiaoqa
pip3 install requests browser_cookie3

# 或装到本机检测到的全部 Agent
npx skills add 15810879921-coder/YunxiaoQA -a '*' -g -y
```

### Codex 装不上时怎么自查

| 现象 | 原因 | 处理 |
|---|---|---|
| 命令里有 `-a cursor` | 只装 Cursor，不写 Codex | 改用 `-a codex` 或 `-a cursor -a codex` |
| `npx` / `skills` 报错 | 无 Node.js 或网络拉不下 GitHub | 装 Node 18+；能打开 github.com |
| skills 显示已安装，Codex 看不到 | CLI 常只落到 `~/.agents/skills/`，而 Codex 用户级目录是 `~/.codex/skills/` | 执行上方 `ln -sfn …` 后**重启 Codex** |
| 能调起 Skill 但拉云效失败 | 无 Cookie / 无 Python 依赖 | `pip3 install …` + Chrome 登录后 `python3 scripts/refresh_cookies.py --probe` |

更新：

```bash
npx skills update YunxiaoQA
```

仓库：https://github.com/15810879921-coder/YunxiaoQA

## 装完后怎么用

对新开的 Agent 说：

```text
拉取测试任务
发起缺陷：标题=…；测试任务=ONEOS-xx；负责人=…
发起缺陷(非本期)：标题=…；负责人=…；验证者=…
拉取待验缺陷
批量关闭已修复：缺陷=ONEOS-a,ONEOS-b
再次打开：缺陷=ONEOS-xx；原因=复现说明
闭环测试任务：测试任务=ONEOS-xx
```

凡**写云效**会先进入 Plan，你确认后再执行。

## 本机依赖

| 依赖 | 说明 |
|---|---|
| Node.js | 用于 `npx skills` |
| Python 3 | 运行 `scripts/*.py` |
| `requests` / `browser_cookie3` | `pip3 install -r requirements.txt` |
| Chrome | 已登录 https://devops.aliyun.com |

鉴权探测 / 刷新 Cookie：

```bash
cd ~/.cursor/skills/YunxiaoQA   # 或 Agent 安装后的技能目录
python3 scripts/check_auth.py
python3 scripts/refresh_cookies.py --probe
```

## 能力一览

| 能力 | 状态 |
|---|---|
| 拉取【测试】待处理/处理中 | ✅ |
| 挂载点选【测试】/需求 | ✅ `list_bug_anchors.py` + AskQuestion |
| 发起缺陷（ASSOCIATED→【测试】；需求描述追溯） | ✅ `create_bug.py` |
| 发起缺陷（非本期） | ✅ |
| 已修复→已关闭 / 再次打开 | ✅ `transit_bug.py` |
| 闭环【测试】 | ✅ `close_test_task.py`（`--sn` + 回读；禁止浏览器点状态） |
| 用例库精确执行 | ❌ 需另装 `$yunxiao-test-management` |

## 目录结构

```text
.
├── SKILL.md
├── README.md
├── LICENSE
├── requirements.txt
├── assets/runtime-ids.json
├── references/
└── scripts/
    ├── check_auth.py
    ├── refresh_cookies.py
    ├── list_test_tasks.py
    ├── list_bugs.py
    ├── create_bug.py
    ├── transit_bug.py
    └── close_test_task.py
```

## 安全说明

- 仓库**不含**账号密码、Cookie、`/tmp/yunxiao_cookies.json`
- 登录态只保存在本机；失效时用 `refresh_cookies.py`
- 写操作须 Plan 确认；测试侧禁止把缺陷改成「已修复 / 暂不修复」（开发侧职责）
- **禁止**用浏览器 DOM / 可交互节点改云效状态（防编号串单）

## 与产品 / 开发 Skill 的关系

| Skill | 角色 |
|---|---|
| [YunxiaoPMapp](https://github.com/15810879921-coder/oneos-pm-skills) | 产品：记需求 → 交棒待开发 |
| 开发交付 Skill | 开发：分配【开发】、提测建【测试】 |
| **YunxiaoQA（本仓库）** | 测试：拉单、缺陷、关闭、闭环 |

## License

内部工具，按团队约定使用。见 [LICENSE](LICENSE)。
