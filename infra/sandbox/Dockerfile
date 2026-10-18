FROM python:3.12-slim
WORKDIR /sandbox
COPY runner.py /sandbox/runner.py
USER 65532:65532
ENTRYPOINT ["python", "-I", "-S", "-u", "/sandbox/runner.py"]
