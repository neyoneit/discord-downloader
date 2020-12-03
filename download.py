#!/usr/bin/env python3
import datetime
import os
import re
import sys
import traceback
import urllib
import urllib.parse

import discord
from discord import Message, Attachment
from discord.abc import Messageable
from discord.iterators import HistoryIterator
from pathvalidate import sanitize_filename

from movers import RenamingMover
from settings import DISCORD_TOKEN, CHANNELS, STATE_DIRECTORY, ATTACHMENTS_DIRECTORY, URLS_FILE, TEMP_DIRECTORY


def extract_urls(msg):
    return re.findall(r'(https?://[^\s]+)', msg)


class DownloaderClient(discord.Client):

    async def on_ready(self):
        self.ret = 0
        try:
            try:
                await self.download_news()
            finally:
                await self.logout()
        except Exception as e:
            self.ret = 1
            traceback.print_exc(file=sys.stderr)

    async def download_news(self):
        print("Connected")
        channels = {}

        for channel in self.get_all_channels():
            if hasattr(channel, "history") and hasattr(channel, "name") and hasattr(channel, "guild"):
                name = f"{channel.guild}--{channel.name}"
                if channels.get(name) is not None:
                    raise Exception(f"Multiple channels for name {name}")
                channels[name] = channel
        missing = CHANNELS - channels.keys()
        if len(missing) > 0:
            raise Exception(f"Some channels were not found: {missing}")

        print("Checking individual channels")
        channel: Messageable
        for name, channel in channels.items():
            if name in CHANNELS:
                print(f"## {name}")
                await self.download_channel(name, channel)

        print("Everything done")

    async def download_channel(self, name: str, channel: Messageable):
        savepoint = Savepoint(os.path.join(STATE_DIRECTORY, urllib.parse.quote(name)+".txt"))
        mover = RenamingMover()
        last_processed_message_id = savepoint.get()  # messages have increasing ids; we can use it to mark what messages we have seen
        history: HistoryIterator = channel.history(
            limit=None,
            oldest_first=True,
            after=None if last_processed_message_id is None else discord.Object(last_processed_message_id)
        )
        with open(URLS_FILE, "a") as urls_file:
            def before_sync():
                print("Syncing… ", end="")
                urls_file.flush()
                os.fsync(urls_file.fileno())

            def after_sync():
                print("Done")

            message: Message
            async for message in history:
                print(f"#{message.id} {message.created_at}: {message.content}")
                urls = extract_urls(message.content)
                if len(urls) > 0:
                    for url in urls:
                        urls_file.write(url)
                        urls_file.write("\n")

                attachment: Attachment
                for i, attachment in enumerate(message.attachments):
                    tmp_file = os.path.join(TEMP_DIRECTORY, f"{message.id}-{attachment.id}-{i}-{os.getpid()}")
                    out_file = os.path.join(
                        ATTACHMENTS_DIRECTORY,
                        sanitize_filename(attachment.filename, replacement_text='-')
                    )
                    with open(tmp_file, mode="wb") as f:
                        await attachment.save(f)
                        f.flush()
                        os.fsync(f.fileno())
                    mover.move(tmp_file, out_file)
                    print(f"* {attachment}")
                savepoint.set(message.id, before_sync=before_sync, after_sync=after_sync)  # mark as done
        savepoint.close()


def noop():
    pass


class Savepoint:

    def __init__(self, filename):
        self.filename = filename
        try:
            with open(filename) as f:
                s = f.read().strip()
                self.value = None if s == "None" else int(s)
        except FileNotFoundError:
            self.value = None
        self.last_synced = datetime.datetime.now()

    def get(self):
        return self.value

    def set(self, new_value: int, before_sync=noop, after_sync=noop):
        self.value = new_value
        now = datetime.datetime.now()
        if (now-self.last_synced) > datetime.timedelta(seconds=1):
            before_sync()
            self.flush()
            self.last_synced = now
            after_sync()

    def flush(self):
        tmp_filename = f"{self.filename}.tmp"
        with open(tmp_filename, "w") as f:
            f.write(str(self.value))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_filename, self.filename)

    def close(self):
        self.flush()


def main():
    print("Connecting…")
    client = DownloaderClient()
    client.run(DISCORD_TOKEN)
    sys.exit(client.ret)


if __name__ == "__main__":
    main()