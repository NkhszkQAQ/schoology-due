# Schoology Due

[![Tests](https://github.com/NkhszkQAQ/schoology-due/actions/workflows/test.yml/badge.svg)](https://github.com/NkhszkQAQ/schoology-due/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Ask Codex what homework is due. Keep your Schoology calendar credentials on your machine.**

一个轻量、只读的 Codex Skill：用 Schoology 个人 iCal 订阅回答“今天有什么 due”“本周有什么 due”和“未来 7 天有什么作业”。Python 标准库实现，无第三方运行依赖，无需 Cookie、API 密钥或浏览器登录。

- 输出作业名称、截止时间与可选的本地课程名称映射。
- 支持 IANA 时区、文本输出和 JSON。
- 订阅配置放在仓库外；网络错误不打印私人订阅地址。
- 只查日历截止事项，不读取提交状态或成绩，不提交作业。

这是一个独立开源项目，与 Schoology、PowerSchool 或 OpenAI 没有官方关联。

## Requirements / 运行条件

Python **3.10+**，macOS 或 Linux，系统 IANA 时区数据库，以及能访问 Schoology 的网络。学校必须允许个人日历共享。其他平台未验证；本工具使用 Unix 文件权限检查。

## Install / 安装

```sh
git clone https://github.com/NkhszkQAQ/schoology-due.git
cd schoology-due
mkdir -p ~/.agents/skills
cp -R skills/schoology-due ~/.agents/skills/schoology-due
```

如果目标目录已存在，请先备份或检查差异，不要直接覆盖。当前官方 Codex 文档使用 `~/.agents/skills` 作为用户技能目录；如果你的已有环境通过其他目录加载技能，请使用该环境的目录，避免重复安装同名技能。详情见 [OpenAI skills documentation](https://developers.openai.com/codex/skills/)。

这个仓库提供本地运行的 Skill 和 CLI；安装它不会给 ChatGPT 网页聊天自动增加 Schoology connector。运行需要能够读取本机配置并执行 Python 的宿主环境。

## Configure / 私人配置

在 Schoology 的账户设置中找到 **Share Your Schoology Calendar**，启用日历共享并复制个人 iCal 链接。学校设置或界面可能不同；没有该选项时请先向学校确认。

```sh
mkdir -p ~/.config/schoology-due
chmod 700 ~/.config/schoology-due
nano ~/.config/schoology-due/ical_url
chmod 600 ~/.config/schoology-due/ical_url
```

在编辑器中粘贴链接，保存退出。支持 `https://` 和 `webcal://`，后者会转换成 HTTPS。**链接相当于日历访问凭据，不要发到聊天、Issue、命令参数或仓库。** 不需要 Cookie 或 API 密钥。

可选环境变量 `SCHOOLOGY_DUE_CONFIG` 指定其他私人配置目录。目录里仍使用 `ical_url` 和可选的 `course_map.json`。

## Use / 使用

在 Codex 中直接问：

```text
今天有什么 due？
本周有什么 due？
未来 7 天有什么 due？
用 America/New_York 时区显示。
```

也可以显式调用 `$schoology-due`，或从仓库直接运行 CLI：

```sh
python3 skills/schoology-due/scripts/schoology_due.py --today
python3 skills/schoology-due/scripts/schoology_due.py --week
python3 skills/schoology-due/scripts/schoology_due.py --days 7 --json
python3 skills/schoology-due/scripts/schoology_due.py --week --timezone America/New_York
```

默认时区为 `Asia/Shanghai`。`--today` 包含今天已过的截止时间；`--week` 从查询时刻到下周一零点，不包含本周已过的项目；`--days N` 从现在到 N 个日历日之后。文本截止时间附带该日期的 UTC 偏移，JSON 使用带偏移的 ISO 8601 时间。

虚构输出示例：

```text
本周剩余时间（Asia/Shanghai）
- Example Calculus｜Practice: derivatives｜10月14日 23:59 +0800
- 课程未标注｜Reading response｜10月16日 17:00 +0800
```

## Course names / 课程名称

日历通常不提供课程字段，没有映射时会显示 `课程未标注`。可以在私人配置目录中创建 `course_map.json`：

```json
{
  "assignments": {
    "1000000001": "Example Calculus"
  },
  "summaries": {
    "Example reading response": "Example English"
  }
}
```

示例均为虚构数据。`assignments` 按作业 URL 中 `/assignment/` 后的 ID 匹配；`summaries` 按完整标题匹配，相同标题可能跨课程重复，因此优先使用 ID。保存后执行：

```sh
chmod 600 ~/.config/schoology-due/course_map.json
```

## Privacy and limitations / 隐私与限制

- 个人配置、真实课程映射、下载的 `.ics` 和作业数据应留在本机，仓库的 `.gitignore` 提供额外防护。
- 发起请求时 Schoology 会收到你的日历链接；本项目不提供额外的遥测或数据上传服务。启用 Skill 后，查询结果会交给你的 AI 宿主用于回答。
- 日历只反映学校导出的事项。未设置截止时间、未导出或尚未同步的作业可能缺失；结果不代表完成、提交或评分状态。
- 依据 `/assignment/` 链接识别作业，不包含普通日历活动。不展开重复事件的 `RRULE`，不处理自定义 `VTIMEZONE`；支持 UTC、IANA `TZID`、浮动本地时间和全天日期。全天事项显示本地零点，具体截止要求以学校页面为准。
- 网络访问受到 Codex 的宿主权限限制；必要时允许该次日历读取。连接失败不能解释为“没有作业”。
- 如私人链接泄露，请在 Schoology 中停用/重新生成日历共享链接，并更新本机配置；不要把泄露链接放进公开反馈。

## Troubleshooting / 排错

| 现象 | 处理 |
| --- | --- |
| `URLError` / `TimeoutError` | 检查网络、TLS 证书、宿主网络权限和私人订阅设置；不要粘贴链接或原始请求到 Issue。 |
| 私密配置权限过宽 | 对 `ical_url` 和映射文件设置 `chmod 600`。 |
| 配置文件不存在 | 按上文创建 `ical_url`，或检查 `SCHOOLOGY_DUE_CONFIG`。 |
| 订阅响应不是有效的 iCal 日历 | 订阅可能失效，或返回了登录页面；检查私人订阅设置。 |
| 时区不可用 | 使用有效的 IANA 名称，并确认系统安装了时区数据库。 |
| `课程未标注` | 配置本地课程映射；不要根据标题猜课程。 |

## Development / 验证

```sh
python3 -m unittest discover -s tests -v
```

测试仅使用虚构日历和模拟网络，不读取真实配置。GitHub Actions 在 Python 3.10–3.14 上运行离线测试。真实连接测试需要用户自己的私人订阅，不进入 CI。

## License

[MIT](LICENSE). Contributions are welcome. Please use synthetic calendar data in bug reports and tests.
