# 测试执行与发布候选交接

## 状态所有权

```text
开始测试：
【测试】待处理 → 处理中
需求待测试 → 测试中

完成测试：
【测试】处理中 → 已完成
需求测试中 → 测试完成
```

任何一侧状态或正式关系不符时零写入。不得用“测试任务已完成”推断需求已自动进入测试完成；必须回读需求真实状态。

## 交付端分流（Web / 小程序）

开始测试前先读【测试】中开发写入的`oneos.test-deployment/v1`，按其`deliveryEnd`分流：

| 交付端 | test 部署证据 | QA 侧要求 |
| --- | --- | --- |
| `Web`（`PC`视为`Web`） | 环境=`test`、终态成功、含执行ID与部署版本 | 原门禁不变 |
| `小程序` | `deliveryEnd=小程序`、`testPipeline=skipped`、`status=skipped`、含`reason` | 跳过test流水线与自动化测试证据；仍要求测试计划、用例执行、报告和逐Bug复测证据 |

小程序端说明：

- 小程序无法执行云效test流水线与自动化测试，缺流水线属预期，不算证据缺失，也不得伪造执行ID、部署版本或流水线URL。
- 小程序的用例执行由测试人员在小程序测试版本上手工完成；`caseRun`计数与TestHub回读门禁不放宽。
- 复测版本用小程序测试版本标识（如体验版版本号），由开发或测试提供；不得留空。
- 只有`deliveryEnd=小程序`可跳过；其他端写`testPipeline=skipped`一律阻塞。

## 开始测试

```text
/skill YunxiaoQA
开始测试：测试任务=ONEOS-xx；[需求=ONEOS-yy]
```

执行：

1. 按编号精确读取【测试】，验证`TASK_SUB→【交付】`和`ASSOCIATED→需求`。
2. 口令给需求时必须与正式关系一致；未给时从正式关系唯一反查。
3. 验证【测试】=`待处理`、需求=`待测试`。
4. 先预检，再在同一已确认 Plan 中加`--apply`执行：

```powershell
skill-run yunxiao_cli_test_lifecycle.py start `
  --space-id <项目ID> `
  --test-sn ONEOS-xx `
  --idempotency-key 'qa-start-ONEOS-xx'
```

`--req-sn`可省略：适配器会从正式`ASSOCIATED`关系唯一反查需求；若显式提供，则必须与正式关系一致。若开发已提供可核验的部署JSON、但任务描述缺少受管`oneos.test-deployment/v1`区块，可在同一预检与已确认Plan中增加`--deployment-evidence <JSON路径>`，先校验并修复区块，再幂等推进状态。

5. 回读两侧编号、标题和状态。任一失败时报告部分状态，不用浏览器补写。

## 测试证据

测试任务描述维护一个机器可解析的`oneos.qa-evidence/v1`幂等区块。证据来源必须是一份由真实测试执行资产导出的JSON清单，不接受聊天中逐项填写的字符串作为完成依据。

```markdown
## 测试执行证据（YunxiaoQA）

{"schemaVersion":"oneos.qa-evidence/v1","sourceVerified":true,"projectId":"...","iterationId":"...","iterationName":"...","requirementId":"...","testTaskId":"...","testPlan":{"id":"...","url":"..."},"caseRun":{"id":"...","url":"...","status":"completed","total":10,"passed":10,"failed":0,"blocked":0,"unexecuted":0},"caseCounts":{"total":10,"passed":10,"failed":0,"blocked":0,"unexecuted":0},"report":{"id":"...","url":"..."},"testDeployment":{"executionId":"...","deployedVersion":"...","evidenceUrl":"..."},"bugSnapshot":[],"bugSnapshotSha256":"...","riskApprovals":{},"manifestSha256":"...","idempotencyKey":"qa-..."}
```

小程序端清单的`testDeployment`改写跳过口径，其余字段不变：

```json
"testDeployment":{"deliveryEnd":"小程序","testPipeline":"skipped","testedVersion":"<小程序测试版本>"}
```

只允许替换该受管区块，保留人工描述。计划、用例集合、执行和报告任一为空不得完成测试。

计划用例执行必须先走[TestHub CLI适配](yunxiao-cli-testhub.md)。不能对尚未规划进计划的用例直接标PASS；适配器必须先规划、由官方CLI回读，再更新结果并回读计划进度。

测试进行中可先独立记录并回读证据，不推进状态：

```powershell
skill-run yunxiao_cli_test_lifecycle.py record `
  --space-id <项目ID> `
  --test-sn ONEOS-xx `
  --req-sn ONEOS-yy `
  --evidence-manifest '.\evidence\ONEOS-xx.qa.json' `
  --idempotency-key 'qa-ONEOS-xx-<版本>'
```

预检成功后加`--apply`只写受管证据区块。此时允许活动缺陷；它们会在`complete`阶段阻塞完成。

## 完成测试

```text
/skill YunxiaoQA
完成测试：测试任务=ONEOS-xx；需求=ONEOS-yy；证据清单=.\evidence\ONEOS-xx.qa.json；暂不修复批准=BUG-ID=批准人|证据
```

脚本入口：

```powershell
skill-run yunxiao_cli_test_lifecycle.py complete `
  --space-id <项目ID> `
  --test-sn ONEOS-xx `
  --req-sn ONEOS-yy `
  --evidence-manifest '.\evidence\ONEOS-xx.qa.json' `
  --risk-approval 'ONEOS-901=王冕|APPROVAL-ID-or-URL' `
  --idempotency-key 'qa-ONEOS-xx-<版本>'
```

预检成功后加`--apply`。脚本必须满足：

- 【测试】=`处理中`、需求=`测试中`。
- 测试任务含开发侧写入并回读的`oneos.test-deployment/v1`；**Web**要求环境=`test`且部署成功，版本、项目、迭代、需求和测试任务一致；**小程序**要求`deliveryEnd=小程序`、`testPipeline=skipped`、`status=skipped`且含`reason`，项目、迭代、需求、测试任务一致。
- 用例未执行/失败/阻塞均为0。
- 每条已关闭Bug有自己的`oneos.bug-retest/v1`复测通过证据；其他缺陷仅允许有批准证据的`暂不修复`。
- 完成时由脚本从测试任务正式关系实时生成完整`bugSnapshot`及SHA-256；发布侧必须重新读取全部关联Bug并与该快照一致，不能用手填活动Bug数量代替。
- 证据与本项目、迭代、需求、测试任务一致。
- TestHub计划概览必须是`/testhub/plan/<计划ID>/dashboard`，作为同一计划的正式汇总报告；脚本同时回读计划计数和目标用例执行ID，禁止只信URL。

完成后回读【测试】=`已完成`和需求=`测试完成`。

## 人工验证通过快捷闭环

适用：用户针对明确测试任务编号确认人工验证通过，并要求测试任务、需求直接闭环；不把该确认伪装成部署、TestHub或QA manifest证据。

前置与边界：

- 【测试】状态属于`待处理/处理中/已完成`，正式关联需求属于`待测试/测试中/测试完成`。
- 唯一父项必须为【交付】，正式`ASSOCIATED`需求必须唯一且与口令一致。
- 关联缺陷不得有`待确认/处理中/已修复/再次打开`；只允许`已关闭/暂不修复`。
- 免除`oneos.test-deployment/v1`、TestHub和`oneos.qa-evidence/v1`，但不生成正式发布候选交接。
- 写入前仍走Plan确认；参数`--manual-verdict passed`只表示Agent已收到本次明确人工通过确认，不能自行推断。

脚本入口：

```powershell
skill-run yunxiao_cli_test_lifecycle.py manual-complete `
  --space-id <项目ID> `
  --test-sn ONEOS-xx `
  --req-sn ONEOS-yy `
  --manual-verdict passed `
  --idempotency-key 'qa-manual-ONEOS-xx-<日期>'
```

先预检，确认后加`--apply`。脚本按需顺序补齐：

1. 【测试】`待处理→处理中`。
2. 需求`待测试→测试中`。
3. 【测试】`处理中→已完成`。
4. 需求`测试中→测试完成`。

每一步均回读编号和状态。最终回执固定包含`evidenceMode=human-confirmed`与`releaseCandidateEligible=false`。

## 无缺陷回写需求（捷径）

```text
/skill YunxiaoQA
需求测试完成：测试任务=ONEOS-xx；[需求=ONEOS-yy]
```

**记住：** 测试任务完成并且验证通过的（无缺陷单），把需求单状态改为测试完成。

执行顺序：

1. 回读【测试】=`已完成`、正式`ASSOCIATED→需求`（口令需求须一致）。
2. 确认验证通过（任务评论测试结论或用户明确确认）。
3. 扫描关联缺陷：无`待确认/处理中/已修复/再次打开`；零缺陷视为满足。
4. 需求当前=`测试中`时，Plan 确认后推进`测试完成`并回读。
5. 回报：`需求编号 | 标题 | 测试中→测试完成`。

不得用「测试任务已完成」 alone 推断需求已测试完成；必须过本门禁后再写。有活跃缺陷时停，走缺陷闭环后再执行。

脚本入口（2026-08-19 补录）：

```powershell
skill-run yunxiao_cli_req_test_complete.py `
  --space-id <项目ID> `
  --test-sn ONEOS-xx `
  --req-sn ONEOS-yy `
  --test-plan-id <计划ID>
```

确认后加 `--apply`。可选 `--test-plan-id` 将 TestHub 计划进度写入回执，便于追溯「计划内已执行用例」。

## 计划内执行用例 + 需求测试完成（常见组合）

适用：测试计划已规划用例；【测试】可能已是「已完成」；需求仍「测试中」；无活跃缺陷。

1. 逐条执行计划内用例（先预检，确认后 `--apply --status PASS`）：

```powershell
skill-run yunxiao_cli_testhub.py `
  --test-plan-id <计划ID> `
  --test-repo-id <用例库ID> `
  --testcase-id <用例内部ID> `
  --executor-id <执行人userId> `
  --status PASS `
  --apply
```

2. 回读计划进度：`test-hub-get-test-plan-progress-rate` 须 `todoCount=0` 且已执行=总数>0；满足后将 **测试计划** 状态改为「已完成」（`DONE`）并回读（见 [yunxiao-cli-testhub.md](yunxiao-cli-testhub.md) 状态机）。用例结果是否全 PASS 与计划 DONE 解耦：有 FAILURE/POSTPONE 只要已执行完仍可 DONE，缺陷另走缺陷条线。

3. 需求回写（本场景用「需求测试完成」，非完整「完成测试」）：

```powershell
skill-run yunxiao_cli_req_test_complete.py `
  --space-id <项目ID> `
  --test-sn ONEOS-xx `
  --req-sn ONEOS-yy `
  --test-plan-id <计划ID> `
  --apply
```

完整「完成测试」仍须 `oneos.test-deployment/v1` + `oneos.qa-evidence/v1` 证据清单；缺部署区块时不得硬走 complete。

## 发布候选交接

```text
来源Skill：YunxiaoQA
目标Skill：yunxiao-release-operations
项目名称/ID：
迭代名称/ID：
需求编号/状态：<REQ-ID>/测试完成
交付任务：
测试任务/状态：<TEST-ID>/已完成
测试计划/用例/执行/报告：
交付端：Web|小程序
测试流水线执行ID：（小程序写 skipped）
缺陷：已关闭=<IDs>；暂不修复及批准=<ID:证据>
完成时间：
幂等键：
允许的下一动作：组建发布批次
建议下一口令：
/skill yunxiao-release-operations
组建发布批次：迭代=<名称>；需求=<REQ-ID,...>
```

接收方必须重读真实状态与正式关系，不得只相信交接文字。
