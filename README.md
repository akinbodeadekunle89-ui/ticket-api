# 🎫 Enterprise Customer Support & Integration API

A resilient, production-ready REST API built with **FastAPI**, **SQLModel**, **Pydantic v2**, and **Docker**. Designed for seamless enterprise customer support management and automated cross-platform synchronization (e.g., Salesforce, Jira).

---

## ✨ Features

* **⚡ Core CRUD Operations:** Full ticket lifecycle management (Create, Read, Update, Delete) powered by SQLModel and SQLite.
* **🛡️ Enterprise Security:** Internal API Key header authentication (`X-API-Key`) with interactive Swagger UI support.
* **🔒 HMAC SHA-256 Signature Verification:** Encrypts and validates outgoing and incoming webhook payloads to guarantee data integrity.
* **🔁 Resilient Webhooks & Retries:** Asynchronous background workers deliver event webhooks using exponential backoff retry logic.
* **📥 Inbound Event Handler & Idempotency:** Receives external webhook payloads and automatically prevents duplicate event processing.
* **⚙️ Dynamic Configuration:** Environment management powered by `pydantic-settings` and `.env` support.
* **🐋 Containerized Architecture:** Complete Docker & Docker Compose setup for consistent deployment across environments.
* **🧪 100% Automated Test Coverage:** Isolated in-memory testing environment built with `pytest` and FastAPI's `TestClient`.

---

## 🏗️ Architecture & Tech Stack

* **Framework:** [FastAPI](https://fastapi.tiangolo.com/)
* **ORM / Database:** [SQLModel](https://sqlmodel.tiangolo.com/) / SQLite
* **Validation & Settings:** [Pydantic v2](https://docs.pydantic.dev/) & `pydantic-settings`
* **HTTP Client:** [httpx](https://www.python-httpx.org/)
* **Testing:** [pytest](https://docs.pytest.org/)
* **Containerization:** Docker & Docker Compose

---

## 🚀 Getting Started

### Prerequisites

* Python 3.10+ installed locally, **OR**
* [Docker Desktop](https://www.docker.com/products/docker-desktop/)

---

### 🔧 Local Installation & Setup

1. **Clone the Repository:**
   ```bash
   git clone [https://github.com/your-username/ticket-api.git](https://github.com/your-username/ticket-api.git)
   cd ticket-api