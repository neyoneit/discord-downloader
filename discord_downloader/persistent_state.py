import datetime
import json
import os

from discord_downloader.util import noop


class StoredState:

    def __init__(self, filename, default_value):
        self.filename = filename
        try:
            with open(filename) as f:
                self.value = json.load(f)
        except FileNotFoundError:
            self.value = default_value

    def flush(self):
        tmp_filename = f"{self.filename}.tmp"
        with open(tmp_filename, "w") as f:
            json.dump(self.value, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_filename, self.filename)

    def close(self):
        self.flush()


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
