# scripts/

| 脚本 | 用途 |
|---|---|
| `_auth.py` | 共享 Cookie / 会话 / list / transit / create / 关联校验 / AuthError |
| `check_auth.py` | 探测会话是否可用；失败打印刷新说明 |
| `refresh_cookies.py` | 从本机 Chrome 导出 Cookie → 当前系统临时目录 |
| `list_bug_anchors.py` | **挂载点选**：【测试】/需求字母表 + AskQuestion 载荷 |
| `list_test_tasks.py` | 拉【测试】待处理/处理中 |
| `list_bugs.py` | 按状态拉缺陷（默认已修复+暂不修复） |
| `create_bug.py` | **发起缺陷**（独立/测试用例共同入口；验证者强制当前登录用户；ASSOCIATED→【测试】） |
| `create_bug_openapi.py` | 机器已配置 PAT 时，通过官方 OpenAPI 发起非本期独立缺陷、上传附件并回读关键字段 |
| `comment_bug_openapi.py` | 机器已配置 PAT 时，通过官方 OpenAPI 发布缺陷评论并做幂等回读校验 |
| `transit_bug.py` | 测试侧流转：已修复→已关闭时强制逐Bug复测证据；再次打开保留原证据（含编号回读） |
| `yunxiao_cli_test_lifecycle.py` | **测试生命周期**：常规闭环校验test部署/TestHub/QA证据；人工确认通过时可用`manual-complete`同步任务与需求完成态（非发布候选） |
| `yunxiao_requirement_plan_monitor.py` | **每日新增需求监测**：仅01_ONEOS标题含`【新增】`的新需求；同迭代自动建14天测试计划；全可见用例库匹配后通知确认，不自动加用例 |
| `transit_test_lifecycle.py` | 旧Cookie兼容实现；新执行禁止使用 |
| `close_test_task.py` | 已停用的旧入口：固定拒绝写入并指向完整闭环命令 |
| `discover_bug_constants.py` | 早期探测（常量已写入 runtime-ids） |

## 鉴权

1. 优先读当前系统临时目录中的 `yunxiao_cookies.json`（含 `XSRF-TOKEN`、`AONE_SESSION`）
2. 否则读 Chrome `browser_cookie3`
3. 若 401 / 探测失败：

```bash
# Chrome 已登录 devops.aliyun.com 后：
skill-run refresh_cookies.py --probe
skill-run check_auth.py
```

不要把 Cookie 写入 Skill 仓库或缺陷描述。

机器已配置 `ALIBABA_CLOUD_YUNXIAO_ACCESS_TOKEN` 与
`ALIBABA_CLOUD_YUNXIAO_ORGANIZATION_ID` 时，非本期独立缺陷可使用：

```powershell
skill-run create_bug_openapi.py --title '【模块】问题' --assignee 张三 `
  --verifier 当前测试用户 --label 小程序-模块 --priority 中 --severity 3-一般 `
  --description-file C:\evidence\bug.html --file C:\evidence\shot.png --dry-run
```

去掉 `--dry-run` 后，脚本会执行精确标题查重、创建、附件上传，并回读标题、
状态、负责人、验证者、创建人、标签、优先级、严重程度与附件名称/大小。

每日需求监测使用相同 PAT/组织 ID，中心版默认接入点为
`https://openapi-rdc.aliyuncs.com`；Region 版另设
`ALIBABA_CLOUD_YUNXIAO_ENDPOINT`。首次成功运行默认只建立基线，不补建历史需求：

```powershell
# 预检
skill-run yunxiao_requirement_plan_monitor.py

# 已按Plan确认后，由每日自动化执行
skill-run yunxiao_requirement_plan_monitor.py --apply
```

输出中的`awaiting-case-confirmation`表示计划已建且找到用例，必须将计划ID、
用例库、用例ID和标题通知用户；收到逐批确认前不得把用例规划进计划。

## 示例

```powershell
# 在当前 Skill 工作目录执行
skill-run check_auth.py
skill-run list_test_tasks.py
skill-run list_bugs.py --status 已修复 --status 暂不修复

skill-run list_bug_anchors.py --gate test
skill-run list_bug_anchors.py --gate req --test-task DEMO-90

# 发起缺陷（先 --dry-run，Plan 确认后再实写）
skill-run create_bug.py --mode 本期 --source standalone --title '[模块] 问题简述' `
  --test-task DEMO-90 --assignee 沈辰 --dry-run
skill-run create_bug.py --mode 本期 --source standalone --title '[模块] 问题简述' `
  --test-task DEMO-90 --assignee 沈辰 `
  --description-html '<p>实际…</p><p>期望…</p>'

skill-run create_bug.py --mode 本期 --source test-case --test-case CASE-1001 `
  --title '[模块] 问题简述' --test-task DEMO-90 --assignee 沈辰 --dry-run

skill-run create_bug.py --mode 非本期 --source standalone --title '…' `
  --assignee 沈辰 --allow-no-test --dry-run

skill-run transit_bug.py --sn DEMO-91 --from 已修复 --to 已关闭 `
  --retest-case CASE-1001 --retest-execution RUN-9001 `
  --retest-evidence https://example.invalid/evidence/RUN-9001 `
  --environment test --deployed-version v2026.07.31.1 --verified-by USER-1 --dry-run

# 测试中记录证据（读取真实证据清单，不推进状态）
skill-run yunxiao_cli_test_lifecycle.py record --space-id <项目ID> `
  --test-sn ONEOS-343 --req-sn ONEOS-300 `
  --evidence-manifest C:\evidence\ONEOS-343.json `
  --idempotency-key qa-ONEOS-343-v1

# 开始测试（先预检；同一命令加 --apply 才写入）
skill-run yunxiao_cli_test_lifecycle.py start --space-id <项目ID> `
  --test-sn ONEOS-343 --req-sn ONEOS-300 `
  --idempotency-key qa-start-ONEOS-343

# 完成测试（先预检；同一命令加 --apply 才写入）
skill-run yunxiao_cli_test_lifecycle.py complete --space-id <项目ID> `
  --test-sn ONEOS-343 --req-sn ONEOS-300 `
  --evidence-manifest C:\evidence\ONEOS-343.json `
  --idempotency-key qa-ONEOS-343-v1

# 人工验证通过快捷闭环（先预检；Plan确认后加 --apply）
skill-run yunxiao_cli_test_lifecycle.py manual-complete --space-id <项目ID> `
  --test-sn ONEOS-343 --req-sn ONEOS-300 `
  --manual-verdict passed --idempotency-key qa-manual-ONEOS-343-v1
```

`create_bug.py` / `transit_bug.py` / `yunxiao_cli_test_lifecycle.py` 为写操作：须先走 YunxiaoQA **Plan 门禁**，用户确认后再加`--apply`或去掉旧脚本的`--dry-run`执行。`close_test_task.py`始终拒绝写入。
**禁止**用浏览器 DOM 点击改云效状态。

### `create_bug.py` 退出码

| code | 含义 |
|---|---|
| 0 | 成功（含当前用户=验证者、关联校验通过） |
| 2 | 鉴权失败 |
| 3 | 已建单但 ASSOCIATED 回读失败（须重试/UI 确认，勿事后补关联） |
| 4 | 已建单但当前会话用户无法解析，或验证者写入/回读不一致 |

### `close_test_task.py` / `transit_bug.py` 退出码

| code | 含义 |
|---|---|
| 0 | `transit_bug.py`成功（回读编号、状态和逐Bug复测证据通过） |
| 3 | `transit_bug.py`编号、状态或证据回读失败 |
| 4 | `close_test_task.py`已停用，固定拒绝写入 |
