# Run Citizen Portal
To run the Citizen portal, you need to start the underlying infrastructure, the relevant backend services, and the Citizen frontend UI. Follow these steps, opening a new terminal window or tab for each service.

All commands assume you are running them from the root directory of the project.

---

## 1. Start Infrastructure Dependencies
The backend services require Postgres and Redis to be running.
```bash
docker compose up -d postgres redis
```

---

## 2. Start Backend Services
You need to run the Auth, Case, and Bot services as dependencies for the Citizen BFF.

### Auth Service
```bash
cd backend/auth
source ../../venv/bin/activate
uvicorn main:app --reload --port 8010
```

### Case Service
```bash
cd backend/case
source ../../venv/bin/activate
uvicorn main:app --reload --port 8011
```

### Bot Service
```bash
cd backend/bot
source ../../venv/bin/activate
uvicorn main:app --reload --port 8012
```

### Citizen BFF (Backend For Frontend)
```bash
cd backend/citizen-bff
source ../../venv/bin/activate
uvicorn main:app --reload --port 8013
```

---

## 3. Start Citizen Frontend UI
Finally, start the Citizen frontend application.
```bash
cd frontend
npm install
npm run dev:citizen
```

The Citizen Portal will be accessible at: **http://localhost:5173**

---

### Useful Tips
- Make sure your `.env` files are configured correctly to point to these custom ports (8010, 8011, 8012, 8013).
- To stop the databases later, run `docker compose down` in the project root.
