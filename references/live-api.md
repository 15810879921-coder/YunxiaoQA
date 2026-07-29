# 实写 API（测试任务）

与 YunxiaoPM 共用 Projex 会话；**禁止**把凭证写入 Skill 或缺陷描述。

通用约定见 `~/.cursor/skills/YunxiaoPM/references/live-api.md`。常量以本 Skill [assets/runtime-ids.json](../assets/runtime-ids.json) 为准（2026-07-27 在 `01_ONEOS` 实网验证）。

**鉴权提示：** 本机 Chrome `browser_cookie3` 可能 `invalid session`；已登录的 Cursor/浏览器页内 `fetch(..., {credentials:'include'})` 可用。优先复用有效会话。

刷新流程（本机）：

```bash
# Chrome 已登录 devops.aliyun.com
python3 scripts/refresh_cookies.py --probe   # 写入 /tmp/yunxiao_cookies.json 并探测
python3 scripts/check_auth.py                # 仅探测；失败会打印 AUTH_HELP
```

脚本遇 401/未登录会抛 `AuthError` 并附刷新说明；**禁止**把 Cookie 写入 Skill 或缺陷描述。

## 读

| 目的 | API |
|---|---|
| 缺陷/任务列表 | `POST /projex/api/workitem/workitem/list?_input_charset=utf-8`（见 runtime-ids `search`） |
| 工作项详情 | `GET /projex/api/workitem/workitem/{id}` |
| 验证者等额外字段 | `GET /projex/api/workitem/workitem/{id}/extra` → `workitem.verifier` |
| 关联列表 | `GET /projex/api/workitem/v2/workitem/{id}/relation/workitem/list/by-relation-category?category=ASSOCIATED\|PARENT_SUB&isForward=true` |
| 下一状态 | `GET /projex/api/workitem/workitem/{id}/nextStatus/list?currentStatusIdentifier={from}` |
| Bug 字段字典 | `GET /projex/api/workitem/workitem/field/listAllFields?spaceType=Project&spaceIdentifier={space}&categoryIdentifier=Bug` |

拉【测试】：`category=Task` + 标题前缀 `【测试】` + 状态 `待处理`/`处理中`。

## 写 · 状态流转

```http
POST /projex/api/workitem/workitem/{id}/status/transit?_input_charset=utf-8
{"fromStatus":"<当前status.identifier>","toStatus":"<目标status.identifier>"}
```

成功：`code=200` 且 `result=true`。

### 缺陷状态 ID（01_ONEOS）

| 显示名 | identifier | 说明 |
|---|---|---|
| 待确认 | `28` | 新建默认；口令统一用此名 |
| 处理中 | `100010` | |
| 已修复 | `29` | |
| 再次打开 | `30` | |
| 暂不修复 | `31` | |
| 已关闭 | `100085` | |

### 任务状态 ID

| 显示名 | identifier |
|---|---|
| 待处理 | `100005` |
| 处理中 | `100010` |
| 已完成 | `100014` |
| 已取消 | `141230` |

### 测试常用迁移

| 从 → 到 | 口令 |
|---|---|
| 已修复 → 已关闭 | `批量关闭已修复` |
| 已修复 → 再次打开 | `再次打开` |
| （任务）→ 已完成 | `闭环测试任务` |

**禁止**测试侧：`→已修复` / `→暂不修复` / `→处理中`（开发 Skill）。

## 写 · 建缺陷

优先用脚本（含强制关联校验）：

```bash
python3 scripts/create_bug.py --mode 本期 --title '…' --test-task DEMO-xx \
  --assignee 沈辰 --verifier 王冕 --description-html '<p>…</p>'
```

```http
POST|PUT /projex/api/workitem/workitem?_input_charset=utf-8
```

- `workitemType` / `workitemTypeIdentifier` = `37da3a07df4d08aef2e3b393`
- `category` = `Bug`
- 负责人：`assignedTo`
- 验证者：`workitem.verifier`（user id）
- 优先级 / 严重程度：见 runtime-ids `fields.priority` / `seriousLevel`
- 描述：`PATCH …/workitem/{id}/document`，`{"content":"<html>","formatType":"RICHTEXT"}`
- **本期关联（强制）**：
  1. `createWorkitemRelationInfo` = `ASSOCIATED` →【测试】；回读 ASSOCIATED（**勿用 TASK_SUB/父子**）
  2. 再 `ASSOCIATED`→需求（bug→req，失败则 req→bug）；回读
  3. 任一失败 → 脚本退出码 3

新建默认状态一般为 **待确认**。

## 写 · 关联 / 迭代

关联：`POST /projex/api/workitem/workitem/{id}/relation/record`（`ASSOCIATED` 等，与 YunxiaoPM 一致）。

**注意：** 缺陷对【测试】/交付的 ASSOCIATED **应在 create 时挂上**；事后 `relation/record` 在 DEMO/ONEOS 常报「不能关联相同的工作项」，不可作为主路径。

挂迭代：

```http
PATCH /projex/api/workitem/workitem/{id}?_input_charset=utf-8
{"workitemIdentifier":"{id}","propertyKey":"sprint","propertyValue":"{sprintId}","operateType":"COVER"}
```

## 校验

每次 apply 后回读：标题、状态、负责人、验证者、关联、sprint；与 Plan 不一致则停。

**编号硬门禁（强制）**：回读 `serialNumber` 必须等于口令/Plan 编号；回报一行：

```text
ONEOS-xx | 【测试】标题… | 处理中→已完成
```

对不上立刻停。**禁止**用浏览器点列表改状态（历史误关 ONEOS-309 当 343）。

### 闭环【测试】脚本

```bash
python3 scripts/close_test_task.py --sn ONEOS-xx --dry-run
python3 scripts/close_test_task.py --sn ONEOS-xx
```

退出码：`0` 成功；`2` 鉴权；`3` 编号/状态回读失败；`4` 关联缺陷未闭环。
