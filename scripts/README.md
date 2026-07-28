# scripts/

| 脚本 | 用途 |
|---|---|
| `_auth.py` | 共享 Cookie / 会话 / list / transit / create / 关联校验 / AuthError |
| `check_auth.py` | 探测会话是否可用；失败打印刷新说明 |
| `refresh_cookies.py` | 从本机 Chrome 导出 Cookie → `/tmp/yunxiao_cookies.json` |
| `list_test_tasks.py` | 拉【测试】待处理/处理中 |
| `list_bugs.py` | 按状态拉缺陷（默认已修复+暂不修复） |
| `create_bug.py` | **发起缺陷**（本期强制 create 时 ASSOCIATED + 回读校验） |
| `transit_bug.py` | 测试侧流转：已修复→已关闭 / 再次打开 |
| `discover_bug_constants.py` | 早期探测（常量已写入 runtime-ids） |

## 鉴权

1. 优先读 `/tmp/yunxiao_cookies.json`（含 `XSRF-TOKEN`、`AONE_SESSION`）
2. 否则读 Chrome `browser_cookie3`
3. 若 401 / 探测失败：

```bash
# Chrome 已登录 devops.aliyun.com 后：
python3 scripts/refresh_cookies.py --probe
python3 scripts/check_auth.py
```

不要把 Cookie 写入 Skill 仓库或缺陷描述。

## 示例

```bash
cd ~/.cursor/skills/YunxiaoQA
python3 scripts/check_auth.py
python3 scripts/list_test_tasks.py
python3 scripts/list_bugs.py --status 已修复 --status 暂不修复

# 发起缺陷（先 --dry-run，Plan 确认后再实写）
python3 scripts/create_bug.py --mode 本期 --title '[模块] 问题简述' \
  --test-task DEMO-90 --assignee 沈辰 --verifier 王冕 --dry-run
python3 scripts/create_bug.py --mode 本期 --title '[模块] 问题简述' \
  --test-task DEMO-90 --assignee 沈辰 --verifier 王冕 \
  --description-html '<p>实际…</p><p>期望…</p>'

python3 scripts/create_bug.py --mode 非本期 --title '…' \
  --assignee 沈辰 --verifier 王冕 --allow-no-associate --dry-run

python3 scripts/transit_bug.py --sn DEMO-91 --from 已修复 --to 已关闭 --dry-run
```

`create_bug.py` / `transit_bug.py` 为写操作：须先走 YunxiaoQA **Plan 门禁**，用户确认后再去掉 `--dry-run` 执行。

### `create_bug.py` 退出码

| code | 含义 |
|---|---|
| 0 | 成功（含关联校验通过） |
| 2 | 鉴权失败 |
| 3 | 已建单但 ASSOCIATED 回读失败（须重试/UI 确认，勿事后补关联） |
