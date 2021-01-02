from unittest import TestCase

from download import extract_urls


class UrlsTest(TestCase):

    def test_urls(self):
        self.assertEqual(extract_urls("""
            https://giphy.com/gifs/beamiller-miller-bea-jDONZD3qrOlyBFTkXU
                https://discord.com/channels/783750597902860349/783750597902860352
                https://discordpy.readthedocs.io/en/latest/discord.html
                https://discord.com/channels/783750597902860349/783763349028470805
                https://discordpy.readthedocs.io/en/latest/api.html#discord.Object
                https://en.wikipedia.org/wiki/Bitcoin#Austrian_economics_roots
                https://en.wikipedia.org/wiki/Adversary_(cryptography)
                https://discord.com/channels/783750597902860349/783750624709836850,
            """),
            [
                "https://giphy.com/gifs/beamiller-miller-bea-jDONZD3qrOlyBFTkXU",
                "https://discord.com/channels/783750597902860349/783750597902860352",
                "https://discordpy.readthedocs.io/en/latest/discord.html",
                "https://discord.com/channels/783750597902860349/783763349028470805",
                "https://discordpy.readthedocs.io/en/latest/api.html#discord.Object",
                "https://en.wikipedia.org/wiki/Bitcoin#Austrian_economics_roots",
                "https://en.wikipedia.org/wiki/Adversary_(cryptography)",
                "https://discord.com/channels/783750597902860349/783750624709836850,"
            ]
        )