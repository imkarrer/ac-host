FROM python:3.12-slim
WORKDIR /app
COPY sidecar/auth.py sidecar/details.py sidecar/plugin.py sidecar/push_status.py /app/
COPY shared/downtime.py /app/downtime.py
COPY shared/server_health.py /app/server_health.py
EXPOSE 18080
CMD ["python", "-u", "/app/auth.py"]
