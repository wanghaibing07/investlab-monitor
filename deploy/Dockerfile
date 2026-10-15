FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 INVESTLAB_HOME=/var/lib/investlab
WORKDIR /opt/investlab
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --uid 10001 --create-home investlab && mkdir /var/lib/investlab && chown investlab /var/lib/investlab
USER 10001:10001
VOLUME ["/var/lib/investlab"]
ENTRYPOINT ["investlab"]
CMD ["doctor"]
