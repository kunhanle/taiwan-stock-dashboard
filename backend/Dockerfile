
# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Copy the frontend directory to /frontend (sibling of /app)
COPY frontend /frontend

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container at /app
COPY backend/requirements.txt /app/

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the backend directory contents into the container at /app
COPY backend /app

# Make port 8050 available to the world outside this container
EXPOSE 8050

# Define environment variable
ENV PORT=8050

# Run main.py when the container launches
CMD ["python", "main.py"]
