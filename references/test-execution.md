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

## 当前完成门禁

常规完成测试只使用以下可核验事实：

1. 【测试】唯一父项为【交付】，且唯一正式`ASSOCIATED`需求正确。
2. 父【交付】已绑定与端别一致的已有迭代；若缺失，先走候选确认补绑流程。
3. 指定TestHub计划可由官方CLI回读，计划内用例总数`>0`，失败、阻塞、未执行均为0。
4. 关联缺陷无`待确认/处理中/已修复/再次打开`；每个已关闭缺陷有独立`oneos.bug-retest/v1`复测通过证据。
5. 每个`暂不修复`缺陷有明确批准人和批准记录ID/URL。

以下三类材料不再是开始或完成测试的必填项，也不得造成阻塞：

- test环境部署成功记录、流水线执行ID和实际版本。
- 正式测试报告ID/链接。
- `oneos.qa-evidence/v1`证据清单、manifest或SHA-256哈希。

已有历史字段可以保留，但不参与当前完成判定。

## 开始测试

```text
/skill YunxiaoQA
开始测试：测试任务=ONEOS-xx；[需求=ONEOS-yy]
```

执行：

1. 按编号精确读取【测试】，验证`TASK_SUB→【交付】`和`ASSOCIATED→需求`。
2. 口令给需求时必须与正式关系一致；未给时从正式关系唯一反查。
3. 验证【测试】=`待处理`、需求=`待测试`。
4. 回读父【交付】迭代；缺失时先按“父交付缺迭代补绑”处理。
5. 先预检，Plan确认后加`--apply`：

```powershell
skill-run yunxiao_cli_test_lifecycle.py start `
  --space-id <项目ID> `
  --test-sn ONEOS-xx `
  --idempotency-key 'qa-start-ONEOS-xx'
```

开始测试不校验test部署记录、执行ID或实际版本。完成后回读两侧编号、标题和状态；任一失败时报告部分状态，不用浏览器补写。

## TestHub执行事实

测试计划和用例执行仍是常规完成测试的正式依据。用例必须先规划进指定计划，再由官方CLI回读结果；不得把用例库中的孤立用例当作计划执行结果。

完成判定直接读取`test-hub-get-test-plan-progress-rate`：

- 用例总数必须大于0。
- `todoCount=0`。
- `failureCount=0`。
- `postponeCount=0`。
- 已通过数等于总数。

不再要求计划概览充当正式测试报告，也不要求报告ID或URL。

## 完成测试

```text
/skill YunxiaoQA
完成测试：测试任务=ONEOS-xx；需求=ONEOS-yy；测试计划=<TestHub计划ID>；[暂不修复批准=BUG-ID=批准人|证据]
```

脚本入口：

```powershell
skill-run yunxiao_cli_test_lifecycle.py complete `
  --space-id <项目ID> `
  --test-sn ONEOS-xx `
  --req-sn ONEOS-yy `
  --test-plan-id <TestHub计划ID> `
  --risk-approval 'ONEOS-901=王冕|APPROVAL-ID-or-URL' `
  --idempotency-key 'qa-ONEOS-xx'
```

先预检，Plan确认后加`--apply`。脚本直接回读TestHub计划进度和全部关联缺陷；不读取或写入部署证据、正式测试报告或QA manifest。门禁通过后依次推进【测试】=`已完成`、需求=`测试完成`并回读。

标准回执包含：项目、父交付及迭代、需求、测试任务、TestHub计划与计数、缺陷状态、风险批准、幂等键和最终状态；不要求部署执行ID、实际版本、报告链接或manifest哈希。

## 人工验证通过快捷闭环

适用：用户针对明确测试任务编号确认人工验证通过，并要求测试任务、需求直接闭环。

前置与边界：

- 【测试】状态属于`待处理/处理中/已完成`，正式关联需求属于`待测试/测试中/测试完成`。
- 唯一父项必须为【交付】，正式`ASSOCIATED`需求必须唯一且与口令一致。
- 关联缺陷不得有`待确认/处理中/已修复/再次打开`；只允许`已关闭/暂不修复`。
- 快捷路径可跳过TestHub，但不生成正式发布候选交接。
- 写入前仍走Plan确认；`--manual-verdict passed`只表示Agent已收到本次明确人工通过确认，不能自行推断。

```powershell
skill-run yunxiao_cli_test_lifecycle.py manual-complete `
  --space-id <项目ID> `
  --test-sn ONEOS-xx `
  --req-sn ONEOS-yy `
  --manual-verdict passed `
  --idempotency-key 'qa-manual-ONEOS-xx-<日期>'
```

脚本按需补齐中间态并逐步回读。最终回执固定包含`evidenceMode=human-confirmed`与`releaseCandidateEligible=false`。

## 父【交付】缺迭代补绑

开始或完成测试（含人工快捷闭环）前回读唯一父【交付】的迭代。若为空，先独立运行`yunxiao_cli_delivery_iteration.py`：预检只给出同端最新已有版本迭代候选；用户确认候选名称和ID后才能加`--confirm-sprint-id <ID> --apply`补绑。补绑成功回读后再执行状态流转。不得创建迭代，也不得跨端猜测。

## 无缺陷回写需求（捷径）

```text
/skill YunxiaoQA
需求测试完成：测试任务=ONEOS-xx；[需求=ONEOS-yy]
```

适用条件：

1. 【测试】已回读为`已完成`，且有明确通过结论。
2. 正式`ASSOCIATED`需求唯一。
3. 无`待确认/处理中/已修复/再次打开`缺陷。
4. 需求当前为`测试中`。

Plan确认后推进需求为`测试完成`并回读。不得仅凭测试任务已完成推断需求状态。

## 发布候选交接

```text
来源Skill：YunxiaoQA
目标Skill：yunxiao-release-operations
项目名称/ID：
迭代名称/ID：
需求编号/状态：<REQ-ID>/测试完成
交付任务：
测试任务/状态：<TEST-ID>/已完成
TestHub计划/计划内用例计数：
缺陷：已关闭=<IDs>；暂不修复及批准=<ID:证据>
完成时间：
幂等键：
允许的下一动作：组建发布批次
```

接收方必须重读真实状态与正式关系，不得只相信交接文字。
