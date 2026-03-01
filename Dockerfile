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
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir .

COPY engine/ ./engine/

RUN mkdir -p data logs && chown -R appuser:appuser /home/appuser/app

USER appuser

# Doppler injects all secrets at runtime via DOPPLER_TOKEN env var.
# Run enrichment + Loops export (enrolls new leads), then drip (sends due emails).
COPY scripts/ ./scripts/
CMD ["doppler", "run", "--", "sh", "scripts/cron-run.sh"]
