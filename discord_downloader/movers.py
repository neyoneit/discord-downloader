import filecmp
import itertools
import os
import re
from typing import Optional, Tuple


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


class DeduplicatingRenamingMover:

    SPLIT = re.compile("""^(.*)(\\.[^/.\\\\]*)$""")

    def move(self, src: str, dest: str) -> Tuple[str, bool]:
        """
        :param src:
        :param dest:
        :return: The adjusted filename + Whether the file was not actually created (i.e., not a duplicate).
        """
        for real_dest in self._moving_params(dest):
            # This is a bit racy, but we don't seem to have a better way for *NIX.
            # On Windows, this condition is not critical, because we can handle FileExistsError.
            if os.path.exists(real_dest):
                if filecmp.cmp(src, real_dest):
                    os.unlink(src)
                    return real_dest, False
            else:
                try:
                    os.rename(src, real_dest)
                    return real_dest, True
                except FileExistsError:
                    # This can happen only on Windows. Most likely, such situations are going to be caught by
                    # os.path.exists, so this can happen only in case of race conditions.
                    if filecmp.cmp(src, real_dest):
                        os.unlink(src)
                        return real_dest, False

        raise AssertionError(
            "You have successfully iterated over an infinite generator. You can feel like Chuck Norris. Enjoy!")

    @staticmethod
    def _moving_params(dest):
        return itertools.chain([dest], map(lambda i: DeduplicatingRenamingMover._adjust_name(dest, i), itertools.count(1)))

    @staticmethod
    def _adjust_name(dest, i):
        match = RenamingMover.SPLIT.match(dest)
        [dest_prefix, dest_suffix] = match.groups() if match else [dest, ""]
        return f"{dest_prefix}.{i}{dest_suffix}"
