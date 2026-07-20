# Cyber Fraud Detection Platform - Getting Started Guide

This guide explains how to start the entire Cyber Fraud Detection platform from scratch immediately after cloning the repository. It covers booting the backend microservices, provisioning data, and launching the frontend web applications.

---

## 1. Prerequisites

Before starting, ensure your local development environment has the following installed:
1. **Docker Desktop**: Must be running. Ensure you have allocated sufficient resources (at least 8GB RAM is recommended due to the number of microservices and ML models).
2. **Node.js** (v18+): Required for running the Vite/React frontends.
3. **Python 3.10+**: Required to run the local helper scripts (like generating demo accounts).
4. **PowerShell**: Required for running the setup script on Windows.

---

## 2. Boot the Backend Infrastructure

The backend consists of 14 microservices (Auth, Department BFFs, Case, ML Inference Orchestrator, etc.) and core infrastructure (Kong, Kafka, Postgres, Neo4j, Redis, OpenSearch).

1. Open a **PowerShell terminal** at the root of the cloned repository.
2. Run the automated setup script:
   ```powershell
   .\setup.ps1
   ```
   
**What `setup.ps1` does automatically:**
- Copies `.env.example` to `.env`. **(IMPORTANT: You must open the `.env` file and add your `GROQ_API_KEY` so the AI models can run!)**
- Runs `python generate_keys.py` to securely generate a valid RSA public/private keypair for JWT token signing and injects them into your `.env` file.
- Runs `python add_kong_consumers.py` to parse that new public key and inject it into the Kong Gateway configuration so Kong can successfully validate inbound tokens.
- Pulls and builds all Docker images via `docker compose up -d` (this may take a few minutes and download ~8GB of images).
- Waits up to 10 minutes for all 30+ containers to report a `healthy` state.
- Connects to the Kafka container to provision all required message topics (`citizen.report.created`, `fraud.alert.mha`, etc.).
- Verifies that OpenSearch is booted and ready to accept search indices.
- Runs `python create_demo_accounts.py` to automatically register the `TELECOM_ADMIN` and `BANK_OFFICIAL` test accounts in the Postgres database.

*(Do not proceed to step 3 until the script prints "Setup Complete!" and lists the URLs of the infrastructure dashboards).*

---

## 3. Run the UIs (Bank & Telecom)

Both the Bank and Telecom UIs are built with React and Vite. By default, they are configured to proxy all `/api` requests directly to `http://localhost:8000` (the Kong API Gateway). 

**No frontend `.env` files are required** for local development!

### 🟢 Start the Telecom Admin Portal

1. Open a new terminal and navigate to the Telecom frontend directory:
   ```powershell
   cd frontend/telecom
   ```
2. Install the Node.js dependencies:
   ```powershell
   npm install
   ```
3. Start the development server:
   ```powershell
   npm run dev
   ```
4. Open your browser to `http://localhost:5174`.
5. **Login Credentials:**
   - **Email:** `telecom.admin@fraud.gov.in`
   - **Password:** `Telecom@2024!`

### 🔵 Start the Bank Fraud Monitor

1. Open another new terminal and navigate to the Bank frontend directory:
   ```powershell
   cd frontend/bank
   ```
2. Install the Node.js dependencies:
   ```powershell
   npm install
   ```
3. Start the development server:
   ```powershell
   npm run dev
   ```
4. Open your browser to `http://localhost:5173`.
5. **Login Credentials:**
   - **Email:** `bank.officer@fraud.gov.in`
   - **Password:** `BankOff@2024!`

---

## 5. Explore the Features

Once logged in to both portals, you can verify the following features:

- **Real-time SSE:** Both portals automatically establish a Server-Sent Events (SSE) connection. If you trigger fraud events in the backend, they will appear in real-time.
- **Bank Blocking:** In the Bank Portal, click the "Block" button on any flagged transaction to instantly interdict it. The UI will reflect the `BLOCKED` status.
- **Secure Routing:** If your JWT token expires (or if you click "Sign Out" in the top right), you will be automatically routed back to the login screen.
