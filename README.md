# YunxiaoQA · 云效测试任务（Agent Skill）

[![skills.sh](https://skills.sh/b/15810879921-coder/YunxiaoQA)](https://skills.sh/15810879921-coder/YunxiaoQA)

测试同学在支持 Skill 的 Agent 里操作**阿里云效 Projex**：拉【测试】任务、开始测试并同步需求、发起缺陷、关闭/再次打开、闭环测试并同步需求与父【交付】。
**只做测试侧**；不建【开发】/【测试】任务、不创建迭代、不代开发标「已修复」。

## 发给测试 AI / 同事的一键安装

使用 Agent 中立的安装命令，让安装器自行管理各客户端目录；生命周期交接不依赖任何安装路径。

```text
npx skills add 15810879921-coder/YunxiaoQA -a '*' -g -y
```

也可以明确选择客户端版本：

```bash
# Codex 版
npx skills add 15810879921-coder/YunxiaoQA -a codex -g -y

# Cursor 版
npx skills add 15810879921-coder/YunxiaoQA -a cursor -g -y
```

仓库同时提供两套离线包：`packages/codex/YunxiaoQA.zip` 与 `packages/cursor/YunxiaoQA.zip`。两个版本共享业务规则；Codex 包额外包含 `agents/openai.yaml`。SHA-256 记录在各目录的 `manifest.json`。

重新构建双版本包：

```powershell
pwsh -File ./tools/build-dual-client-packages.ps1
```

安装完成后，由 Agent 使用本 Skill 启动器选择本机 Python 3；如缺少依赖，再在用户确认后为该解释器安装 `requirements.txt`，不在业务文档中固定平台命令。

### 安装后自查

| 现象 | 原因 | 处理 |
|---|---|---|
| `npx` / `skills` 报错 | 无 Node.js 或网络拉不下 GitHub | 装 Node 18+；能打开 github.com |
| 当前客户端看不到 Skill | 客户端尚未刷新 Skill 清单 | 确认安装命令成功后重启客户端或新开会话 |
| 能调起 Skill 但拉云效失败 | 无 Cookie / 无 Python 依赖 | 让 Agent 通过本 Skill 启动器确认解释器和依赖，Chrome 登录后运行刷新脚本 |

更新：

```bash
npx skills update YunxiaoQA
```

仓库：https://github.com/15810879921-coder/YunxiaoQA

## 测试同学：改技能并推回仓库

本仓库对协作者开放 **Write**，测试可根据使用踩坑直接优化并 `git push`。  
完整流程见 **[CONTRIBUTING.md](CONTRIBUTING.md)**（拿权限 → clone → 改 → 推 → `npx skills update`）。

管理员邀请示例：

```bash
gh api -X PUT repos/15810879921-coder/YunxiaoQA/collaborators/<GitHub用户名> -f permission=push
```

被邀请人须在 GitHub **接受邀请** 后才能推送。不要只改 `npx skills` 安装目录——请改本仓库 clone，再让同事 `npx skills update YunxiaoQA`。

## 装完后怎么用

对新开的 Agent 说：

```text
拉取测试任务
发起缺陷：标题=…；测试任务=ONEOS-xx；负责人=…
从测试用例发起缺陷：测试用例=CASE-xx；标题=…；测试任务=ONEOS-xx；负责人=…
发起缺陷(非本期)：标题=…；负责人=…
拉取待验缺陷
批量关闭已修复：缺陷=ONEOS-a,ONEOS-b；逐条提供复测用例、复测执行、test版本、证据和当前验证人
再次打开：缺陷=ONEOS-xx；原因=复现说明
完成测试：测试任务=ONEOS-xx；需求=ONEOS-yy；证据清单=<oneos.qa-evidence/v1 JSON文件>
```

凡**写云效**会先进入 Plan，你确认后再执行。

## 本机依赖

| 依赖 | 说明 |
|---|---|
| Node.js | 用于 `npx skills` |
| Python 3 | 运行 `scripts/*.py` |
| `requests` / `browser_cookie3` | 由本 Skill 启动器选定的 Python 3 安装 `requirements.txt` |
| Chrome | 已登录 https://devops.aliyun.com |

鉴权探测 / 刷新 Cookie：

```text
skill-run check_auth.py
skill-run refresh_cookies.py --probe
```

`skill-run` 的 Windows/macOS/Linux 解析规则见 `references/runtime-launcher.md`。

## 能力一览

| 能力 | 状态 |
|---|---|
| 拉取【测试】已分配/处理中 | ✅ |
| 挂载点选【测试】/需求 | ✅ `list_bug_anchors.py` + AskQuestion |
| 独立发起缺陷（当前用户=验证者；ASSOCIATED→【测试】） | ✅ `create_bug.py --source standalone` |
| 从测试用例发起缺陷（同一验证者门禁） | ✅ `create_bug.py --source test-case` |
| 发起缺陷（非本期） | ✅ |
| 已修复→已关闭 / 再次打开 | ✅ `transit_bug.py`；关闭时强制逐Bug复测证据 |
| 开始/完成测试并同步关联状态 | ✅ `transit_test_lifecycle.py`（开始双侧、完成三侧逐项回读） |
| 测试计划/执行/报告证据 | ✅ 读取`oneos.qa-evidence/v1`真实JSON清单并记录SHA-256，不接受口令自报 |
| 发布/验收失败修复回流 | ✅ 接收回流→正式Bug→开发修复→逐Bug复测→回归→重新发布 |

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
    ├── run-skill-script.ps1
    ├── run-skill-script.sh
    ├── check_auth.py
    ├── refresh_cookies.py
    ├── list_test_tasks.py
    ├── list_bugs.py
    ├── create_bug.py
    ├── transit_bug.py
    ├── transit_test_lifecycle.py
    └── close_test_task.py（已停用，只返回完整闭环命令）
```

## 安全说明

- 仓库**不含**账号密码或 Cookie；临时 Cookie 只写入当前系统临时目录
- 登录态只保存在本机；失效时用 `refresh_cookies.py`
- 写操作须 Plan 确认；测试侧禁止把缺陷改成「已修复 / 暂不修复」（开发侧职责）
- 所有测试侧建缺陷路径强制`验证者=当前登录用户`并回读；不接受固定默认人或口令覆盖
- 正常需求必须已有成功`oneos.test-deployment/v1`才可开始测试；完成测试必须校验真实QA证据清单、实时Bug快照和逐Bug复测证据
- **禁止**用浏览器 DOM / 可交互节点改云效状态（防编号串单）

## 与产品 / 开发 Skill 的关系

| Skill | 角色 |
|---|---|
| [YunxiaoPM](https://github.com/15810879921-coder/oneos-pm-skills) | 产品：记需求 → 交棒待开发 |
| yunxiao-development-delivery | 开发：分配【开发】、提测建【测试】 |
| **YunxiaoQA（本仓库）** | 测试：拉单、缺陷、关闭、闭环 |

## License

内部工具，按团队约定使用。见 [LICENSE](LICENSE)。
