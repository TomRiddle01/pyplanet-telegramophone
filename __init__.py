from pyplanet.apps.config import AppConfig
from pyplanet.apps.core.trackmania import callbacks as tm_signals
from pyplanet.apps.core.maniaplanet import callbacks as mp_signals

from pyplanet.contrib.setting import Setting

import asyncio

import telegram
import re


class TelegramophoneApp(AppConfig):
    game_dependencies = []
    mode_dependencies = []
    app_dependencies = ['core.maniaplanet']
    
    bot = None
    chat_id = None
    active = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.bot = None
        self.chat_id = None

        self.setting_bot_key = Setting(
            'bot_key', 'Telegram Bot Key', Setting.CAT_KEYS, type=str,
            description='Telegram Bot Key',
            default=None, change_target=self.reload_settings
        )

        self.setting_target_chat = Setting(
            'target_group', 'Telegram Target Group', Setting.CAT_KEYS, type=str,
            description='Telegram Target Group Key',
            default=None, change_target=self.reload_settings
        )

    async def on_init(self):
        await super().on_init()

    async def on_stop(self):
        await super().on_stop()

    async def on_destroy(self):
        await super().on_destroy()

    async def on_start(self):
        await super().on_start()

        await self.context.setting.register(self.setting_bot_key, self.setting_target_chat)

        mp_signals.player.server_chat.register(self.on_server_chat)
        mp_signals.player.player_chat.register(self.on_chat)
        mp_signals.player.player_connect.register(self.on_connect)
        mp_signals.player.player_disconnect.register(self.on_disconnect)
        mp_signals.map.map_start.register(self.on_map_start)

        await self.reload_settings(None)

    async def get_current_player_list(self):
        message = "Currently online:\n"
        for player in self.instance.player_manager.online:
            message += f"{self.remove_format(player.nickname)}\n"
        return message

    async def reload_settings(self, *args, **kwargs):
        self.active = False
        key = await self.setting_bot_key.get_value(refresh=True) or None
        self.chat_id = await self.setting_target_chat.get_value(refresh=True) or None
        if key and self.chat_id:
            self.bot = telegram.Bot(key)
            self.active = True

    async def on_connect(self, player, **kwargs):
        if not self.active:
            return
        message = f"[{self.get_player_name(player)}] joined the server.\n"
        message += await self.get_current_player_list()
        await self.send_message(message)


    async def on_disconnect(self, player, **kwargs):
        if not self.active:
            return
        message = f"[{self.get_player_name(player)}] left the server.\n"
        message += await self.get_current_player_list()
        await self.send_message(message)

    async def on_chat(self, player, text, cmd, **kwargs):
        if not self.active:
            return
        message = f"[{self.get_player_name(player)}]\n{text}"
        await self.send_message(message)


    async def on_server_chat(self, source, signal):
        if not self.active:
            return
        text = source["text"]
        cmd = source["cmd"]
        message = f"{self.remove_format(text)}"
        ignore = ["joined the server!", "left the server!"]

        for s in ignore:
            if s in message:
                return

        await self.send_message(message)

    async def on_map_start(self, map, **kwargs):
        if not self.active:
            return
        map_name = self.remove_format(map.name) if map.name is not None else ""
        author_login = self.remove_format(map.author_login) if map.author_login is not None else ""
        author_nick = self.remove_format(map.author_nickname) if map.author_nickname is not None else ""
        message = f"New Map: {map_name} by {author_nick} {author_login}"
        await self.send_message(message)


    def get_player_name(self, player):
        nickname = self.remove_format(player.nickname)
        login = player.login
        return f"{nickname} {login}"

    def remove_format(self, text):
        text = re.sub(r'\$[0-9a-fA-F]{3}', "", text)
        text = re.sub(r'\$h\[.*?((\$h)|(\]))', "", text)
        text = re.sub(r'\$l\[.*?((\$l)|(\]))', "", text)
        text = re.sub(r'\$.', "", text)
        return text

    async def send_message(self, message):
        try:
            self.bot.send_message(self.chat_id, message, disable_web_page_preview=True)
        except Exception as e:
            pass
