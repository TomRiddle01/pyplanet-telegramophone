from pyplanet.apps.config import AppConfig
from pyplanet.apps.core.trackmania import callbacks as tm_signals
from pyplanet.apps.core.maniaplanet import callbacks as mp_signals

from pyplanet.contrib.setting import Setting

import asyncio

import telegram
from queue import Queue
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
import re


class TelegramophoneApp(AppConfig):
    game_dependencies = []
    mode_dependencies = []
    app_dependencies = ['core.maniaplanet']

    bot = None
    updater = None
    chat_id = None
    active = False

    chat_queue = Queue()
    supported_commands = ["//skip", "//mute", "//unmute", "//kick", "//ban", "//unban", "//mx", "reboot", "//setpassword", "//setspecpassword", "chat", "writemaplist", "//restart", "//mxpack", "/version"]


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

        self.setting_admins = Setting(
            'admins', 'Telegram Admin Usernames', Setting.CAT_KEYS, type=str,
            description='Comma-separated list of admins (telegram usernames). Adding =playerlogin associates the user to an ingame user and enables admin commands.',
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

        await self.context.setting.register(self.setting_bot_key, self.setting_target_chat, self.setting_admins)

        mp_signals.player.server_chat.register(self.on_server_chat)
        mp_signals.player.player_chat.register(self.on_chat)
        mp_signals.player.player_connect.register(self.on_connect)
        mp_signals.player.player_disconnect.register(self.on_disconnect)
        mp_signals.map.map_start.register(self.on_map_start)

        await self.reload_settings(None)

        asyncio.ensure_future(self.telegram_receive_loop())
        asyncio.ensure_future(self.chat_queue_loop())
        print("running on")

    async def get_current_player_list(self):
        if len(self.instance.player_manager.online)==0:
            return "No players online"

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
            self.updater = Updater(key, use_context=True)
            self.active = True

        setting_admins = await self.setting_admins.get_value(refresh=True) or ""
        admin_tuples = [u.strip().split("=") for u in setting_admins.split(",")]
        self.admins = list()
        for t in admin_tuples:
            if len(t) == 2:
                self.admins.append({"telegram_user": t[0].strip(" "), "playerlogin": t[1].strip(" ")})
            elif len(t) == 1:
                self.admins.append({"telegram_user": t[0].strip(" "), "playerlogin": ""})


    async def send_event_msg(self, event):
        message = f"[Event] {event}"
        await self.send_message(message)


    async def on_connect(self, player, **kwargs):
        if not self.active:
            return
        message = f"[{self.get_player_name(player)}] joined the server."
        await self.send_message(message)
        message = await self.get_current_player_list()
        await self.send_message(message)


    async def on_disconnect(self, player, **kwargs):
        if not self.active:
            return
        message = f"[{self.get_player_name(player)}] left the server."
        await self.send_message(message)
        message = await self.get_current_player_list()
        await self.send_message(message)

    async def on_chat(self, player, text, cmd, **kwargs):
        if not self.active:
            return
        message = f"[{self.get_player_name(player)}] {text}"
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

    async def chat_queue_loop(self):
        while True:
            i = 0
            try:
                while not self.chat_queue.empty() and i < 20:
                    i+=1
                    telegram_user, msg = self.chat_queue.get()

                    if msg.startswith("/"):
                        base_command =  msg.split(" ")[0]
                        if base_command in self.supported_commands:
                            playerlogin = await self.telegram_user_to_playerlogin(telegram_user)
                            if playerlogin:
                                player = await self.instance.player_manager.get_player(playerlogin)
                                await self.instance.command_manager._on_chat(player, msg, True)
                        else:
                            self.bot.send_message(self.chat_id, "Command not supported")
                    else:
                        playerlogin = await self.telegram_user_to_playerlogin(telegram_user)
                        if playerlogin:
                            player = await self.instance.player_manager.get_player(playerlogin)
                            await self.instance.chat(f"[{player.nickname}] {msg}")
                        else:
                            await self.instance.chat(f"[Admin] {msg}")
            except Exception as e:
                # for player not found.
                print(e)
                pass

            await asyncio.sleep(1)


    async def telegram_receive_loop(self):
        dp = self.updater.dispatcher

        dp.add_handler(MessageHandler(Filters.text, self.receive_message))
        dp.add_error_handler(self.error)

        print("initialized telegram listener")
        self.updater.start_polling()

    def receive_message(self, update, context):

        # test loopback
        # update.message.chat.send_message(update.message.text)

        if str(update.message.chat_id) == self.chat_id:
            if not update.message.from_user.is_bot:
                username = update.message.from_user.username
                is_admin = self.is_admin(username)
                if is_admin:
                    self.chat_queue.put((username, update.message.text))
                    if not update.message.text.startswith("/"):
                        update.message.delete()
                
        else:
            print(f"Ignoring Message from Chat {update.message.chat_id}")

    def is_admin(self, telegram_user):
        for admin in self.admins:
            if admin["telegram_user"] == telegram_user:
                return True
        return False

    async def telegram_user_to_playerlogin(self, telegram_user):
        for admin in self.admins:
            if admin["telegram_user"] == telegram_user:
                return admin["playerlogin"]
        return None


    def error(self, update, context):
        print('Update "%s" caused error "%s"', update, context.error)
