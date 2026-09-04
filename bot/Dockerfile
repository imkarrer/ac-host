FROM python:3.12-slim
WORKDIR /app
COPY bot/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY bot/bot.py bot/steam_parse.py bot/car_skins.py bot/players.py bot/page_mirror.py /app/
COPY shared/downtime.py /app/downtime.py
CMD ["python", "-u", "/app/bot.py"]
