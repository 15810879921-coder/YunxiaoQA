---
name: YunxiaoQA
description: >-
  测试人员云效（Projex）自动化：接收并开始【测试】任务，推进需求待测试→测试中，
  执行复测、判断预期或提交缺陷前重新读取最新原型PRD，并在提交前再次确认需求未变化，
  每日监测01_ONEOS新交付任务并为标题同时含【交付】【新增】且已选迭代的交付任务自动创建测试计划，
  扫描全部可见用例库，匹配后通知确认再规划用例；
  测试闭环按任务标题分流：【新增】回读TestHub计划与完整缺陷证据，【优化】回读测试通过评论且确认无活动缺陷；
  诊断查重后一键发起缺陷；
  独立建缺陷和测试用例建缺陷均强制将验证者设置为当前登录测试用户并回读，
  （本期交付绑定开发负责人 / 非本期自指定负责人），拉取已修复|暂不修复待验清单，
  仅在每个Bug具有独立复测通过证据后批量关闭已修复、再次打开复现缺陷、已关闭并入当期迭代；缺陷闭环且暂不修复均有批准证据后，
  将【测试】标已完成、需求推进测试完成；仅【新增】完整门禁通过时输出正式发布候选交接；
  闭环发现父【交付】缺迭代时，
  主动推荐同端最新已有迭代，用户确认后补绑并回读，但不冒充完整发布证据。
  用户说 YunxiaoQA、测试任务、拉取测试任务、发起缺陷、再次打开、批量关闭、并入迭代、
  开始测试、记录测试证据、完成测试、闭环测试任务、需求测试完成、监测新增交付任务、自动建测试计划、
  接收发布回流、验证发布回流、交接发布 时使用。
  仅测试角色；不建【开发】/不创建迭代/不代开发改已修复。
  凡写云效先 Plan 确认再一口气 apply；禁止对齐 yunxiao-requirement-lifecycle。
---

# 测试任务（YunxiaoQA）

> **客户端**：同一业务规则支持 Codex 与 Cursor；安装器负责选择客户端目录，生命周期交接不得依赖安装路径。

测试人员云效自动化。正式 Skill 名 **`YunxiaoQA`**，选择器 **`/skill YunxiaoQA`**；对外中文名 **测试任务**。本 Skill **自洽成篇**；**禁止** fork / include / 「对齐」`yunxiao-requirement-lifecycle`。

与 **YunxiaoPM（需求任务）**、开发交付 Skill 分工：本 Skill **只做测试侧**读写。

闭环版本：`2.7.6`。

## 最新原型 PRD 门禁（强制）

凡执行测试、复测、判断预期结果、创建缺陷、追加失败评论、再次打开或关闭缺陷，均先按
[references/prototype-prd-gate.md](references/prototype-prd-gate.md) 重新读取当前可用的最新原型 PRD/标注。
若测试执行到云效提交之间经过等待、刷新、切换账号或需求可能更新，提交前必须再次读取并比较；
发现预期变化时，立即按新口径重判并补测受影响路径，禁止沿用旧缺陷描述、旧评论或旧测试用例中的过期预期。

## Plan 模式门禁（强制 · 凡写云效）

凡会改云效的操作（建缺陷、改状态、闭环任务、挂迭代、改负责人/验证者等），Agent **第一步**必须：

1. `SwitchMode` → **plan**（说明：先对齐参数与执行清单，确认后再一口气 apply）。
2. **切换项目**时：口令带 `项目=` 或 Plan 点选；有 YunxiaoPM 时可复用其 PJ。禁止静默用错误 `spaceIdentifier`；确认后写入 `assets/runtime-ids.json` → `project.last_selected`。
3. Plan 写清：项目名 + spaceId、口令类型、涉及编号、目标状态、负责人/验证者、关联对象、**不会做的事**。
4. **用户确认 / 「执行」之前**：禁止 apply。
5. 确认后切回 Agent，**同一轮按清单一口气执行到底**，再一次性校验回报。

**例外（可读可不进 Plan）：** 仅 `拉取测试任务` / `拉取待验缺陷` 且不改状态。

**禁止：** 以「参数已齐」「速度路径」跳过 Plan。

细则见 [references/plan-gate.md](references/plan-gate.md)。

## 真相源模型

```text
【测试】= 交付子项（TASK_SUB→【交付】）；由开发 Skill 在提测时创建（本 Skill 不建）
缺陷     = Bug；**必须** ASSOCIATED→【测试】（关联项，非父子）；产品需求写入描述追溯（本期不做需求 ASSOCIATED API）
验证者   = workitem.verifier；所有测试侧建单路径均=当前登录测试用户，禁止口令覆盖
本期负责人=同交付【开发】负责人
缺陷打开态 = 待确认（禁止再用「待处理」指缺陷）
查重/复用 = 优先编号；禁止只按模糊标题瞎改他人单
测试可改状态 = 已修复→已关闭 | 已修复→再次打开 |（闭环）【测试】→已完成
测试阶段状态 = 【测试】待处理→处理中→已完成；需求待测试→测试中→测试完成
闭环分流     = 标题含【新增】走完整证据；否则标题含【优化】走通过评论+无活动缺陷；两者同现时【新增】优先；均无则拒绝自动闭环
优化快捷闭环 = 必须从测试任务评论区回读最新明确“测试/验证/复测通过”结论，且活动缺陷为0；跳过TestHub；不产出发布候选
测试不改     = 待确认/再次打开/处理中 → 已修复|暂不修复|处理中（开发侧）
【测试】任务打开态 = 待处理 / 处理中（任务状态名，与缺陷待确认不同）
产品不建迭代 = 本 Skill 只把已关闭缺陷挂到已有当期迭代；迭代按端分列，缺陷只并入与来源【交付】端侧标签一致的迭代
交付缺迭代 = 精确回读测试任务唯一父【交付】；若未绑定，按Web/小程序端筛选未归档、未锁定的已有版本迭代并按版本号取最新候选；先发用户确认，确认后补绑并回读；不创建迭代
交付端       = 【交付】端侧标签 Web / 小程序（PC 视为 Web）；用于迭代端别匹配，不再要求test流水线部署证据
发布候选真相 = 仅【新增】：完成态【测试】+ TestHub计划全量通过 + 测试完成需求 + 正式关系 + 完整缺陷证据
新增交付建计划 = 每日一次；01_ONEOS；Task标题同时精确包含【交付】【新增】；同交付任务迭代；谢佳伟=管理员+参与人；当天至+14天；用例匹配后先通知确认
测试计划状态 = 新建成功后→进行中（DOING）；计划内全部用例已执行（待测=0 且已执行=总数>0）后→已完成（DONE）；细则见 yunxiao-cli-testhub.md
常量       = assets/runtime-ids.json（2026-07-27 01_ONEOS 已实网补齐）
```

## 外置调用（禁止本 Skill 内嵌对方全文）

| 时机 | 调用 |
|---|---|
| 人员 / 项目 catalog / 通用状态 | 只读本 Skill [assets/runtime-ids.json](assets/runtime-ids.json)；缺项按交接编号实时查询云效 |
| PJ 云效项目点选 | 按 Plan/口令实时查询云效项目并将选中结果写回本 Skill 运行时配置 |
| 缺陷描述模板 / 定位矩阵 | 本 Skill [references/bug-template.md](references/bug-template.md) · [references/diagnosis.md](references/diagnosis.md) |
| 挂载点选【测试】/需求 | [references/anchor-selection.md](references/anchor-selection.md) · `scripts/list_bug_anchors.py` |
| 实写 API | [references/live-api.md](references/live-api.md)（01_ONEOS 已验证） |
| 测试执行闭环 | [references/test-execution.md](references/test-execution.md) · `scripts/yunxiao_cli_test_lifecycle.py` · `scripts/yunxiao_cli_bug_retest.py` · `scripts/yunxiao_cli_req_test_complete.py` |
| 最新原型PRD重读与预期重判 | [references/prototype-prd-gate.md](references/prototype-prd-gate.md) · 可用时调用正式 Skill `axhub-prototype-context` |
| 父交付缺迭代补绑 | [references/test-execution.md](references/test-execution.md) · `scripts/yunxiao_cli_delivery_iteration.py` |
| TestHub计划/用例执行 | [references/yunxiao-cli-testhub.md](references/yunxiao-cli-testhub.md) · `scripts/yunxiao_cli_testhub.py` |
| 新交付任务监测/自动建测试计划 | [references/requirement-testplan-monitor.md](references/requirement-testplan-monitor.md) · `scripts/yunxiao_delivery_plan_monitor.py` |
| 列表/建缺/流转脚本 | [scripts/README.md](scripts/README.md) · `check_auth.py` / `list_bug_anchors.py` / `list_test_tasks.py` / `list_bugs.py` / `create_bug.py` / `transit_bug.py` / `close_test_task.py` |
| 跨平台脚本启动 | [references/runtime-launcher.md](references/runtime-launcher.md) · `skill-run <script.py> [参数...]` |

日常测试**优先本 Skill**；不必再挂载英文 `yunxiao-bug-triage`（诊断要点已收入本 Skill）。

## 跨 Skill 逻辑交接（强制）

- 只接收/输出正式 Skill 名、需求/交付/开发/测试/发版任务编号、当前状态、正式 `ASSOCIATED`/`TASK_SUB` 关系，以及测试计划、用例、缺陷和幂等证据标识。
- 禁止定位、读取、复制或要求用户提供其他 Skill 的安装目录。本 Skill 只读取自身包内资源；缺少人员、项目或状态信息时按交接编号实时查询云效。
- 上游开发正式名为 `yunxiao-development-delivery`，下游发布正式名为 `yunxiao-release-operations`，产品回退正式名为 `YunxiaoPM`；选择器必须使用 `/skill <正式名称>`。

## 写操作铁律（防编号误判 · 强制）

历史事故：浏览器点状态菜单把 **ONEOS-343** 错关成 **ONEOS-309**。故：

1. **禁止**用 `cursor-ide-browser` / DOM 点击 /「可交互节点」改云效状态、负责人、关联、迭代。
2. **唯一常规写路径**：本 Skill `scripts/*.py`。TestHub 测试计划可由官方 OpenAPI 创建，用例与结果优先走官方阿里云 CLI/OpenAPI；当前官方能力仍缺少“规划已有用例”写接口，须先通知匹配结果并获得“指定测试计划+指定既有用例”的逐批确认。确认后仅允许在隔离测试计划页面补齐该单一动作；随后必须立即回到CLI回读计划内用例并更新结果。该例外禁止改工作项状态、禁止猜测接口、禁止扩展到其他计划。
3. **编号硬门禁**：口令 `ONEOS-xx` → 脚本 `--sn` → `serialNumber ==` 精确匹配 → apply → **回读** `serialNumber|subject|from→to`；任一不对立刻停。
4. **开始/完成测试**：只用 `skill-run yunxiao_cli_test_lifecycle.py start|complete|manual-complete ...`；脚本必须先按标题分类。`【新增】`走`complete --test-plan-id`完整门禁；`【优化】`走`complete`或兼容`manual-complete`，必须通过官方CLI回读测试任务最新评论为通过且活动缺陷为0。标题同时含两者时按【新增】，均不含时拒绝闭环。逐Bug复测关闭只用 `skill-run yunxiao_cli_bug_retest.py ...`。`skill-run` 按 [references/runtime-launcher.md](references/runtime-launcher.md) 解析。
5. **旧闭环入口**：`close_test_task.py`已停用并固定拒绝写入；`transit_test_lifecycle.py`保留为旧Cookie兼容实现但禁止用于新执行；`闭环测试任务`兼容口令必须转入`yunxiao_cli_test_lifecycle.py complete`完整门禁。
6. Projex与TestHub新闭环只许PAT/组织ID/官方CLI。旧Cookie脚本只可用于历史诊断，**禁止**改走浏览器点选「凑合关单」。

## 路由（按需完整阅读）

| 场景 | 模块 |
|---|---|
| 口令面 | [references/commands.md](references/commands.md) |
| 测试环境切账号 / 多角色 UI 验收 | [references/test-env-account-switch.md](references/test-env-account-switch.md) |
| 开始测试 / 证据 / 完成测试 / 发布交接 | [references/test-execution.md](references/test-execution.md) |
| 条线 1/2 · 状态机 · 再次打开 | [references/defect-flow.md](references/defect-flow.md) |
| 诊断 · 查重 · 分层初判 | [references/diagnosis.md](references/diagnosis.md) |
| 缺陷描述模板 | [references/bug-template.md](references/bug-template.md) |
| Plan 确认清单 | [references/plan-gate.md](references/plan-gate.md) |
| 挂载点选 | [references/anchor-selection.md](references/anchor-selection.md) |
| 实写 API | [references/live-api.md](references/live-api.md) |
| 跨平台脚本启动器 | [references/runtime-launcher.md](references/runtime-launcher.md) |
| 每日监测交付任务并建测试计划 | [references/requirement-testplan-monitor.md](references/requirement-testplan-monitor.md) |

## 口令速查

```text
拉取测试任务：状态=待处理|处理中；[项目=…]
监测新增交付任务建计划：项目=01_ONEOS；任务标记=【交付】+【新增】；频率=每日一次；管理员=谢佳伟；参与人=谢佳伟；用例库=全部可见；用例添加=匹配后通知确认
开始测试：测试任务=ONEOS-xx；[需求=ONEOS-yy]
发起缺陷：标题=…；描述=…；测试任务=ONEOS-xx；[需求=ONEOS-yy]；[负责人=…]；[证据=…]
从测试用例发起缺陷：测试用例=CASE-xx；标题=…；描述=…；测试任务=ONEOS-xx；[需求=ONEOS-yy]；[负责人=…]；[证据=…]
发起缺陷(非本期)：标题=…；描述=…；负责人=…；[测试任务=…]；[项目=…]
# 无测试任务的非本期须显式声明，默认仍要求挂测试子项+需求
拉取待验缺陷：状态=已修复|暂不修复；[测试任务=…]；[负责人=…]
批量关闭已修复：缺陷=ONEOS-a；复测用例=CASE-ID；复测执行=RUN-ID；test版本=VERSION；证据=ID或URL；验证人=当前用户
再次打开：缺陷=ONEOS-xx；[原因=复现说明]；[证据=…]
并入当期迭代：缺陷=… 或 范围=已关闭且未挂迭代；迭代=（当期/指定名）
完成测试：测试任务=ONEOS-xx；[需求=ONEOS-yy]；[测试计划=<【新增】必填TestHub计划ID>]；[暂不修复批准=BUG-ID=批准人|证据]
优化测试通过并完成：测试任务=ONEOS-xx；[需求=ONEOS-yy]（评论区须已有最新明确通过结论）
补绑交付迭代：测试任务=ONEOS-xx；候选=同端最新已有迭代（先确认后apply）
需求测试完成：测试任务=ONEOS-xx；[需求=ONEOS-yy]
# 【测试】已完成 + 验证通过 + 无缺陷单 → 需求测试中→测试完成（见「无缺陷回写需求」）
接收发布回流：发版任务=TASK-900；触发=发布失败|产品验收失败；证据=ID或URL
验证发布回流：发版任务=TASK-900；缺陷=ONEOS-a,ONEOS-b；回归证据清单=<JSON文件>
闭环测试任务：测试任务=ONEOS-xx（兼容旧口令；按“完成测试”门禁执行）
```

**编号优先**：口令显式 `ONEOS-xx` > 当前上下文 > 询问；**禁止按标题猜编号后静默写云效**。

## 【优化】评论通过快捷闭环

标题只含`【优化】`的测试任务可走轻量闭环；`complete`会自动选择该路径，`manual-complete`仅作兼容入口：

1. 写操作仍须 Plan；`manual-complete`兼容入口的执行参数必须含`--manual-verdict passed`。
2. 精确回读【测试】、唯一父【交付】和唯一正式`ASSOCIATED`需求；任务源状态仅允许`待处理/处理中/已完成`，需求仅允许`待测试/测试中/测试完成`。
3. 通过官方CLI读取测试任务评论；按时间取最新明确结论，必须命中“测试/验证/复测通过”，若最新为不通过/失败/阻塞或评论冲突且无法排序则停止。
4. 关联缺陷不得存在`待确认/处理中/已修复/再次打开`；已关闭或暂不修复不算活动缺陷。
5. 该路径不要求TestHub或已关闭Bug复测清单，但必须按状态机补齐中间态并逐步回读：任务最终=`已完成`、需求最终=`测试完成`。
6. 输出回执标记`evidenceMode=optimization-pass-comment-and-active-defect-gate`及`releaseCandidateEligible=false`；不得声称为完整发布候选证据。
7. 兼容入口：`skill-run yunxiao_cli_test_lifecycle.py manual-complete --space-id <项目ID> --test-sn ONEOS-xx [--req-sn ONEOS-yy] --manual-verdict passed --idempotency-key <键>`；【新增】禁止使用。

## 父【交付】缺迭代补绑

开始、记录或完成测试（含【优化】兼容闭环）时，必须回读测试任务唯一父【交付】的`sprint`：

1. 已绑定：幂等回读，不改原迭代。
2. 未绑定：从同项目已有迭代中按父交付端别筛选；Web/PC只匹配`web端`/`PC端`，小程序只匹配`小程序端`；排除`ARCHIVED`、已锁定和无版本号的迭代，按`Vx.y.z`数值取最新候选（例如`OneOS_web端V1.4.9`）。
3. 端别不能从标签/标题唯一判定、候选不存在或并列不能稳定判定时停止并报告，不猜测、不创建迭代。
4. 先运行`yunxiao_cli_delivery_iteration.py`预检，将父交付编号、当前迭代、候选名称+ID+状态、不会创建迭代发给用户确认；**确认前禁止apply**。
5. 确认后将候选ID原样传给`--confirm-sprint-id`并加`--apply`；脚本精确回读父交付编号和`sprint.id`，再报告绑定结果。不得只说“已请求”。

```powershell
skill-run yunxiao_cli_delivery_iteration.py `
  --space-id <项目ID> `
  --test-sn ONEOS-xx

# 用户确认候选后
skill-run yunxiao_cli_delivery_iteration.py `
  --space-id <项目ID> `
  --test-sn ONEOS-xx `
  --confirm-sprint-id <已确认候选ID> `
  --apply
```

## 无缺陷回写需求（强制记住 · 2026-08-19）

**规则原文口径：** 测试任务完成并且验证通过的（无缺陷单），把需求单状态改为测试完成。

适用与门禁：

1. 【测试】回读=`已完成`（编号硬门禁）。
2. 验证结论为通过（任务评论或用户确认的测试结论；禁止无结论臆推）。
3. 关联该【测试】的缺陷中，无`待确认/处理中/已修复/再次打开`；允许零缺陷，或仅有`已关闭`/`暂不修复`（暂不修复须另有批准证据，否则停）。
4. 正式`ASSOCIATED`唯一反查需求（或口令`需求=`与关系一致）；需求当前=`测试中`。
5. Plan 确认后推进需求`测试中→测试完成`并回读；回报一行：`serialNumber | subject | 测试中→测试完成`。
6. **禁止**浏览器点状态；**禁止**在仍有活跃缺陷时改需求；回写前仍按标题分流校验：【新增】须提供并回读完整TestHub/缺陷证据，【优化】须回读通过评论。

用户说「评论结果并改状态」「测试通过无缺陷改需求」时：先保证【测试】已完成且评论结论，再按本规则改需求。

## 发起缺陷流水线（强制 · 方案 B）

每次 `发起缺陷` / `从测试用例发起缺陷` / `发起缺陷(非本期)`：

0. **重读最新原型PRD**：按 [prototype-prd-gate.md](references/prototype-prd-gate.md) 确认当前预期；提交前再次检查需求是否变化。来源不可读或口径冲突时停止写入，不猜预期。
1. **规范化证据**（环境、路径、角色、时间、步骤、实际/期望、截图；无秘密）
2. **查重**（活跃 + 近期关闭；同因则更新旧单并回报，不问则新建）
3. **分层初判**（前端/后端/数据/配置/环境；标「推断」）
4. **填模板** → 见 [bug-template.md](references/bug-template.md)
5. **字段**：验证者=当前登录测试用户，禁止口令覆盖；本期负责人=同交付【开发】负责人（多人 Plan 点选）；非本期负责人=口令必填
   - 独立创建：`create_bug.py --source standalone`
   - 测试用例创建：`create_bug.py --source test-case --test-case <用例编号/执行记录>`
   - 两条路径必须进入同一个建单处理器。apply 后以云效在新建 Bug 上记录的当前会话用户为真相，写入`workitem.verifier`并回读；不以固定姓名、负责人、开发人、测试主管或口令参数代替。
5b. **挂载点选**：口令未给出唯一 `测试任务=` 时，先跑 `list_bug_anchors.py`，用 **AskQuestion** 点选【测试】；需求可点选/追溯，写入描述作追溯（非关联项）。未点选【测试】禁止 create。详见 [anchor-selection.md](references/anchor-selection.md)。
6. **关联**：
   - **硬门禁**：缺陷 **create 时**挂 `ASSOCIATED→【测试】`（关联项；**禁止** TASK_SUB/父子）；回读 ASSOCIATED 校验，失败退出码 3。
   - **需求**：点选/追溯后写入描述「追溯需求」段；**不做** Cookie 事后 `ASSOCIATED→需求`（不告警、不伪造成功）。口令 `需求=` / `--req` 可覆盖。
7. Plan 回显 → 确认 → apply（`create_bug.py`）→ 回读当前用户=验证者及【测试】关联 → 回报；任一校验失败须停

## 测试完成标题分流门禁

所有完成路径先满足：

1. 【测试】=`处理中`且正式`TASK_SUB→【交付】`、`ASSOCIATED→需求`。
2. 需求=`测试中`。
3. 唯一父【交付】已绑定正确端别的已有迭代；缺失时按“父【交付】缺迭代补绑”先确认后处理。

随后按标题选择唯一通道：

- `【新增】`（即使同时含`【优化】`也按此通道）：直接通过官方CLI回读指定TestHub计划，计划内用例总数`>0`且未执行/失败/阻塞均为0；无活动缺陷；每条已关闭Bug有独立复测通过证据；每条`暂不修复`有批准人和证据。通过后可输出发布候选交接。
- `【优化】`：通过官方CLI回读测试任务评论区，最新明确测试结论为通过，且无`待确认/处理中/已修复/再次打开`活动缺陷；不要求TestHub、已关闭Bug复测证据或暂不修复批准证据；完成回执标记不可作为发布候选。
- 两类标记均无：拒绝自动闭环并报告标题分类缺失，不猜测通道。

门禁通过后依次推进【测试】→`已完成`、需求→`测试完成`并逐项回读。

常规完成测试**明确不要求**：`oneos.test-deployment/v1`及其执行ID/实际版本、正式测试报告ID/链接、`oneos.qa-evidence/v1`证据清单及任何manifest/SHA-256哈希。上述字段存在时可保留为历史资料，但不得作为开始或完成测试的阻断条件。

## 本 Skill 终点与明确不做

- **终点**：完成测试执行与缺陷闭环，推进需求到测试完成，并输出可机器校验的发布候选交接。
- **明确不做：** 创建【开发】/【测试】任务、代开发标「已修复/暂不修复」、创建迭代、改产品/开发阶段状态、挂仓库/开分支/提 MR。仅允许在用户确认后，为缺失迭代的父【交付】补绑已存在的同端最新版本迭代。
- 本 Skill明确拥有且只拥有需求测试阶段`待测试→测试中→测试完成`。

缺陷回流交接：「开发侧请用开发 Skill 拉待确认/再次打开缺陷并标已修复|暂不修复。」
测试完成交接：「发布侧请用`/skill yunxiao-release-operations`组建发布批次。」

发布或产品验收失败后的正式回流按[release-repair-loop.md](references/release-repair-loop.md)执行；不得直接重跑生产或直接再次验收。

## 验收清单（回报自检）

- [ ] 测试/复测与云效提交前均已重读最新原型PRD；若版本或口径变化，已按新预期重判并补测，证据含来源定位与读取时间
- [ ] 拉【测试】：仅待处理/处理中（或口令指定）
- [ ] 开始测试：【测试】待处理→处理中；需求待测试→测试中；两侧均回读
- [ ] 发起缺陷（独立/测试用例）：验证者=当前登录用户且已回读；负责人/关联正确；走过查重+模板
- [ ] 再次打开：仅自「已修复」且有复现说明；负责人未误改
- [ ] 批量关闭：逐Bug复测证据已写入并回读；仅「已修复」→「已关闭」
- [ ] 并入迭代：仅「已关闭」；迭代已存在（未新建）
- [ ] 标题分流：含【新增】走完整证据；仅含【优化】走通过评论+无活动缺陷；两者同现按【新增】；均无已停止
- [ ] 【新增】完成：TestHub计划非空且全部通过；已关闭Bug复测证据和暂不修复批准齐全；未要求部署记录、正式报告或QA manifest/哈希
- [ ] 【优化】完成：最新评论明确通过；无活动缺陷；未要求TestHub；任务与需求均完成并回读；回执明确不可作为发布候选
- [ ] 父交付迭代：已回读；若缺失，已按同端最新已有版本给出候选并经用户确认后补绑；编号和`sprint.id`写后回读；未创建迭代
- [ ] 无缺陷回写需求：【测试】已完成 + 验证通过 + 无活跃缺陷 → 需求测试中→测试完成并回读
- [ ] 状态闭环：【测试】处理中→已完成；需求测试中→测试完成；两侧均回读
- [ ] 发布交接：项目/迭代/需求/交付/TestHub计划/缺陷状态/幂等键完整
- [ ] 新增交付任务监测：每日一次；仅Task标题同时含【交付】【新增】；项目/人员/交付迭代均实时回读；计划当天至+14天；按交付任务ID幂等；匹配用例未自动添加
- [ ] 测试计划状态：新建后回读「进行中」(DOING)；全部用例已执行（待测=0）后回读「已完成」(DONE)；零用例不得 DONE
- [ ] 每次写操作回报含一行：`serialNumber | subject | from→to`（与口令编号一致）
- [ ] 本轮无浏览器改状态；无建【开发】、无创建迭代、无代开发改状态
