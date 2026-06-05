import random
import re
from collections import defaultdict
from datetime import datetime, timedelta

from nonebot.adapters.onebot.v11 import ActionFailed, Bot, Message, MessageSegment
from nonebot.log import logger


# lotteries[group_id][lottery_id] = {"name": str, "time": datetime, "participants": {}}
lotteries = defaultdict(dict)


def parse_target_time(time_str: str) -> datetime | None:
    now = datetime.now()

    rel_match = re.match(r"^(\d+)(h|min|s)后$", time_str)
    if rel_match:
        val = int(rel_match.group(1))
        unit = rel_match.group(2)
        if unit == "h":
            return now + timedelta(hours=val)
        if unit == "min":
            return now + timedelta(minutes=val)
        if unit == "s":
            return now + timedelta(seconds=val)

    if "T" not in time_str:
        return None

    date_part, time_part = time_str.split("T", 1)

    year, month, day = now.year, now.month, now.day
    if date_part:
        d_splits = date_part.split("-")
        if len(d_splits) == 3:
            year, month, day = map(int, d_splits)
        elif len(d_splits) == 2:
            month, day = map(int, d_splits)
        elif len(d_splits) == 1:
            day = int(d_splits[0])

    hour, minute, second = 0, 0, 0
    if time_part:
        t_splits = time_part.split("-")
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

        msg = Message(
            [
                MessageSegment.text(f"🎉 定时抽奖【{name}】开奖啦！\n恭喜 "),
                MessageSegment.at(winner_qq),
                MessageSegment.text(f" ({winner_name} / {winner_qq}) 成为鼠鼠的幸运儿！"),
            ]
        )

    try:
        await bot.send_group_msg(group_id=group_id, message=msg)
    except ActionFailed:
        logger.error(f"群 {group_id} 发送抽奖结果失败")
