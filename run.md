# Cyber Fraud Shield - End-to-End Testing Guide

This guide outlines how to boot up the entire platform and test each individual portal independently using Docker.

### 🚀 Prerequisites (Running the Backend)
Before testing any of the portals below, you must ensure the core backend infrastructure (Kong API Gateway, Postgres, Redis, Kafka, Auth, and Microservices) is running.
Open a terminal in the root directory and run:
```bash
docker compose up -d
```
Wait about 30 seconds for the containers to fully start before proceeding with the steps below.

> **🔒 AUTHENTICATION NOTE:** To test the application properly, you must first register an account on the `/register` page using the dummy credentials below. Ensure you select the correct **Role** from the dropdown during registration to be granted the correct permissions!

---

## 1. Citizen Portal
This is the public-facing portal where victims report fraud.

- **How to Start the UI (via Docker):**
  ```bash
  docker run -d --name citizen-ui -p 5173:5173 -v $(pwd):/app -w /app/frontend/citizen node:22 sh -c "npm install && npm run dev -- --host"
  ```
- **Access URL:** `http://localhost:5173`
- **Role:** `CITIZEN`
- **Dummy Registration Credentials:**
  - **Email:** `demo.citizen@example.com`
  - **Password:** `Password123!`
  - **Phone:** `+919876543210`

### 🧪 What to Check
1. Go to `http://localhost:5173/register` and click **Create Account**.
2. Register using the dummy credentials and select **CITIZEN** role.
3. Sign in with the registered credentials.
4. Go to **Report Fraud**.
5. Fill out a dummy fraud report (e.g., "Someone called asking for my UPI pin, here is their phone number").
6. Submit the report and copy the generated **Tracking ID**.
7. Go to **Track Status**, enter your tracking ID, and verify you can see the pending status of your report.

---

## 2. Investigator Dashboard
This is the internal dashboard used by law enforcement to triage, review AI verdicts, and authorize actions.

- **How to Start the UI (via Docker):**
  ```bash
  docker run -d --name investigator-ui -p 5177:5177 -v $(pwd):/app -w /app/frontend/investigator node:22 sh -c "npm install && npm run dev -- --host"
  ```
- **Access URL:** `http://localhost:5177`
- **Role:** `INVESTIGATOR`
- **Dummy Registration Credentials:**
  - **Email:** `demo.investigator@mha.gov.in`
  - **Password:** `Password123!`
  - **Phone:** `+919876543211`

### 🧪 What to Check
1. Go to `http://localhost:5177/register` and click **Create Account**.
2. Register using the dummy credentials and select **INVESTIGATOR** role.
3. Sign in with the registered credentials.
4. Look at the **Live Case Queue** on the homepage. You should instantly see the case you just submitted as a Citizen appear in the queue without needing to refresh the page (powered by Server-Sent Events).
5. Click on the newly reported case to open the **Case Details**.
6. Verify you can see the **AI Verdict**, the **Entity Linkage Graph**, and the **Geospatial Heatmap**.
7. Use the **Human-in-the-Loop** panel to click **Approve** or **Reject**, fill in a justification, and submit.
8. Click the **Intelligence Package** button to verify it successfully requests a PDF report.

---

## 3. Bank Official Portal
This is the dashboard used by banking officials to review and comply with law enforcement freeze requests.

- **How to Start the UI (via Docker):**
  ```bash
  docker run -d --name bank-ui -p 5175:5175 -v $(pwd):/app -w /app/frontend/bank node:22 sh -c "npm install && npm run dev -- --host"
  ```
- **Access URL:** `http://localhost:5175`
- **Role:** `BANK_OFFICIAL`

### 🧪 What to Check
1. Open the URL. The dashboard should render immediately.
2. Verify you see a list of **Flagged Transactions / Accounts** that require freezing (these are propagated when an investigator approves a case).
3. Click into a transaction graph to visualize the suspicious mule accounts.
4. Click the **Freeze Account** button to simulate banking compliance.

---

## 4. Telecom Admin Portal
This is the dashboard used by telecom operators (Jio, Airtel) to block fraudulent phone numbers and IMEI devices in real-time.

- **How to Start the UI (via Docker):**
  ```bash
  docker run -d --name telecom-ui -p 5174:5174 -v $(pwd):/app -w /app/frontend/telecom node:22 sh -c "npm install && npm run dev -- --host"
  ```
- **Access URL:** `http://localhost:5174`
- **Role:** `TELECOM_ADMIN`

### 🧪 What to Check
1. Open the URL. The dashboard should render immediately.
2. Verify you see incoming **Real-Time Webhook Alerts** dictating which fraudulent phone numbers (flagged in the Citizen report) need to be blocked.
3. Click the **Block Number** action and ensure the UI reflects that the number is successfully blacklisted.

---

## 5. Government / MHA Admin Dashboard
This is the overarching national dashboard used by NCRB and MHA directors to view macro-level threats, incoming alerts, and intelligence packages.

- **How to Start the UI (via Docker):**
  ```bash
  docker run -d --name gov-ui -p 5176:5176 -v $(pwd):/app -w /app/frontend/gov-mha node:22 sh -c "npm install && npm run dev -- --host"
  ```
- **Access URL:** `http://localhost:5176`
- **Role:** `GOV_OFFICIAL`
- **Dummy Registration Credentials:**
  - **Email:** `director.mha@gov.in`
  - **Password:** `AdminSecure123!`
  - **Phone:** `+911123456789`
  - **Jurisdiction ID:** `JUR-MHA-01`

### 🧪 What to Check
1. Go to `http://localhost:5176/register` and click **Create Account**.
2. Register using the dummy credentials and ensure you select the **GOV_OFFICIAL** role from the dropdown. Enter a jurisdiction ID (e.g., `JUR-MHA-01`).
3. Sign in with the credentials at `http://localhost:5176/login`.
4. On the homepage, you will see two tabs: **Live MHA Alerts** and **Intelligence Packages**.
5. Ensure the **Live MHA Alerts** tab is receiving real-time SSE notifications for critical tiered cases (e.g., "FRAUD_RING_DETECTED").
6. Click on the **Intelligence Packages** tab to view generated PDF reports (these are created when Investigators click "Generate Intelligence Package" on their dashboard). You should see download links for each report.
