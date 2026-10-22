"""Import every ac-host service module and its libraries; print the versions.

Used to test run-mode images where the code is bind-mounted, not packaged.
"""
import discord, numpy, scipy.signal, PIL.Image, aiohttp
import auth, details, plugin, bot, skin_livery, skin_uv

print("check ok: numpy", numpy.__version__, "scipy", scipy.__version__,
      "Pillow", PIL.__version__, "discord.py", discord.__version__)
