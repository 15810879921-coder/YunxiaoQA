# 每日交付任务监测与测试计划

## 固定口径

- 频率：每日一次（Asia/Shanghai）。
- 项目：`01_ONEOS`；历史 spaceId 为`1280be963a5a2cc126a4118dca`，每次写前必须`GetProject`回读项目编号或名称。
- 交付范围：仅新出现、工作项分类为`Task`且标题同时精确包含全角标记`【交付】`、`【新增】`的交付任务；`【开发】`、`【测试】`等其他任务不处理。
- 测试计划名称：移除`【交付】`、`【新增】`和多余空白/标点，最多40字符；不得按标题猜工作项ID。
- 日期：运行当天为开始日，结束日为开始日后14个自然日。
- 管理员、参与人：均为`谢佳伟`；每次写前用`SearchMembers`按启用状态精确唯一回读userId。
- 关联项目：`01_ONEOS`；关联迭代：交付任务返回的同一`sprint.id`。交付任务无迭代时不建计划，次日重试并通知。
- 用例库：扫描当前PAT可见的全部用例库。
- 用例添加：匹配后通知用户确认；未收到“计划ID+用例ID”的逐批确认前禁止添加。

## 执行入口

```powershell
# 只读预检
skill-run yunxiao_delivery_plan_monitor.py

# 用户已经确认本固定规则后，供每日自动化执行
skill-run yunxiao_delivery_plan_monitor.py --apply
```

中心版要求本机安全配置：

- `ALIBABA_CLOUD_YUNXIAO_ACCESS_TOKEN`
- `ALIBABA_CLOUD_YUNXIAO_ORGANIZATION_ID`

中心版接入点默认`https://openapi-rdc.aliyuncs.com`。Region版必须额外设置
`ALIBABA_CLOUD_YUNXIAO_ENDPOINT=https://<实例域名>`。禁止在聊天、回执、仓库或
定时任务提示词中写入PAT。

## 幂等与首次运行

1. 首次成功`--apply`只建立当前交付任务基线，默认不为历史`【交付】【新增】`任务补建计划。
2. 后续按交付任务内部ID去重；本地状态默认位于
   `%LOCALAPPDATA%\OneOS\YunxiaoQA\delivery-testplan-monitor.json`。
3. 创建前再按项目+迭代+规范化计划名调用`ListTestPlan`查重。
4. 创建描述写入`YunxiaoQA delivery=<交付任务内部ID>`幂等标识。
5. 创建成功后立即回读计划；即使用例扫描失败，也必须保存计划ID，后续不得重复创建。
6. **创建后状态**：新建计划回读成功后，同一 apply 清单内将计划状态改为「进行中」（`DOING`）并再次回读；细则见 [yunxiao-cli-testhub.md](yunxiao-cli-testhub.md)「测试计划状态机」。用例全部执行完成后才改为「已完成」（`DONE`），本监测脚本不在建计划当场标 DONE。
7. 只有整轮交付任务读取成功才更新`lastSuccessfulScanAt`。

`--bootstrap-existing`会处理首次运行时已有的匹配交付任务，属于扩大写入范围，必须另行
Plan确认；每日自动化不得默认携带该参数。

## 用例匹配与通知

脚本从精确到宽松提取最多3个标题关键字，逐库调用`SearchTestCases`的
`subject CONTAINS`，同一用例按`用例库ID+用例ID`去重。

- 有匹配：状态`awaiting-case-confirmation`，通知计划ID/名称、交付任务编号、迭代ID、
  用例库ID/名称、用例ID/编号/标题、命中关键字。不得自动规划。
- 无匹配：状态`no-matching-cases`，通知“全部可见用例库无同关键字用例”。
- 部分用例库扫描失败：保留已建计划和已匹配结果，同时列出`caseScanErrors`；不得宣称全库无匹配。
- PAT/组织ID缺失：`AUTH_CONFIG_MISSING`，在任何云端读取和写入之前停止。

## 自动化提示词（每日一次）

自动化必须在`D:\codex`执行：

```text
使用 YunxiaoQA 技能运行 skill-run yunxiao_delivery_plan_monitor.py --apply。
严格按技能中的“每日交付任务监测与测试计划”固定口径执行。若缺少PAT/组织ID，只报告
AUTH_CONFIG_MISSING和本机配置方法，不读取或写入云效；不要索要或回显令牌。若有新计划，
报告计划回读和用例匹配；匹配用例仅通知确认，不自动添加。若无新交付任务，报告本次扫描成功且零新增。
```
