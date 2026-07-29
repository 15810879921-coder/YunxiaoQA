# 发起缺陷 · 挂载点选（【测试】+ 需求）

缺陷发布前必须点选挂载锚点，**禁止** Agent 静默猜【测试】编号或需求编号。

## 强制规则

1. 缺陷 = 所选【测试】的 **TASK_SUB 子项**
2. 缺陷 **ASSOCIATED→** 所选产品需求（可从测试追溯预填，仍须点选确认）
3. 未点选（或压缩串未解析回显）→ **禁止** `create_bug.py` 实写

## 何时触发

| 场景 | 是否点选 |
|---|---|
| `发起缺陷` / 绑测试的非本期 | **必须**点选【测试】；再点选需求 |
| 口令已写 `测试任务=ONEOS-xx` 且列表唯一命中 | Plan/`AskQuestion` **预勾 ★**，仍须用户确认 |
| 口令已写 `需求=` 且唯一命中 | 需求题预勾 ★，仍须确认 |
| `发起缺陷(非本期)` 且 Plan 明示「无测试锚点」`allow-no-test` | 可跳过本门禁 |

## 执行顺序

```text
list_bug_anchors.py --gate test
  → AskQuestion「挂载点选 · 【测试】」（或文字字母表）
  → 用户点选 / 压缩串
  → 人话回显一行（编号|标题）
list_bug_anchors.py --gate req --test-task <已选编号>
  → AskQuestion「挂载点选 · 产品需求」
  → 用户点选 / 确认预勾
  → 人话回显
Plan 汇总 → 用户「确认/执行」→ create_bug.py --test-task … [--req …]
```

## 脚本

```bash
# 测试任务字母表（默认待处理+处理中）
python3 scripts/list_bug_anchors.py --gate test

# 口令预填
python3 scripts/list_bug_anchors.py --gate test --match DEMO-90

# 已选测试后拉需求候选
python3 scripts/list_bug_anchors.py --gate req --test-task DEMO-90
```

stdout 含：

- `askQuestion`：可直接喂给 Cursor `AskQuestion`（`options[].id` = `a`/`b`/…）
- `letters`：字母 → `{serialNumber,id,subject,…}` 映射
- `suggestedLetter`：唯一命中或 auto_trace 时的建议项（通常 `a`）

## AskQuestion 规格

| 题 `id` | prompt | 选项 |
|---|---|---|
| `test_task` | 挂载点选 · 【测试】任务（缺陷将成为其子项） | `a`/`b`/… 来自脚本当轮列表 |
| `req` | 挂载点选 · 产品需求（将 ASSOCIATED 到缺陷） | `a`/`b`/…；`auto_trace` 命中标 ★ 置顶 |

- `title` 建议：`YunxiaoQA · 缺陷挂载点选`
- 可两题同卡（先跑 `--gate both --test-task` 不适用；应先选测试再拉需求，故通常 **两卡串行**）
- 渠道优先级与 YunxiaoPM 一致：**AskQuestion > 压缩串 > 明文**

## 文字字母表（后备）

```text
挂载点选 · 【测试】
a. DEMO-90 · 【测试】… · 处理中
b. …

请回复字母，或压缩串（仅本题时如：a）
```

## 禁止

- 未点选就 `create_bug.py` 去掉 `--dry-run`
- 列表为空时瞎选已完成单或按标题模糊猜编号
- 需求 0 候选时静默跳过 ASSOCIATED（应停并要求补关联或口令 `需求=`）
- 把缓存/上轮字母表当当轮真相（必须以脚本当轮 stdout 为准）
