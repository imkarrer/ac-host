FROM python:3.12-slim
WORKDIR /app
# DejaVu is the font the race-number badge renders with; skin_livery.find_font
# refuses to fall back to Pillow's bitmap default because that would silently
# produce unreadable digits.
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*
COPY bot/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY bot/bot.py bot/steam_parse.py bot/car_skins.py bot/players.py bot/page_mirror.py bot/series_cmds.py bot/series_poll.py bot/series_poll_content.py /app/
COPY shared/downtime.py shared/series_lib.py shared/buildkite_trigger.py shared/atomic_json.py /app/
CMD ["python", "-u", "/app/bot.py"]
