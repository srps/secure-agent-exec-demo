FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY runner_service.py /app/runner_service.py
EXPOSE 8080
CMD ["python", "/app/runner_service.py"]
