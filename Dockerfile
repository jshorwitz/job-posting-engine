FROM python:3.11-slim

RUN useradd --create-home appuser
WORKDIR /home/appuser/app

COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir .

COPY engine/ ./engine/

RUN mkdir -p data logs && chown -R appuser:appuser /home/appuser/app

USER appuser

# Default: run the email outreach pipeline
# DRY_RUN, OUTREACH_CHANNEL, MAX_EMAILS_PER_RUN configured via env vars
CMD ["python", "-m", "engine.pipeline", "--channel", "email"]
