runserver:
	uv run uvicorn main:app --host 0.0.0.0 --port 8002

pytest:
	uv run pytest -v --tb=short --maxfail=5 --disable-warnings