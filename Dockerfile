FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY app ./app
RUN mkdir /data && chown 65532:65532 /data
USER 65532:65532
EXPOSE 8000
CMD ["python", "-m", "app.server"]
