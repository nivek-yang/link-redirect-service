FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Install uv
RUN pip install uv

# Copy only the dependency files to leverage Docker cache
COPY pyproject.toml uv.lock ./

# Install project dependencies
RUN uv sync --system

# Copy the rest of the application code
COPY . .

# Command to run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
