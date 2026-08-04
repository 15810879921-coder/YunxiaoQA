# 测试执行与发布候选交接

## 状态所有权

```text
开始测试：
【测试】已分配 → 处理中
需求待测试 → 测试中

完成测试：
【测试】处理中 → 已完成
需求测试中 → 测试完成
父【交付】已分配/待处理/处理中 → 已完成
```

任何一侧状态或正式关系不符时零写入。不得用“测试任务已完成”推断需求或父【交付】已自动完成；必须逐项回读真实状态。

## 开始测试

```text
/skill YunxiaoQA
开始测试：测试任务=ONEOS-xx；[需求=ONEOS-yy]
```

执行：

1. 按编号精确读取【测试】，验证`TASK_SUB→【交付】`和`ASSOCIATED→需求`。
2. 口令给需求时必须与正式关系一致；未给时从正式关系唯一反查。
3. 验证【测试】=`已分配`、需求=`待测试`。
4. 先 dry-run，再在同一已确认 Plan 中执行：

```powershell
skill-run transit_test_lifecycle.py start --test-sn ONEOS-xx --req-sn ONEOS-yy --dry-run
skill-run transit_test_lifecycle.py start --test-sn ONEOS-xx --req-sn ONEOS-yy
```

5. 回读两侧编号、标题和状态。任一失败时报告部分状态，不用浏览器补写。

## 测试证据

测试任务描述维护一个机器可解析的`oneos.qa-evidence/v1`幂等区块。证据来源必须是一份由真实测试执行资产导出的JSON清单，不接受聊天中逐项填写的字符串作为完成依据。

```markdown
## 测试执行证据（YunxiaoQA）

{"schemaVersion":"oneos.qa-evidence/v1","sourceVerified":true,"projectId":"...","iterationId":"...","iterationName":"...","requirementId":"...","testTaskId":"...","testPlan":{"id":"...","url":"..."},"caseRun":{"id":"...","url":"...","status":"completed","total":10,"passed":10,"failed":0,"blocked":0,"unexecuted":0},"caseCounts":{"total":10,"passed":10,"failed":0,"blocked":0,"unexecuted":0},"report":{"id":"...","url":"..."},"testDeployment":{"executionId":"...","deployedVersion":"...","evidenceUrl":"..."},"bugSnapshot":[],"bugSnapshotSha256":"...","riskApprovals":{},"manifestSha256":"...","idempotencyKey":"qa-..."}
```

只允许替换该受管区块，保留人工描述。计划、用例集合、执行和报告任一为空不得完成测试。

测试进行中可先独立记录并回读证据，不推进状态：

```powershell
skill-run transit_test_lifecycle.py record `
  --test-sn ONEOS-xx `
  --req-sn ONEOS-yy `
  --evidence-manifest '.\evidence\ONEOS-xx.qa.json' `
  --dry-run
```

去掉`--dry-run`后只写受管证据区块。此时允许非零用例计数和活动缺陷；它们会在`complete`阶段阻塞完成。

## 完成测试

```text
/skill YunxiaoQA
完成测试：测试任务=ONEOS-xx；需求=ONEOS-yy；证据清单=.\evidence\ONEOS-xx.qa.json；暂不修复批准=BUG-ID=批准人|证据
```

脚本入口：

```powershell
skill-run transit_test_lifecycle.py complete `
  --test-sn ONEOS-xx `
  --req-sn ONEOS-yy `
  --evidence-manifest '.\evidence\ONEOS-xx.qa.json' `
  --risk-approval 'ONEOS-901=王冕|APPROVAL-ID-or-URL' `
  --dry-run
```

去掉`--dry-run`前必须满足：

- 【测试】=`处理中`、需求=`测试中`，父【交付】处于已分配/待处理/处理中之一或已完成。
- 测试任务含开发侧写入并回读的`oneos.test-deployment/v1`，环境=`test`且部署成功，版本、项目、迭代、需求和测试任务一致。
- 用例未执行/失败/阻塞均为0。
- 每条已关闭Bug有自己的`oneos.bug-retest/v1`复测通过证据；其他缺陷仅允许有批准证据的`暂不修复`。
- 完成时由脚本从测试任务正式关系实时生成完整`bugSnapshot`及SHA-256；发布侧必须重新读取全部关联Bug并与该快照一致，不能用手填活动Bug数量代替。
- 证据与本项目、迭代、需求、测试任务一致。

完成后回读【测试】=`已完成`、需求=`测试完成`和父【交付】=`已完成`。

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
测试流水线执行ID：
缺陷：已关闭=<IDs>；暂不修复及批准=<ID:证据>
完成时间：
幂等键：
允许的下一动作：组建发布批次
建议下一口令：
/skill yunxiao-release-operations
组建发布批次：迭代=<名称>；需求=<REQ-ID,...>
```

接收方必须重读真实状态与正式关系，不得只相信交接文字。
