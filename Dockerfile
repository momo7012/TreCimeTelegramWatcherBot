FROM mcr.microsoft.com/playwright/python:v1.54.0-noble

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY tre_cime_bot.py .

CMD ["python", "-u", "tre_cime_bot.py"]
