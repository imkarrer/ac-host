FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY bot.py steam_parse.py car_skins.py players.py /app/
CMD ["python", "-u", "/app/bot.py"]
