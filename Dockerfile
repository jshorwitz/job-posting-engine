FROM python:3.11-slim

# Install Doppler CLI
RUN apt-get update && apt-get install -y curl gnupg && \
    curl -sLf --retry 3 --tlsv1.2 --proto "=https" \
      'https://packages.doppler.com/public/cli/gpg.DE2A7741A397C129.key' | \
      gpg --dearmor -o /usr/share/keyrings/doppler-archive-keyring.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/doppler-archive-keyring.gpg] https://packages.doppler.com/public/cli/deb/debian any-version main" \
      > /etc/apt/sources.list.d/doppler-cli.list && \
    apt-get update && apt-get install -y doppler && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home appuser
WORKDIR /home/appuser/app

COPY pyproject.toml .

# Install dependencies only (no project install yet — source not copied)
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir \
      httpx>=0.27.0 sqlalchemy>=2.0.0 openai>=1.30.0 \
      pydantic-settings>=2.1.0 python-dotenv>=1.0.1 \
      playwright>=1.49.0 requests-oauthlib>=2.0.0 \
      requests>=2.32.0 google-genai>=1.0.0

COPY engine/ ./engine/
COPY scripts/ ./scripts/

# Now install the project (source is available for hatchling)
RUN pip install --no-cache-dir .

RUN mkdir -p data logs && chown -R appuser:appuser /home/appuser/app

USER appuser

# Default: enrichment pipeline (overridden per Railway service)
# X scheduler service uses: doppler run -- python scripts/x_scheduler.py
CMD ["doppler", "run", "--", "python", "-m", "engine.pipeline", "--enrich", "--export", "loops"]
