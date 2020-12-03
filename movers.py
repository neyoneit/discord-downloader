import os
import re


class RenamingMover:

    SPLIT = re.compile("""^(.*)(\\.[^/.\\\\]*)$""")

    def move(self, src, dest):
        if not self._move(src, dest, None):
            i = 1
            while not self._move(src, dest, i):
                i = i+1

    def _move(self, src, dest, i):
        real_dest = (dest if i is None else RenamingMover._adjust_name(dest, i))
        # This is a bit racy, but we don't seem to have a better way for *NIX.
        # On Windows, this condition is not critical, because we can handle FileExistsError.
        if os.path.exists(real_dest):
            return False
        try:
            os.rename(src, real_dest)
            return True
        except FileExistsError as e:
            # This can happen only on Windows.
            # Most likely, such situations are going to be caught by os.path.exists, so this can happen only in case of race conditions.
            return False

    @staticmethod
    def _adjust_name(dest, i):
        match = RenamingMover.SPLIT.match(dest)
        [dest_prefix, dest_suffix] = match.groups() if match else [dest, ""]
        return f"{dest_prefix}.{i}{dest_suffix}"
