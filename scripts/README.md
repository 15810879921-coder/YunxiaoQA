# scripts/

| 脚本 | 用途 |
|---|---|
| `_auth.py` | 共享 Cookie / 会话 / list / transit / create / 关联校验 / AuthError |
| `check_auth.py` | 探测会话是否可用；失败打印刷新说明 |
| `refresh_cookies.py` | 从本机 Chrome 导出 Cookie → 当前系统临时目录 |
| `list_bug_anchors.py` | **挂载点选**：【测试】/需求字母表 + AskQuestion 载荷 |
| `list_test_tasks.py` | 拉【测试】已分配/处理中（待处理仅兼容历史任务） |
| `list_bugs.py` | 按状态拉缺陷（默认已修复+暂不修复） |
| `create_bug.py` | **发起缺陷**（独立/测试用例共同入口；验证者强制当前登录用户；ASSOCIATED→【测试】） |
| `transit_bug.py` | 测试侧流转：已修复→已关闭时强制逐Bug复测证据；再次打开保留原证据（含编号回读） |
| `transit_test_lifecycle.py` | **完整测试闭环**：开始时【测试】已分配→处理中、需求→测试中；完成时同步【测试】、需求与父【交付】，写证据并回读 |
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

# 开始测试（先 dry-run；禁止浏览器点状态）
skill-run transit_test_lifecycle.py start --test-sn ONEOS-343 --req-sn ONEOS-300 --dry-run

# 测试中记录证据（读取真实证据清单，不推进状态）
skill-run transit_test_lifecycle.py record --test-sn ONEOS-343 --req-sn ONEOS-300 `
  --evidence-manifest C:\evidence\ONEOS-343.json --dry-run

# 完成测试（先dry-run；必须提供真实证据清单）
skill-run transit_test_lifecycle.py complete --test-sn ONEOS-343 --req-sn ONEOS-300 `
  --evidence-manifest C:\evidence\ONEOS-343.json --dry-run
```

`create_bug.py` / `transit_bug.py` / `transit_test_lifecycle.py` 为写操作：须先走 YunxiaoQA **Plan 门禁**，用户确认后再去掉 `--dry-run` 执行。`close_test_task.py`始终拒绝写入。
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
