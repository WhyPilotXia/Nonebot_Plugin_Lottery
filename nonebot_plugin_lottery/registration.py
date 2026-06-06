from collections import defaultdict
from datetime import datetime

from nonebot.adapters.onebot.v11 import ActionFailed, Bot, Message, MessageSegment
from nonebot.log import logger


# registrations[group_id][registration_id] = {
#     "name": str,
#     "setter": str,
#     "time": datetime,
#     "limit": int,
#     "participants": {},
#     "job_id": str,
# }
registrations = defaultdict(dict)


def format_participants(participants: dict[str, dict]) -> str:
    if not participants:
        return "暂无"

    lines = []
    for index, item in enumerate(participants.values(), start=1):
        qq = item["qq"]
        name = item.get("name", "")
        lines.append(f"{index}. {name} / {qq}" if name else f"{index}. {qq}")

    return "\n".join(lines)


async def close_registration(bot: Bot, group_id: int, rid: str, reason: str = "time"):
    if group_id not in registrations or rid not in registrations[group_id]:
        return

    rdata = registrations[group_id].pop(rid)

    if not registrations[group_id]:
        del registrations[group_id]

    name = rdata["name"]
    participants = rdata["participants"]
    limit = rdata["limit"]

    if reason == "full":
        title = f"【{name}】报名已满，报名关闭。"
    elif reason == "stop":
        title = f"【{name}】报名已由发起者停止。"
    else:
        title = f"【{name}】报名截止时间到，报名关闭。"

    msg = Message(
        [
            MessageSegment.text(
                f"{title}\n当前人数：{len(participants)}/{limit}\n报名名单：\n{format_participants(participants)}"
            )
        ]
    )

    try:
        await bot.send_group_msg(group_id=group_id, message=msg)
    except ActionFailed:
        logger.error(f"群 {group_id} 发送报名结果失败")


def make_registration_id(setter: str, target_time: datetime) -> str:
    return (
        datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        + setter
        + target_time.strftime("%Y-%m-%dT%H:%M:%S")
    )
