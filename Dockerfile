FROM node:24-bookworm-slim AS dashboard
WORKDIR /build/fimi-dashboard
COPY fimi-dashboard/package.json fimi-dashboard/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY fimi-dashboard/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 DEMO_HOST=0.0.0.0 PORT=10000
WORKDIR /app
RUN pip install --no-cache-dir c2pa-python==0.38.0
COPY ANTI_FIMI/*.py ANTI_FIMI/*.json ANTI_FIMI/*.html ./ANTI_FIMI/
COPY ANTI_FIMI_운용표_v1.0.xlsx deploy_demo.py ./
COPY --from=dashboard /build/fimi-dashboard/dist ./fimi-dashboard/dist
USER 10001:10001
EXPOSE 10000
CMD ["python", "deploy_demo.py"]
