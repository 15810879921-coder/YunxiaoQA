# YunxiaoQA · 云效测试任务（Cursor / Agent Skill）

[![skills.sh](https://skills.sh/b/15810879921-coder/YunxiaoQA)](https://skills.sh/15810879921-coder/YunxiaoQA)

测试同学在 Cursor / Claude Code 等 Agent 里操作**阿里云效 Projex**：拉【测试】任务、发起缺陷、关闭/再次打开、闭环测试任务。  
**只做测试侧**；不建【开发】/【测试】任务、不创建迭代、不代开发标「已修复」。

## 发给测试 AI / 同事的一键安装

把下面整段发给同事的 Cursor / Claude Code / 其他 Agent 即可：

```text
根据以下命令帮我安装该 skills（全局 · Cursor）：
npx skills add 15810879921-coder/YunxiaoQA -a cursor -g -y
装完后对新开对话说「拉取测试任务」，并确认可用。
依赖：本机需 Python3，以及 pip3 install requests browser_cookie3；Chrome 已登录 devops.aliyun.com。
```

或同事自己在终端执行：

```bash
# 推荐：全局装到 Cursor
npx skills add 15810879921-coder/YunxiaoQA -a cursor -g -y

# 同时装 Cursor + Claude Code
npx skills add 15810879921-coder/YunxiaoQA -a cursor -a claude-code -g -y

# 仅当前项目
npx skills add 15810879921-coder/YunxiaoQA -a cursor -y
```

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
| 发起缺陷（本期 create 挂 ASSOCIATED + 校验） | ✅ `create_bug.py` |
| 发起缺陷（非本期） | ✅ |
| 已修复→已关闭 / 再次打开 | ✅ `transit_bug.py` |
| 闭环【测试】 | ✅（关联缺陷均已关闭/暂不修复） |
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
    └── transit_bug.py
```

## 安全说明

- 仓库**不含**账号密码、Cookie、`/tmp/yunxiao_cookies.json`
- 登录态只保存在本机；失效时用 `refresh_cookies.py`
- 写操作须 Plan 确认；测试侧禁止把缺陷改成「已修复 / 暂不修复」（开发侧职责）

## 与产品 / 开发 Skill 的关系

| Skill | 角色 |
|---|---|
| [YunxiaoPMapp](https://github.com/15810879921-coder/oneos-pm-skills) | 产品：记需求 → 交棒待开发 |
| 开发交付 Skill | 开发：分配【开发】、提测建【测试】 |
| **YunxiaoQA（本仓库）** | 测试：拉单、缺陷、关闭、闭环 |

## License

内部工具，按团队约定使用。见 [LICENSE](LICENSE)。
