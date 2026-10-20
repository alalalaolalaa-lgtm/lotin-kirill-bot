FROM python:3.10-slim

# Tizim paketlari, Tesseract OCR va shriftlarni o'rnatish
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-uzb \
    tesseract-ocr-uzb-cyrl \
    fontconfig \
    liberation-fonts \
    fonts-dejavu-core \
    && fc-cache -f -v \
    && rm -rf /var/lib/apt/lists/*

# Ishchi papkani belgilash
WORKDIR /app

# requirements.txt ni ko'chirib o'rnatish
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Qolgan barcha fayllarni ko'chirish
COPY . .

# Botni ishga tushirish
CMD ["python", "main.py"]
