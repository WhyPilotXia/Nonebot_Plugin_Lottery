import json
import time
from typing import Union

from nonebot.log import logger

from .config import plugin_config


notion = None

# QQ -> contact_id
qq_to_contact_id: dict[str, str] = {}

# contact_id -> contact_info
contact_id_to_info: dict[str, dict[str, str]] = {}


def is_notion_enabled() -> bool:
    return plugin_config.notion_enabled


def _get_notion_client():
    global notion

    if not plugin_config.notion_enabled:
        return None

    if notion is None:
        try:
            from notion_client import Client
        except ImportError as e:
            raise RuntimeError("已配置 notion_token，但未安装 notion-client,请在当前python环境执行 pip install notion-client>=2.2.0") from e

        notion = Client(auth=plugin_config.notion_token)

    return notion


def _read_property(prop: dict) -> str:
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


def _query_all_rows(data_source_id: str, page_size: int = 100) -> list[dict]:
    client = _get_notion_client()
    if client is None:
        return []

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
                resp = client.data_sources.query(**kwargs)
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


def get_contacts() -> list[dict[str, str]]:
    if not plugin_config.notion_enabled:
        return []

    rows = _query_all_rows(plugin_config.lottery_contact_data_source_id)
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


def refresh_contact_maps() -> dict[str, str]:
    global qq_to_contact_id, contact_id_to_info

    if not plugin_config.notion_enabled:
        qq_to_contact_id = {}
        contact_id_to_info = {}
        logger.info("未配置 notion_token，已使用 QQ 作为报名去重身份")
        return qq_to_contact_id

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

    logger.success(f"已刷新 Notion 联系人 QQ 映射，共 {len(qq_to_contact_id)} 个 QQ")
    return qq_to_contact_id


def get_contact_id_by_qq(qq: int | str) -> str | None:
    return qq_to_contact_id.get(str(qq))


def get_identity_by_qq(qq: int | str) -> str:
    qq = str(qq)
    contact_id = get_contact_id_by_qq(qq)

    if contact_id:
        return f"contact:{contact_id}"

    return f"qq:{qq}"


def get_display_name_by_identity(identity: str) -> str:
    if identity.startswith("contact:"):
        contact_id = identity.removeprefix("contact:")
        info = contact_id_to_info.get(contact_id, {})
        return info.get("姓名") or contact_id

    if identity.startswith("qq:"):
        return identity.removeprefix("qq:")

    return identity


def At(data: str) -> Union[list[str], list[int], list]:
    """
    检测 at 了谁，返回 [qq, qq, qq, ...]。
    包含全体成员直接返回 ['all']，没有 at 任何人返回 []。
    """
    try:
        qq_list = []
        data = json.loads(data)
        for msg in data["message"]:
            if msg["type"] == "at":
                if "all" not in str(msg):
                    qq_list.append(int(msg["data"]["qq"]))
                else:
                    return ["all"]
        return qq_list
    except KeyError:
        return []
