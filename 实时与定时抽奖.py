import base64
import json
import os
import re
import random
from datetime import datetime, timedelta
from collections import defaultdict
from io import BytesIO
from typing import Union

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
import time
from notion_client import Client

driver = get_driver()
# =================notion_contacts工具函数开始=================
NOTION_TOKEN = driver.config.notion_token
CONTACT_DATA_SOURCE_ID = "31e70d82-c716-8034-b23d-000ba20878af"

notion = Client(auth=NOTION_TOKEN)

# QQ -> contact_id
qq_to_contact_id = {}

# contact_id -> contact_info
contact_id_to_info = {}


def _read_property(prop: dict):
    """
    简单读取 Notion property。
    你原代码里已经有 _read_property 的话，可以沿用自己的。
    """
    if not prop:
        return ""

    prop_type = prop.get("type")

    if prop_type == "title":
        return "".join(x.get("plain_text", "") for x in prop.get("title", []))

    if prop_type == "rich_text":
        return "".join(x.get("plain_text", "") for x in prop.get("rich_text", []))

    if prop_type == "email":
        return prop.get("email") or ""

    if prop_type == "phone_number":
        return prop.get("phone_number") or ""

    if prop_type == "number":
        value = prop.get("number")
        return "" if value is None else str(value)

    if prop_type == "url":
        return prop.get("url") or ""

    return ""


def _query_all_rows(data_source_id, page_size=100):
    results = []
    start_cursor = None

    while True:
        kwargs = {
            "data_source_id": data_source_id,
            "page_size": page_size,
        }

        if start_cursor:
            kwargs["start_cursor"] = start_cursor

        for i in range(10):
            try:
                resp = notion.data_sources.query(**kwargs)
                break
            except Exception as e:
                if i >= 7:
                    logger.warning(f"查询 Notion 联系人失败，第 {i + 1} 次重试：{e}")
                time.sleep(1)

                if i >= 9:
                    raise

        results.extend(resp.get("results", []))

        if not resp.get("has_more"):
            break

        start_cursor = resp.get("next_cursor")

    return results


def get_contacts():
    rows = _query_all_rows(CONTACT_DATA_SOURCE_ID)
    contacts = []

    for row in rows:
        props = row.get("properties", {})
        row_id = row.get("id")

        contact = {
            "id": row_id,
            "姓名": _read_property(props.get("姓名/昵称", {})),
            "电话": _read_property(props.get("电话", {})),
            "邮箱": _read_property(props.get("电子邮箱", {})),
            "地址1": _read_property(props.get("地址1", {})),
            "邮编1": _read_property(props.get("邮编1", {})),
            "地址2": _read_property(props.get("地址2", {})),
            "邮编2": _read_property(props.get("邮编2", {})),
            "QQ": _read_property(props.get("QQ", {})),
            "url": row.get("url", ""),
        }

        contacts.append(contact)

    return contacts


def refresh_contact_maps():
    """
    从 Notion 刷新 QQ 映射表。

    结果：
    qq_to_contact_id = {
        "123456": "notion_page_id_1",
        "7891011": "notion_page_id_1",
        "222333": "notion_page_id_2",
    }
    """
    global qq_to_contact_id, contact_id_to_info

    contacts = get_contacts()

    new_qq_to_contact_id = {}
    new_contact_id_to_info = {}

    for item in contacts:
        contact_id = item.get("id")
        qq_str = item.get("QQ", "")

        if not contact_id:
            continue

        new_contact_id_to_info[contact_id] = item

        if not qq_str:
            continue

        qq_list = [
            qq.strip()
            for qq in str(qq_str).replace("，", ",").split(",")
            if qq.strip()
        ]

        for qq in qq_list:
            new_qq_to_contact_id[qq] = contact_id

    qq_to_contact_id = new_qq_to_contact_id
    contact_id_to_info = new_contact_id_to_info

    logger.info(f"已刷新 Notion 联系人 QQ 映射，共 {len(qq_to_contact_id)} 个 QQ")

    return qq_to_contact_id


def get_contact_id_by_qq(qq: int | str):
    """
    根据 QQ 获取联系人 id。
    如果 Notion 里没有这个 QQ，则返回 None。
    """
    return qq_to_contact_id.get(str(qq))


def get_identity_by_qq(qq: int | str):
    """
    抽奖用的统一身份 ID。

    如果 QQ 在 Notion 联系人库里：
        返回 contact:{notion_page_id}

    如果 QQ 不在 Notion 联系人库里：
        返回 qq:{qq}

    这样可以保证：
    1. 同一个联系人多个 QQ 会被视为同一个人；
    2. 没录入 Notion 的 QQ 也能正常报名。
    """
    qq = str(qq)
    contact_id = get_contact_id_by_qq(qq)

    if contact_id:
        return f"contact:{contact_id}"

    return f"qq:{qq}"


def get_display_name_by_identity(identity: str):
    """
    用于提示报名信息。
    """
    if identity.startswith("contact:"):
        contact_id = identity.removeprefix("contact:")
        info = contact_id_to_info.get(contact_id, {})
        return info.get("姓名") or contact_id

    if identity.startswith("qq:"):
        return identity.removeprefix("qq:")

    return identity
# =================notion_contacts工具函数结束=================

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

# 全局变量
message_history = defaultdict(list)
active_tasks = {}



# 抽奖系统全局变量：字典结构群号映射到抽奖项目
# lotteries[group_id][lottery_id] = {"name": str, "time": datetime, "participants": {}}
lotteries = defaultdict(dict)


def startedgroupchecker():
    async def _checker(bot: Bot, event: GroupMessageEvent, state: T_State) -> bool:
        if event.group_id in active_tasks:
            return True
        return False

    return Rule(_checker)



# ===================== 定时抽奖与报名系统 =====================

def parse_target_time(time_str: str) -> datetime:
    """时间解析函数"""
    now = datetime.now()

    # 1. 匹配相对时间 (3h后, 30min后, 15s后)
    rel_match = re.match(r'^(\d+)(h|min|s)后$', time_str)
    if rel_match:
        val = int(rel_match.group(1))
        unit = rel_match.group(2)
        if unit == 'h': return now + timedelta(hours=val)
        if unit == 'min': return now + timedelta(minutes=val)
        if unit == 's': return now + timedelta(seconds=val)

    # 2. 匹配绝对时间 T 格式 (2026-5-21T18-25-00)
    if 'T' not in time_str:
        return None
    # /定时抽奖 项目名称 3h后（支持xxh后/xxmin后/xxs后）或/定时抽奖 项目名称 2026-5-21T18-25-00
    date_part, time_part = time_str.split('T', 1)
    # 默认当前时区，如果日期漏了比如只输入5-21默认今年，只输入21默认当月，时间漏输默认18则为18-00-00，18-25默认18-25-00
    # 默认日期补全策略
    year, month, day = now.year, now.month, now.day
    if date_part:
        d_splits = date_part.split('-')
        if len(d_splits) == 3:
            year, month, day = map(int, d_splits)
        elif len(d_splits) == 2:
            month, day = map(int, d_splits)
        elif len(d_splits) == 1:
            day = int(d_splits[0])

    # 默认时间补全策略
    hour, minute, second = 0, 0, 0
    if time_part:
        t_splits = time_part.split('-')
        if len(t_splits) == 3:
            hour, minute, second = map(int, t_splits)
        elif len(t_splits) == 2:
            hour, minute = map(int, t_splits)
        elif len(t_splits) == 1:
            hour = int(t_splits[0])

    try:
        return datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None


async def execute_lottery(bot: Bot, group_id: int, lid: str):
    """抽奖执行回调函数"""
    if group_id not in lotteries or lid not in lotteries[group_id]:
        return

    ldata = lotteries[group_id].pop(lid)

    if not lotteries[group_id]:
        del lotteries[group_id]

    participants = ldata["participants"]
    name = ldata["name"]

    if not participants:
        msg = f"⏱ 定时抽奖【{name}】时间到！\n很遗憾，由于无人报名，抽奖已取消。"
    else:
        winner_identity = random.choice(list(participants.keys()))
        winner_info = participants[winner_identity]

        winner_qq = winner_info["qq"]
        winner_name = winner_info.get("name", "")

        msg = Message([
            MessageSegment.text(f"🎉 定时抽奖【{name}】开奖啦！\n恭喜 "),
            MessageSegment.at(winner_qq),
            MessageSegment.text(f" ({winner_name} / {winner_qq}) 成为鼠鼠的幸运儿！")
        ])

    try:
        await bot.send_group_msg(group_id=group_id, message=msg)
    except ActionFailed:
        logger.error(f"群 {group_id} 发送抽奖结果失败")


create_lottery_cmd = on_command("定时抽奖", priority=5, block=True)


@create_lottery_cmd.handle()
async def _create_lottery(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    if not scheduler:
        await create_lottery_cmd.finish("未检测到 APScheduler 插件，无法创建定时任务！")

    text = args.extract_plain_text().strip()
    if not text:
        await create_lottery_cmd.finish("格式错误！请输入：/定时抽奖 项目名称 3h/10min/99s后或/定时抽奖 项目名称 2026-5-20T18-25-00(可省略年月或分秒)")

    parts = text.split()
    if len(parts) < 2:
        await create_lottery_cmd.finish("格式错误！请确保项目名称与时间之间有空格隔开。")

    time_str = parts[-1]
    name = " ".join(parts[:-1])

    target_time = parse_target_time(time_str)
    if not target_time:
        await create_lottery_cmd.finish("时间格式解析失败！支持格式如：3h后, 30min后, 2026-5-21T18-25-00, 21T18-25 等")

    if target_time <= datetime.now():
        await create_lottery_cmd.finish(f"你想穿越回{target_time.strftime('%Y-%m-%dT%H:%M:%S')}吗？设定的时间必须在未来！")

    # 生成唯一的抽奖 ID
    lid = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')+event.get_user_id()+target_time.strftime('%Y-%m-%dT%H:%M:%S')
    group_id = event.group_id

    # 初始化字典
    if group_id not in lotteries:
        lotteries[group_id] = {}

    lotteries[group_id][lid] = {
        "name": name,
        "setter": event.get_user_id(),
        "time": target_time,
        "participants": {}
    }

    # 添加至定时任务
    scheduler.add_job(
        execute_lottery,
        "date",
        run_date=target_time,
        args=(bot, group_id, lid),
        id=f"lottery_{lid}"
    )

    await create_lottery_cmd.finish(
        f"已成功创建抽奖项目【{name}】\n开奖时间：{target_time.strftime('%Y-%m-%d %H:%M:%S')}\n群友发送 /报名 即可参与！")


join_lottery_cmd = on_command("报名", priority=5, block=True)


@join_lottery_cmd.handle()
async def _join_lottery_check(matcher: Matcher, event: GroupMessageEvent, state: T_State, args: Message = CommandArg()):
    group_id = event.group_id
    if group_id not in lotteries or not lotteries[group_id]:
        await matcher.finish("哎呀，当前群内没有正在进行的定时抽奖项目哇")

    group_lots = lotteries[group_id]
    arg_text = args.extract_plain_text().strip().upper()

    # 情况 1：如果当前只有一个抽奖项目，直接报名并反馈
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

    # 情况 2：如果有多个项目
    else:
        mapping = {}
        msg = "发现有现在多个抽奖项目：\n"
        for i, (lid, ldata) in enumerate(group_lots.items()):
            char_key = chr(65 + i)  # A, B, C...
            mapping[char_key] = lid
            msg += f"第{char_key}条：{ldata['name']}\n"

        state['mapping'] = mapping

        # 如果用户直接携带了参数 (如 /报名 AB)，跳过等待，传递给 got 处理
        if arg_text:
            matcher.set_arg("choices", args)
        else:
            msg += "请直接回复你想报名的项目对应字母（例如 \"A\"，报多个请回复如 \"AB\"）"
            await matcher.send(msg)


@join_lottery_cmd.got("choices")
async def _process_choices(matcher: Matcher, event: GroupMessageEvent, state: T_State,
                           choices: str = ArgPlainText("choices")):
    mapping = state.get('mapping')
    if not mapping:
        # 如果由于某种原因状态丢失，直接退出
        return

    choices = list(choices.strip().upper())
    joined = []
    already = []
    invalid = True

    # 遍历用户发送的所有字母
    for char in choices:
        if char in mapping:
            invalid = False
            choices.remove(char)
            lid = mapping[char]

            # 如果这期间抽奖已经结束被清理了，防止报错
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

    if invalid:
        await matcher.reject("无效的选择，请重新回复你想报名的项目字母。")

    res_msg = ""
    if joined:
        res_msg += f"成功报名：{', '.join(joined)}\n"
    if already:
        res_msg += f"已报名过：{', '.join(already)}"
    if choices:
        res_msg += f"并不存在：{', '.join(choices)}"

    await matcher.finish(res_msg.strip())

def At(data: str) -> Union[list[str], list[int], list]:
    """
    检测at了谁，返回[qq, qq, qq,...]
    包含全体成员直接返回['all']
    如果没有at任何人，返回[]
    :param data: event.json()  event: GroupMessageEvent
    :return: list
    """
    try:
        qq_list = []
        data = json.loads(data)
        for msg in data['message']:
            if msg['type'] == 'at':
                if 'all' not in str(msg):
                    qq_list.append(int(msg['data']['qq']))
                else:
                    return ['all']
        return qq_list
    except KeyError:
        return []

instant_lottery_cmd = on_command("抽奖", priority=5, block=True)


@instant_lottery_cmd.handle()
async def _instant_lottery_check(matcher: Matcher, event: GroupMessageEvent, state: T_State):
    participants = At(event.json())
    if not participants:
        msg = f"你没有选择任何候选人！语法：/抽奖@a@b@c"
    else:
        winner_id = random.choice(participants)
        msg = Message([
            MessageSegment.text(f"🎉 开奖啦！\n恭喜 "),
            MessageSegment.at(winner_id),
            MessageSegment.text(f" ({winner_id})赢得了本次抽奖")
        ])

    try:
        await instant_lottery_cmd.send(message=msg)
    except ActionFailed:
        logger.error(f"群 {event.group_id} 发送抽奖结果失败")