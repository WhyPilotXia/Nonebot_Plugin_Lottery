import os
import time
from nonebot import get_driver
from nonebot.log import logger
from notion_client import Client

driver = get_driver()

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