FROM python:3.12-slim
WORKDIR /app
COPY auth.py details.py plugin.py push_status.py /app/
EXPOSE 18080
CMD ["python", "-u", "/app/auth.py"]
