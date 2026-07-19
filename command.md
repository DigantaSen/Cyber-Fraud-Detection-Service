# Functional Test Execution Commands

Here are the commands to manually start and test your complete vertical slice as requested. 

**Important:** Open a new terminal window/tab for each service since they need to run concurrently. All commands assume you are starting from the root directory of the project (`Cyber-Fraud-Detection-Service`).

---

## 1. Start Infrastructure Dependencies
Run this once to start the required databases in Docker.

```bash
docker compose up -d postgres redis
```

---

## 2. Start Backend Services (Run locally)

### Auth Service (Port 8010)
```bash
cd backend/auth
source ../../venv/bin/activate
uvicorn main:app --reload --port 8010
```

### Case Service (Port 8011)
```bash
cd backend/case
source ../../venv/bin/activate
uvicorn main:app --reload --port 8011
```

### Bot Service (Port 8012)
```bash
cd backend/bot
source ../../venv/bin/activate
uvicorn main:app --reload --port 8012
```

### Citizen BFF (Port 8013)
```bash
cd backend/citizen-bff
source ../../venv/bin/activate
# Ensure your .env points to the custom ports you set above for Auth, Case, and Bot!
uvicorn main:app --reload --port 8013
```

---

## 3. Start Frontend Applications

### Citizen UI (Port 5173)
```bash
cd frontend
npm run dev:citizen
```

### Telecom UI (Port 5174)
```bash
cd frontend
npm run dev:telecom
```

### Bank UI (Port 5175)
```bash
cd frontend
npm run dev:bank
```

---

## 4. Run Automated Tests

### Backend Tests
```bash
# Auth Service
cd backend/auth
source ../../venv/bin/activate
pytest

# Case Service
cd ../case
source ../../venv/bin/activate
pytest

# Bot Service
cd ../bot
source ../../venv/bin/activate
pytest

# Citizen BFF
cd ../citizen-bff
source ../../venv/bin/activate
pytest
```

### Frontend Tests
```bash
cd frontend
npm run test:citizen
npm run test:telecom
npm run test:bank
```

---

## Configuration Checklist Before Starting:
1. Ensure your backend `.env` files point to `localhost` for `POSTGRES_HOST` and `REDIS_HOST`.
2. Ensure `Citizen BFF` is configured to communicate with the Auth, Case, and Bot services on their new custom ports (`8010`, `8011`, `8012`).
3. Ensure the Frontend `.env` files point to the BFF running on `8013`.
