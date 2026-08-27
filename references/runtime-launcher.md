# 跨平台脚本启动器

所有文档、交接信息和后续动作只记录统一逻辑口令：

```text
skill-run <script.py> [参数...]
```

`skill-run` 不是需要额外安装的系统命令。执行当前 Skill 的 Agent 必须把它解析为本 Skill 自带启动器：Windows 使用 `scripts/run-skill-script.ps1`，macOS/Linux 使用 `scripts/run-skill-script.sh`。禁止到其他 Skill、用户主目录或固定 Windows 路径中查找脚本。

Windows 启动器若发现当前 Codex/Cursor 进程未继承云效环境变量，会仅对
`ALIBABA_CLOUD_YUNXIAO_*`和`ALIYUN_CLI_PATH`白名单从用户级、系统级环境变量
补入当前子进程。不得输出或另行持久化变量值；该机制用于客户端未重启或令牌轮换后的安全恢复。

启动器只运行同一 `scripts` 目录中的 `.py` 文件；拒绝绝对路径、相对目录和路径穿越；只选择通过版本检查的 Python 3；通过系统运行时获取临时目录并设置 `ONEOS_YUNXIAO_TEMP_DIR`；原样返回输出和退出码。找不到 Python 3、脚本不存在或参数非法时必须明确失败，不得伪造成功或静默改走浏览器。

业务链路只传递 Skill 正式名、需求/交付/开发/测试/缺陷/发版编号、状态与关系以及必要证据。Cosa、Code X 或其他宿主不需要知道另一端的物理安装目录。
