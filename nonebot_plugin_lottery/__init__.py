import random
from collections import defaultdict
from datetime import datetime

from nonebot import require, get_driver, get_bot
from nonebot.log import logger
from nonebot.rule import Rule, to_me
from nonebot import on_command, on_startswith, on_keyword, on_fullmatch, on_message
from nonebot.matcher import Matcher
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent, ActionFailed
from nonebot.adapters.onebot.v11 import GROUP_ADMIN, GROUP_OWNER, GROUP_MEMBER
from nonebot.adapters.onebot.v11 import MessageSegment, Message, Event, escape
from nonebot.typing import T_State
from nonebot.params import ArgPlainText, CommandArg, ArgStr

from .lottery import execute_lottery, lotteries, parse_target_time
from .utils import (
    At,
    get_display_name_by_identity,
    get_identity_by_qq,
    refresh_contact_maps,
)

try:
    scheduler = require("nonebot_plugin_apscheduler").scheduler
except Exception:
    logger.warning("请重启程序！")
    scheduler = None

try:
    refresh_contact_maps()
except Exception as e:
    logger.error(f"刷新 Notion 联系人 QQ 映射失败：{e}")

logger.opt(colors=True).info(
    "已检测到软依赖<y>nonebot_plugin_apscheduler</y>, <g>开启定时任务功能</g>"
    if scheduler
    else "未检测到软依赖<y>nonebot_plugin_apscheduler</y>，<r>定时任务功能未启用</r>"
)

message_history = defaultdict(list)
active_tasks = {}


def startedgroupchecker():
    async def _checker(bot: Bot, event: GroupMessageEvent, state: T_State) -> bool:
        return event.group_id in active_tasks

    return Rule(_checker)


create_lottery_cmd = on_command("定时抽奖", priority=5, block=True)


@create_lottery_cmd.handle()
async def _create_lottery(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    if not scheduler:
        await create_lottery_cmd.finish("未检测到 APScheduler 插件，无法创建定时任务！")

    text = args.extract_plain_text().strip()
    if not text:
        await create_lottery_cmd.finish(
            "格式错误！请输入：/定时抽奖 项目名称 3h/10min/99s后或/定时抽奖 项目名称 2026-5-20T18-25-00(可省略年月或分秒)"
        )

    parts = text.split()
    if len(parts) < 2:
        await create_lottery_cmd.finish("格式错误！请确保项目名称与时间之间有空格隔开。")

    time_str = parts[-1]
    name = " ".join(parts[:-1])

    target_time = parse_target_time(time_str)
    if not target_time:
        await create_lottery_cmd.finish(
            "时间格式解析失败！支持格式如：3h后, 30min后, 2026-5-21T18-25-00, 21T18-25 等"
        )

    if target_time <= datetime.now():
        await create_lottery_cmd.finish(
            f"你想穿越回{target_time.strftime('%Y-%m-%dT%H:%M:%S')}吗？设定的时间必须在未来！"
        )

    lid = (
        datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        + event.get_user_id()
        + target_time.strftime("%Y-%m-%dT%H:%M:%S")
    )
    group_id = event.group_id

    lotteries[group_id][lid] = {
        "name": name,
        "setter": event.get_user_id(),
        "time": target_time,
        "participants": {},
    }

    scheduler.add_job(
        execute_lottery,
        "date",
        run_date=target_time,
        args=(bot, group_id, lid),
        id=f"lottery_{lid}",
    )

    await create_lottery_cmd.finish(
        f"已成功创建抽奖项目【{name}】\n开奖时间：{target_time.strftime('%Y-%m-%d %H:%M:%S')}\n群友发送 /报名 即可参与！"
    )


join_lottery_cmd = on_command("报名", priority=5, block=True)


@join_lottery_cmd.handle()
async def _join_lottery_check(
    matcher: Matcher,
    event: GroupMessageEvent,
    state: T_State,
    args: Message = CommandArg(),
):
    group_id = event.group_id
    if group_id not in lotteries or not lotteries[group_id]:
        await matcher.finish("哎呀，当前群内没有正在进行的定时抽奖项目哇")

    group_lots = lotteries[group_id]
    arg_text = args.extract_plain_text().strip().upper()

    if len(group_lots) == 1:
        lid = list(group_lots.keys())[0]
        ldata = group_lots[lid]
        identity = get_identity_by_qq(event.user_id)

        if identity in ldata["participants"]:
            await matcher.finish(f"您已经报名过【{ldata['name']}】了！")

        ldata["participants"][identity] = {
            "qq": event.user_id,
            "name": get_display_name_by_identity(identity),
        }

        await matcher.finish(f"报名成功！您已参加【{ldata['name']}】的抽奖。")

    mapping = {}
    msg = "发现有现在多个抽奖项目：\n"
    for i, (lid, ldata) in enumerate(group_lots.items()):
        char_key = chr(65 + i)
        mapping[char_key] = lid
        msg += f"第{char_key}条：{ldata['name']}\n"

    state["mapping"] = mapping

    if arg_text:
        matcher.set_arg("choices", args)
    else:
        msg += '请直接回复你想报名的项目对应字母（例如 "A"，报多个请回复如 "AB"）'
        await matcher.send(msg)


@join_lottery_cmd.got("choices")
async def _process_choices(
    matcher: Matcher,
    event: GroupMessageEvent,
    state: T_State,
    choices: str = ArgPlainText("choices"),
):
    mapping = state.get("mapping")
    if not mapping:
        return

    selected_chars = list(choices.strip().upper())
    joined = []
    already = []
    missing = []
    has_valid = False

    for char in selected_chars:
        if char not in mapping:
            missing.append(char)
            continue

        has_valid = True
        lid = mapping[char]

        if lid not in lotteries[event.group_id]:
            continue

        ldata = lotteries[event.group_id][lid]
        identity = get_identity_by_qq(event.user_id)

        if identity in ldata["participants"]:
            already.append(ldata["name"])
        else:
            ldata["participants"][identity] = {
                "qq": event.user_id,
                "name": get_display_name_by_identity(identity),
            }
            joined.append(ldata["name"])

    if not has_valid:
        await matcher.reject("无效的选择，请重新回复你想报名的项目字母。")

    res_msg = ""
    if joined:
        res_msg += f"成功报名：{', '.join(joined)}\n"
    if already:
        res_msg += f"已报名过：{', '.join(already)}"
    if missing:
        res_msg += f"并不存在：{', '.join(missing)}"

    await matcher.finish(res_msg.strip())


instant_lottery_cmd = on_command("抽奖", priority=5, block=True)


@instant_lottery_cmd.handle()
async def _instant_lottery_check(matcher: Matcher, event: GroupMessageEvent, state: T_State):
    participants = At(event.json())
    if not participants:
        msg = "你没有选择任何候选人！语法：/抽奖@a@b@c"
    else:
        winner_id = random.choice(participants)
        msg = Message(
            [
                MessageSegment.text("🎉 开奖啦！\n恭喜 "),
                MessageSegment.at(winner_id),
                MessageSegment.text(f" ({winner_id})赢得了本次抽奖"),
            ]
        )

    try:
        await instant_lottery_cmd.send(message=msg)
    except ActionFailed:
        logger.error(f"群 {event.group_id} 发送抽奖结果失败")
