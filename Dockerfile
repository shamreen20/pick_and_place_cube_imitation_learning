FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY zimmer_gripper_controller ./zimmer_gripper_controller
COPY app ./app

RUN pip install uv && uv pip install --system .

EXPOSE 8000
EXPOSE 9876

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]