# Docker Workflow Cheat Sheet

This document contains the everyday Docker Compose commands you will need for this hackathon project. 
**Note:** You do not need to run `setup.ps1` anymore unless you completely destroy your environment.

## 1. Starting and Stopping (Everyday Use)

* **Start the system:**
  ```bash
  docker compose up -d
  ```
  *(The `-d` flag runs it in the background so it doesn't lock up your terminal. It will only start containers that aren't already running).*

* **Pause the system (saves CPU/RAM when you take a break):**
  ```bash
  docker compose stop
  ```
  *(This stops the containers but preserves everything exactly as it is).*

## 2. Pushing Code Updates (Important!)

Because your Python code is baked into the Docker images (we didn't use live-reload volume mounts for the backend to keep it production-accurate), **you must rebuild a container when you change its code.**

* **Apply code changes to a specific service:**
  ```bash
  docker compose up -d --build event-processing
  ```
  *(This takes advantage of the `.dockerignore` file, so it rebuilds the container in under a second and swaps it out without restarting your databases).*

* **Restart a service (if it crashed or you changed an environment variable):**
  ```bash
  docker compose restart kong
  ```

## 3. Debugging & Logs

* **Watch live logs for a specific service:**
  ```bash
  docker compose logs -f event-processing
  ```
  *(The `-f` flag means "follow". It will stream new logs to your terminal in real-time. Press `Ctrl+C` to exit).*

* **Check the health of all containers:**
  ```bash
  docker compose ps
  ```
  *(This shows you which containers are running, which are `(healthy)`, and which are `(unhealthy)`).*

* **Open a terminal inside a running container (like SSH):**
  ```bash
  docker exec -it platform-postgres bash
  ```
  *(Useful if you need to run CLI tools like `psql` or `redis-cli` from inside the network).*

## 4. The "Nuclear Option" (Resetting)

* **Destroy everything but keep your databases safe:**
  ```bash
  docker compose down
  ```

* **Destroy EVERYTHING (Wipe all databases, clear all queues, reset to factory zero):**
  ```bash
  docker compose down -v
  ```
  *(⚠️ **WARNING:** The `-v` flag deletes all Docker volumes. If you run this, you **must** run `setup.ps1` again to recreate your databases, Kong routes, and MinIO buckets!).*
