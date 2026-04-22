FROM python:3.11-slim

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Install the ccf package (src/ccf) so the CLI tool and imports work cleanly
RUN pip install --no-cache-dir -e .

# Persistent storage for chain files and summaries
VOLUME ["/app/chains", "/app/summaries"]

EXPOSE 7331

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
