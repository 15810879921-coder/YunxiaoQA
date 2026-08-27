# 实写 API（测试任务）

与 YunxiaoPM 共用 Projex 会话；**禁止**把凭证写入 Skill 或缺陷描述。

本文件自包含测试侧 Projex 调用约定。常量只以本 Skill [assets/runtime-ids.json](../assets/runtime-ids.json) 为准（2026-07-27 在 `01_ONEOS` 实网验证）；缺项按交接编号实时查询云效，禁止读取其他 Skill 的安装目录。

**鉴权提示：** 本机 Chrome `browser_cookie3` 可能 `invalid session`；已登录的 Cursor/浏览器页内 `fetch(..., {credentials:'include'})` 可用。优先复用有效会话。

刷新流程（本机）：

```bash
# Chrome 已登录 devops.aliyun.com
skill-run refresh_cookies.py --probe   # 写入当前系统临时目录并探测
skill-run check_auth.py                # 仅探测；失败会打印 AUTH_HELP
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
| （任务）→ 已完成 | 仅`完成测试`，并通过部署、QA证据清单和逐Bug复测门禁 |

**禁止**测试侧：`→已修复` / `→暂不修复` / `→处理中`（开发 Skill）。

## 写 · 建缺陷

优先用脚本（含强制关联校验）：

```bash
skill-run create_bug.py --mode 本期 --source standalone --title '…' --test-task DEMO-xx `
  --assignee 沈辰 --description-html '<p>…</p>'

skill-run create_bug.py --mode 本期 --source test-case --test-case CASE-1001 `
  --title '…' --test-task DEMO-xx --assignee 沈辰 --description-html '<p>…</p>'
```

机器已配置个人访问令牌时，非本期独立缺陷可走官方 OpenAPI：

```powershell
skill-run create_bug_openapi.py --title '【模块】问题' --assignee 张三 `
  --verifier 当前测试用户 --label 小程序-模块 --priority 中 --severity 3-一般 `
  --description-file C:\evidence\bug.html --file C:\evidence\shot.png --dry-run
```

该路径读取机器/进程环境变量，不落盘 Token；apply 前做精确标题查重，apply 后回读
创建人=验证者、负责人、标签、优先级、严重程度和附件名称+大小。

```http
POST|PUT /projex/api/workitem/workitem?_input_charset=utf-8
```

- `workitemType` / `workitemTypeIdentifier` = `37da3a07df4d08aef2e3b393`
- `category` = `Bug`
- 负责人：`assignedTo`
- 验证者：`workitem.verifier`（user id）。请求不接受验证者覆盖；创建后从云效新建记录取得当前会话用户，必要时用工作项字段`COVER`写入并从`/extra`回读。
- 优先级 / 严重程度：见 runtime-ids `fields.priority` / `seriousLevel`
- 描述：`PATCH …/workitem/{id}/document`，`{"content":"<html>","formatType":"RICHTEXT"}`
- **本期关联**：
  1. `createWorkitemRelationInfo` = `ASSOCIATED` →【测试】；回读 ASSOCIATED（**勿用 TASK_SUB/父子**）；失败 → 退出码 3
  2. 产品需求：写入描述「追溯需求」段；**不做**事后 `ASSOCIATED→需求`（Cookie 第二挂常报「不能关联相同的工作项」；已去掉告警+伪备注口径）

新建默认状态一般为 **待确认**。

## 写 · 关联 / 迭代

关联：`POST /projex/api/workitem/workitem/{id}/relation/record`（`ASSOCIATED` 等，与 YunxiaoPM 一致）。

**注意：** 缺陷对【测试】的 ASSOCIATED **必须在 create 时挂上**；事后 `relation/record` 在 DEMO/ONEOS 常报「不能关联相同的工作项」，不可作为主路径。需求 API 第二挂本期不做（UI/OpenAPI `pt-` 令牌另议）。

挂迭代：

```http
PATCH /projex/api/workitem/workitem/{id}?_input_charset=utf-8
{"workitemIdentifier":"{id}","propertyKey":"sprint","propertyValue":"{sprintId}","operateType":"COVER"}
```

## 校验

每次 apply 后回读：标题、状态、负责人、验证者、关联、sprint；其中验证者必须等于云效记录的当前创建会话用户，与 Plan 不一致则停。

**编号硬门禁（强制）**：回读 `serialNumber` 必须等于口令/Plan 编号；回报一行：

```text
ONEOS-xx | 【测试】标题… | 处理中→已完成
```

对不上立刻停。**禁止**用浏览器点列表改状态（历史误关 ONEOS-309 当 343）。

### 已停用的旧闭环脚本

```bash
skill-run close_test_task.py --sn ONEOS-xx --dry-run
```

该脚本固定返回退出码`4`且不写状态。唯一完整入口是：

```powershell
skill-run yunxiao_cli_test_lifecycle.py complete --space-id <项目ID> --test-sn ONEOS-xx --req-sn ONEOS-yy `
  --evidence-manifest C:\evidence\ONEOS-xx.json --idempotency-key qa-ONEOS-xx-v1
```
