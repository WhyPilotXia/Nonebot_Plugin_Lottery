# nonebot-plugin-lottery-signup

_NoneBot2 群聊抽奖与报名插件_

<a href="https://pypi.org/project/nonebot-plugin-lottery-signup/">
  <img src="https://img.shields.io/pypi/v/nonebot-plugin-lottery-signup.svg" alt="PyPI">
</a>
<a href="https://pypi.org/project/nonebot-plugin-lottery-signup/">
  <img src="https://img.shields.io/pypi/pyversions/nonebot-plugin-lottery-signup.svg" alt="Python">
</a>
<a href="https://github.com/WhyPilotXia/nonebot-plugin-lottery-signup/blob/main/LICENSE">
  <img src="https://img.shields.io/github/license/WhyPilotXia/nonebot-plugin-lottery-signup.svg" alt="License">
</a>



适用于 NoneBot2 + OneBot V11 的群聊抽奖与报名插件，支持定时抽奖、即时抽奖、限额报名和多项目并发。Notion 联系人去重为可选功能：未配置 Notion 时，插件会直接使用 QQ 号作为去重身份。

## 功能

- 定时抽奖：创建未来指定时间自动开奖的抽奖项目。
- 抽奖报名：群友通过 `/报名` 参与当前群内的定时抽奖。
- 即时抽奖：直接从 `@` 的候选人里随机抽取一人。
- 限额报名：创建独立报名项目，到截止时间、满员或发起者停止时公布名单。
- 多项目选择：同一群内存在多个抽奖或报名项目时，可用 `A`、`AB` 等字母选择一个或多个项目。
- 可选 Notion 去重：配置 Notion 后，同一联系人绑定的多个 QQ 会被视为同一报名身份。

## 安装

使用 nb-cli：

```bash
nb plugin install nonebot-plugin-lottery-signup
```

或使用 pip：

```bash
pip install nonebot-plugin-lottery-signup
```

如果需要启用 Notion 联系人去重，请安装额外依赖：

```bash
pip install "nonebot-plugin-lottery-signup[notion]"
```

## 加载

在 NoneBot 项目中加载插件：

```python
nonebot.load_plugin("nonebot_plugin_lottery_signup")
```

插件依赖 `nonebot-plugin-apscheduler` 提供定时任务能力。通过 PyPI 安装本插件时会自动安装该依赖；如果未加载 APScheduler，定时抽奖和定时报名会不可用。

## 配置

配置项写入 NoneBot 全局配置，例如 `.env`、`.env.prod` 或项目配置文件。

| 配置项 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `notion_token` | 否 | 空 | Notion Integration Token。配置后启用 Notion 联系人去重。 |
| `lottery_contact_data_source_id` | 否 | "31e70d82-c716-8034-b23d-000ba20878af" | Notion 联系人 data source id。仅在配置 `notion_token` 后要求填写。 |

不使用 Notion 时无需配置上述两项：

```env
# 留空或不写 notion_token，插件会使用 QQ 号去重
```

启用 Notion 去重：

```env
notion_token=ntn_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
lottery_contact_data_source_id=31e70d82-c716-8034-b23d-000ba20878af
```

Notion 联系人库至少需要包含以下属性：

- `姓名/昵称`：用于报名名单和开奖结果展示。
- `QQ`：用于匹配群成员 QQ。支持英文逗号或中文逗号分隔多个 QQ，例如 `123456, 234567`。
示例：

<img width="1374" height="979" alt="image" src="https://github.com/user-attachments/assets/6a4a20ac-5ba7-4326-9411-1c344cc529c4" />



## 指令

### 定时抽奖

创建一个未来自动开奖的抽奖项目：

```text
/定时抽奖 项目名称 时间
```

示例：

```text
/定时抽奖 肯德基v我50 3h后
/定时抽奖 夜宵抽奖 30min后
/定时抽奖 跨年大奖 2026-12-31T23-59-59
/定时抽奖 今晚夜宵 T22-30
```

时间支持：

- 相对时间：`3h后`、`30min后`、`99s后`
- 绝对时间：`2026-12-31T23-59-59`、`5-1T12-00`、`21T18-25`、`T18`

参与定时抽奖：

```text
/报名
/报名 A
/报名 AB
```

当群内只有一个抽奖项目时，发送 `/报名` 会直接参加。存在多个项目时，机器人会列出 `A`、`B`、`C` 等选项，可回复字母，也可直接在命令后附带字母。


示例图片：

<img width="1440" height="2568" alt="IMG_20260608_010419" src="https://github.com/user-attachments/assets/3d62523c-2e26-4c5b-b75c-ad7fe4cfd585" />




### 即时抽奖

从指定候选人中立即抽取一人：

```text
/抽奖 @用户1 @用户2 @用户3
```

### 限时限额报名

创建一个独立报名项目：

```text
/创建报名 项目名 人数 截止时间
```

示例：

```text
/创建报名 18号首日封 5人 2026-6-18T18-00
/创建报名 桌游车 4人 2h后
```

参加报名：

```text
/参加报名
/参加报名 A
/参加报名 AB
```

停止自己发起的报名：

```text
/停止报名
/停止报名 A
```

报名项目会在以下情况关闭并公布名单：

- 到达截止时间。
- 报名人数达到名额上限。
- 发起者使用 `/停止报名` 主动停止。

## 去重规则

- 未启用 Notion：同一个 QQ 对同一项目只能报名一次。
- 启用 Notion：插件启动时读取联系人库，建立 `QQ -> 联系人` 映射；同一联系人名下的多个 QQ 会被视为同一个报名身份。
- 由于联系人不常变动，Notion 映射只在插件启动时刷新，运行期间修改联系人库后需要重启机器人生效。

