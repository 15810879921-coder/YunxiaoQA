# 贡献指南 · YunxiaoQA（测试同学可改可推）

欢迎测试同学根据**真实使用踩坑**优化本 Skill，并直接推回仓库。仓库已对协作者开放 **Write**；不是协作者请先找仓库管理员加权限，或提 PR。

## 1. 拿到写权限

1. 把你的 **GitHub 用户名**发给仓库管理员（当前 owner：`15810879921-coder`）。
2. 管理员执行（`push` = Write）：

```bash
gh api -X PUT repos/15810879921-coder/YunxiaoQA/collaborators/<你的GitHub用户名> -f permission=push
```

3. 你打开邮件 / GitHub 通知，**接受邀请**后即可 `git push`。

> 与 `oneos-pm-skills` 同一套协作模型。已邀请示例：`luffyhe`（Write）。

## 2. 本地改 Skill（推荐工作流）

**不要只改** `npx skills` 装出来的目录就完事——那份容易被 `skills update` 覆盖，也推不回 GitHub。

```bash
# 1）克隆可写仓库（或已有则 pull）
git clone https://github.com/15810879921-coder/YunxiaoQA.git
cd YunxiaoQA
git checkout main && git pull

# 2）改完自测（至少）
python3 scripts/check_auth.py
# 涉及写操作：先 --dry-run，再 Plan 确认后的真实脚本

# 3）提交并推送
git add -A
git commit -m "fix: 简述你解决了什么踩坑"
git push origin main
```

### 让本机 Cursor / Codex 立刻用上你的改动

推送后，同事（含你自己）更新安装副本：

```bash
npx skills update YunxiaoQA
# Codex 若仍读不到，再链一次：
mkdir -p ~/.codex/skills && ln -sfn ~/.agents/skills/yunxiaoqa ~/.codex/skills/yunxiaoqa
```

开发中想**边改边用**，可把全局安装目录换成你的 clone（或软链）：

```bash
# 示例：Cursor 全局技能目录指向你的 clone（路径按本机调整）
ln -sfn "$(pwd)" ~/.agents/skills/yunxiaoqa
ln -sfn "$(pwd)" ~/.cursor/skills/YunxiaoQA
mkdir -p ~/.codex/skills && ln -sfn "$(pwd)" ~/.codex/skills/yunxiaoqa
```

## 3. 建议改什么 / 别乱动什么

| 鼓励 | 谨慎 / 禁止 |
|---|---|
| `references/*.md` 口令、诊断、模板、踩坑说明 | 把 Cookie / 密码 / Token 写进仓库 |
| `scripts/*.py` 稳妥修复、更清晰报错、dry-run | 用浏览器 DOM 点选改云效状态（编号串单事故） |
| `README.md` / 本文件安装与协作说明 | 静默扩大「测试可改」的云效状态机（已修复/暂不修复属开发侧） |
| `assets/runtime-ids.json` 中**非秘密**常量补齐 | 删除 Plan 门禁、编号硬门禁、ASSOCIATED→【测试】硬校验 |

大改状态机或 API 契约：先开 Issue 或 PR 说明，避免打断其他人正在用的口令。

## 4. 没有 Write 时：Fork + PR

仓库公开，可 Fork 后提 PR 到 `main`。管理员合并后，大家 `npx skills update YunxiaoQA` 即可。

## 5. 管理员：批量邀请

```bash
# 多个测试同学 GitHub 用户名空格分隔
for u in user1 user2 user3; do
  gh api -X PUT "repos/15810879921-coder/YunxiaoQA/collaborators/$u" -f permission=push
  echo "invited: $u"
done
```

查看当前协作者 / 待接受邀请：

```bash
gh api repos/15810879921-coder/YunxiaoQA/collaborators --jq '.[] | {login, role_name}'
gh api repos/15810879921-coder/YunxiaoQA/invitations --jq '.[] | {invitee: .invitee.login, permissions}'
```
