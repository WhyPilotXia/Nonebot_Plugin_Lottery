from nonebot import get_plugin_config
from pydantic import BaseModel


class Config(BaseModel):
    notion_token: str # 如果环境变量没有配置将报错，必须配置notion_token=xxxx
    lottery_contact_data_source_id: str = "31e70d82-c716-8034-b23d-000ba20878af"


plugin_config = get_plugin_config(Config) # get_plugin_config(Config) 会从 NoneBot 的全局配置里读取 notion_token。
# NOTION_TOKEN = xxxx或notion_token = xxxx仍然会映射到plugin_config.notion_token
