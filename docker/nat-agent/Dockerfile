FROM python:3.11-alpine

RUN apk add --no-cache iptables curl

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 8100

CMD ["python", "app.py"]
