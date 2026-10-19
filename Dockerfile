# This image ships Python and Chromium; the matching `playwright` package comes from pip.
# Keep the tag in sync with requirements.txt.
FROM mcr.microsoft.com/playwright/python:v1.64.0-noble

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 8000
CMD ["python", "app.py", "8000"]
