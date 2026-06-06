import random
import re
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
from .registration import close_registration, make_registration_id, registrations
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


def _remove_scheduler_job(job_id: str):
    if not scheduler:
        return

    try:
        scheduler.remove_job(job_id)
    except Exception:
        pass


create_registration_cmd = on_command("创建报名", priority=5, block=True)


@create_registration_cmd.handle()
async def _create_registration(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    if not scheduler:
        await create_registration_cmd.finish("未检测到 APScheduler 插件，无法创建定时报名任务！")

    text = args.extract_plain_text().strip()
    if not text:
        await create_registration_cmd.finish(
            "格式错误！请输入：/创建报名 项目名 xx人 截止时间\n例如：/创建报名 18号首日封 5人 2026-6-18T18-00",reply=True
        )

    parts = text.split()
    if len(parts) < 3:
        await create_registration_cmd.finish("格式错误！请按格式输入：/创建报名 项目名 xx人 截止时间",reply=True)

    time_str = parts[-1]
    limit_str = parts[-2]
    name = " ".join(parts[:-2]).strip()

    limit_match = re.match(r"^(\d+)人$", limit_str)
    if not name or not limit_match:
        await create_registration_cmd.finish("格式错误！人数请写成 5人 这样的格式。",reply=True)

    limit = int(limit_match.group(1))
    if limit <= 0:
        await create_registration_cmd.finish("报名人数必须大于 0。",reply=True)

    target_time = parse_target_time(time_str)
    if not target_time:
        await create_registration_cmd.finish(
            "时间格式解析失败！支持格式如：3h后, 30min后, 2026-5-21T18-25-00, 21T18-25 等",reply=True
        )

    if target_time <= datetime.now():
        await create_registration_cmd.finish(
            f"设定的截止时间必须在未来：{target_time.strftime('%Y-%m-%d %H:%M:%S')}",reply=True
        )

    group_id = event.group_id
    setter = event.get_user_id()
    rid = make_registration_id(setter, target_time)
    job_id = f"registration_{rid}"

    registrations[group_id][rid] = {
        "name": name,
        "setter": setter,
        "time": target_time,
        "limit": limit,
        "participants": {},
        "job_id": job_id,
    }

    scheduler.add_job(
        close_registration,
        "date",
        run_date=target_time,
        args=(bot, group_id, rid),
        id=job_id,
    )

    await create_registration_cmd.finish(
        f"已创建报名项目【{name}】\n名额：{limit}人\n截止时间：{target_time.strftime('%Y-%m-%d %H:%M:%S')}\n群友发送 /参加报名 即可报名。",reply=True
    )


join_registration_cmd = on_command("参加报名", priority=5, block=True)


async def _join_registration(bot: Bot, matcher: Matcher, event: GroupMessageEvent, rid: str):
    group_id = event.group_id
    if group_id not in registrations or rid not in registrations[group_id]:
        await matcher.finish("当前群还没有报名项目或这个报名项目已经不存在了。")

    rdata = registrations[group_id][rid]
    identity = get_identity_by_qq(event.user_id)

    if identity in rdata["participants"]:
        await matcher.finish(f"您已经报名过【{rdata['name']}】了！",reply=True)

    if len(rdata["participants"]) >= rdata["limit"]:
        await matcher.finish(f"【{rdata['name']}】报名已满。",reply=True)

    rdata["participants"][identity] = {
        "qq": event.user_id,
        "name": get_display_name_by_identity(identity),
    }

    if len(rdata["participants"]) >= rdata["limit"]:
        _remove_scheduler_job(rdata.get("job_id", ""))
        await close_registration(bot, group_id, rid, reason="full")
        return

    await matcher.finish(
        f"报名成功！您已参加【{rdata['name']}】。\n当前人数：{len(rdata['participants'])}/{rdata['limit']}"
    )


@join_registration_cmd.handle()
async def _join_registration_check(
    bot: Bot,
    matcher: Matcher,
    event: GroupMessageEvent,
    state: T_State,
    args: Message = CommandArg(),
):
    group_id = event.group_id
    if group_id not in registrations or not registrations[group_id]:
        await matcher.finish("当前群内没有正在进行的报名项目。",reply=True)

    group_regs = registrations[group_id]
    arg_text = args.extract_plain_text().strip().upper()

    if len(group_regs) == 1:
        rid = list(group_regs.keys())[0]
        await _join_registration(bot, matcher, event, rid)
        return

    mapping = {}
    msg = "当前有多个报名项目：\n"
    for i, (rid, rdata) in enumerate(group_regs.items()):
        char_key = chr(65 + i)
        mapping[char_key] = rid
        msg += f"第{char_key}条：{rdata['name']}（{len(rdata['participants'])}/{rdata['limit']}）\n"

    state["mapping"] = mapping

    if arg_text:
        matcher.set_arg("choices", args)
    else:
        msg += '请直接回复你想参加的项目字母（例如 "A"，报多个请回复如 "AB"）'
        await matcher.send(msg,reply=True)


@join_registration_cmd.got("choices")
async def _process_registration_choices(
    bot: Bot,
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
    full = []
    has_valid = False

    for char in selected_chars:
        if char not in mapping:
            missing.append(char)
            continue

        has_valid = True
        rid = mapping[char]

        if rid not in registrations[event.group_id]:
            continue

        rdata = registrations[event.group_id][rid]
        identity = get_identity_by_qq(event.user_id)

        if identity in rdata["participants"]:
            already.append(rdata["name"])
            continue

        if len(rdata["participants"]) >= rdata["limit"]:
            full.append(rdata["name"])
            continue

        rdata["participants"][identity] = {
            "qq": event.user_id,
            "name": get_display_name_by_identity(identity),
        }

        if len(rdata["participants"]) >= rdata["limit"]:
            full.append(rdata["name"])
            _remove_scheduler_job(rdata.get("job_id", ""))
            await close_registration(bot, event.group_id, rid, reason="full")
        else:
            joined.append(rdata["name"])

    if not has_valid:
        if state['rejected']:
            await matcher.finish("多次无效选择，撤销操作",reply=True)
        state['rejected'] = True
        await matcher.reject("无效的选择，请重新回复你想参加的项目字母。",reply=True)

    res_msg = ""
    if joined:
        res_msg += f"成功报名：{', '.join(joined)}\n"
    if already:
        res_msg += f"已报名过：{', '.join(already)}\n"
    if full:
        res_msg += f"已满或刚刚报满：{', '.join(full)}\n"
    if missing:
        res_msg += f"并不存在：{', '.join(missing)}"

    if res_msg.strip():
        await matcher.finish(res_msg.strip(),reply=True)


stop_registration_cmd = on_command("停止报名", priority=5, block=True)


@stop_registration_cmd.handle()
async def _stop_registration_check(
    bot: Bot,
    matcher: Matcher,
    event: GroupMessageEvent,
    state: T_State,
    args: Message = CommandArg(),
):
    group_id = event.group_id
    user_id = event.get_user_id()
    group_regs = registrations.get(group_id, {})
    own_regs = {
        rid: rdata
        for rid, rdata in group_regs.items()
        if rdata.get("setter") == user_id
    }

    if not own_regs:
        await matcher.finish("当前没有由您发起的报名项目。",reply=True)

    arg_text = args.extract_plain_text().strip()

    if len(own_regs) == 1 and not arg_text:
        rid, rdata = next(iter(own_regs.items()))
        _remove_scheduler_job(rdata.get("job_id", ""))
        await close_registration(bot, group_id, rid, reason="stop")
        return

    mapping = {}
    msg = "您发起了多个报名项目：\n"
    for i, (rid, rdata) in enumerate(own_regs.items()):
        char_key = chr(65 + i)
        mapping[char_key] = rid
        msg += f"第{char_key}条：{rdata['name']}（{len(rdata['participants'])}/{rdata['limit']}）\n"

    state["mapping"] = mapping

    if arg_text:
        matcher.set_arg("choices", args)
    else:
        msg += '请回复要停止的项目字母（例如 "A"）'
        await matcher.send(msg)


@stop_registration_cmd.got("choices")
async def _process_stop_registration_choices(
    bot: Bot,
    matcher: Matcher,
    event: GroupMessageEvent,
    state: T_State,
    choices: str = ArgPlainText("choices"),
):
    mapping = state.get("mapping")
    if not mapping:
        return

    choice = choices.strip().upper()
    if choice not in mapping:
        if state['rejected']:
            await matcher.finish("多次输错，取消停止",reply=True)
        state['rejected'] = True
        await matcher.reject("无效的选择，请重新回复要停止的项目字母。",reply=True)

    rid = mapping[choice]
    if event.group_id not in registrations or rid not in registrations[event.group_id]:
        await matcher.finish("这个报名项目已经不存在了。",reply=True)

    rdata = registrations[event.group_id][rid]
    _remove_scheduler_job(rdata.get("job_id", ""))
    await close_registration(bot, event.group_id, rid, reason="stop")


create_lottery_cmd = on_command("定时抽奖", priority=5, block=True)


@create_lottery_cmd.handle()
async def _create_lottery(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    if not scheduler:
        await create_lottery_cmd.finish("未检测到 APScheduler 插件，无法创建定时任务！")

    text = args.extract_plain_text().strip()
    if not text:
        await create_lottery_cmd.finish(
            "格式错误！请输入：/定时抽奖 项目名称 3h/10min/99s后或/定时抽奖 项目名称 2026-5-20T18-25-00(可省略年月或分秒)",reply=True
        )

    parts = text.split()
    if len(parts) < 2:
        await create_lottery_cmd.finish("格式错误！请确保项目名称与时间之间有空格隔开。",reply=True)

    time_str = parts[-1]
    name = " ".join(parts[:-1])

    target_time = parse_target_time(time_str)
    if not target_time:
        await create_lottery_cmd.finish(
            "时间格式解析失败！支持格式如：3h后, 30min后, 2026-5-21T18-25-00, 21T18-25 等",reply=True
        )

    if target_time <= datetime.now():
        await create_lottery_cmd.finish(
            f"你想穿越回{target_time.strftime('%Y-%m-%dT%H:%M:%S')}吗？设定的时间必须在未来！",reply=True
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
        f"已成功创建抽奖项目【{name}】\n开奖时间：{target_time.strftime('%Y-%m-%d %H:%M:%S')}\n群友发送 /报名 即可参与！",reply=True
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
            await matcher.finish(f"您已经报名过【{ldata['name']}】了！",reply=True)

        ldata["participants"][identity] = {
            "qq": event.user_id,
            "name": get_display_name_by_identity(identity),
        }

        await matcher.finish(f"报名成功！您已参加【{ldata['name']}】的抽奖。",reply=True)

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
        await matcher.send(msg,reply=True)


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

    await matcher.finish(res_msg.strip(),reply=True)


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
        await instant_lottery_cmd.send(message=msg,reply=True)
    except ActionFailed:
        logger.error(f"群 {event.group_id} 发送抽奖结果失败")
