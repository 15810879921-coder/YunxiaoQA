# TestHub CLI 适配

## 适用范围

测试计划可使用官方 OpenAPI `CreateTestPlan` 创建；用例搜索可使用
`ListTestRepo` + `SearchTestCases`；用例执行结果优先使用官方阿里云 CLI
`devops` 插件。当前 CLI `3.4.11` / devops插件 `0.5.2` 与公开 OpenAPI
仍未暴露“把已有用例规划进测试计划”的写接口。本 Skill 必须先如实返回
`CLI_CAPABILITY_GAP`并停止用例规划写入。

只有用户在Plan中明确确认“指定测试计划+指定既有用例”的一次性页面补齐，才允许在隔离测试计划里执行该单一动作。补齐后立即回到本适配器：官方CLI必须回读到同一用例，才可更新结果。该例外禁止Cookie、禁止猜测接口、禁止改工作项状态或操作其他计划。

环境变量：

- `ALIBABA_CLOUD_YUNXIAO_ACCESS_TOKEN`
- `ALIBABA_CLOUD_YUNXIAO_ORGANIZATION_ID`
- 可选 `ALIYUN_CLI_PATH`
- Region版可选 `ALIBABA_CLOUD_YUNXIAO_ENDPOINT`；中心版默认
  `https://openapi-rdc.aliyuncs.com`

每日需求建计划与全可见用例库匹配见
[requirement-testplan-monitor.md](requirement-testplan-monitor.md)。该流程可自动创建计划，
但只通知匹配用例；收到明确的计划ID+用例ID确认前不规划用例。

## 测试计划状态机（强制 · 2026-08-26 本尊口径）

云效 TestHub 计划状态中文名与 API 枚举对应：

| 中文 | API |
|---|---|
| 未开始 | `TODO` |
| 进行中 | `DOING` |
| 已完成 | `DONE` |

硬规则：

1. **新建后开测**：`CreateTestPlan`（或任何路径新建计划）成功并回读到计划 ID 后，**同一已确认 Plan apply 清单内**立即将计划状态改为「进行中」（`DOING`）；再按 `planId | 名称 | status` 精确回读，未回读成功不得声称已开测。
2. **全部用例执行完成后收口**：仅当计划内用例总数 `>0`、待测试（`TODO`）=`0`、已执行数=`总数` 时，将计划状态改为「已完成」（`DONE`）。`PASS` / `FAILURE` / `POSTPONE` 均计为已执行；**通过率不是**计划是否完成的判定条件。
3. **禁止误判**：不得仅凭计划日期到期、通过率 100%、截图观感、或「【测试】任务已完成」把计划标为「已完成」；必须回读计划进度统计。**零用例计划禁止自动 DONE**。
4. **状态校正**：若全部用例已执行但计划仍为「未开始/进行中」，经写操作 Plan 确认后仅校正计划状态为「已完成」，不得改用例结果、人员、日期、迭代或关联。
5. **完成回读**：写入后再次精确读取同一计划，回报一行：`planId | 计划名称 | from→to | 已执行/总数 | 待测试数`；任一不一致立即停。
6. **写路径**：优先官方 OpenAPI/CLI 更新计划状态；禁止浏览器 DOM 点选凑合。若公开接口暂无改计划状态能力，如实报告能力缺口，不得伪造成功。

与【测试】任务状态机分离：本条只管 **TestHub 测试计划**；【测试】工作项仍走 `yunxiao_cli_test_lifecycle.py`。

## 规划并执行单条用例

先预检：

```powershell
skill-run yunxiao_cli_testhub.py `
  --test-plan-id <计划ID> `
  --test-repo-id <用例库ID> `
  --testcase-id <用例内部ID> `
  --executor-id <执行人userId>
```

确认后执行：

```powershell
skill-run yunxiao_cli_testhub.py `
  --test-plan-id <计划ID> `
  --test-repo-id <用例库ID> `
  --testcase-id <用例内部ID> `
  --executor-id <执行人userId> `
  --status PASS `
  --apply
```

适配器的硬门禁：

1. 先用官方 CLI 回读用例和计划目录。
2. 若用例未规划，返回`CLI_CAPABILITY_GAP`，回执记录阻塞原因并停止；不得猜测未公开OAPI路由。
3. 只有官方 CLI 的计划结果目录和结果列表已回读到同一用例，才允许更新执行结果。
4. PASS/FAILURE/POSTPONE/TODO 更新调用官方 `test-hub-update-test-result`。
5. 最后回读计划进度和用例结果；未匹配目标状态时返回失败，不得据此关闭测试任务。
6. 回执不写 PAT，所有异常信息都执行令牌脱敏。
