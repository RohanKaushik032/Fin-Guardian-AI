# 🚀 Fin-Guardian AI — Complete Project Setup Guide

## Phase Overview
Your project is structured in 4 implementation phases:
- **Phase 1**: Real-time fraud detection API (Hot Path - 30ms)
- **Phase 2**: Feature engineering & storage
- **Phase 3**: Network graph analysis (Neo4j)
- **Phase 4**: AI Detective & Deep Investigation (LangGraph)

---

## 📁 Complete Project Structure (After Setup)

```
Fin_Gurdain/
├── app/                                    ← FastAPI application
│   ├── __init__.py
│   ├── main.py                            ← API entry point
│   ├── config.py                          ← Configuration management
│   ├── models/                            ← Pydantic data models
│   │   ├── __init__.py
│   │   ├── transaction.py                 ← Transaction request/response models
│   │   └── investigation.py               ← Investigation report models
│   ├── api/                               ← API routes
│   │   ├── __init__.py
│   │   └── transactions.py                ← POST /api/v1/transactions/evaluate
│   ├── services/                          ← Business logic
│   │   ├── __init__.py
│   │   ├── fraud_detector.py              ← XGBoost classifier (Layer 1)
│   │   ├── feature_store.py               ← Redis feature retrieval
│   │   ├── graph_analyzer.py              ← Neo4j queries (Layer 2)
│   │   └── investigator.py                ← LangGraph agent (Layer 3)
│   └── utils/
│       ├── __init__.py
│       ├── kafka_producer.py              ← Publish HOLD events
│       └── logging.py                     ← Structured logging
│
├── workers/                               ← Background processing
│   ├── __init__.py
│   ├── detection_worker.py                ← Kafka consumer for deep investigation
│   └── tasks.py                           ← Task definitions
│
├── models/                                ← Trained ML models
│   ├── xgboost_classifier.pkl             ← Fraud classifier
│   ├── autoencoder.pth                    ← Anomaly detection model
│   └── feature_scaler.pkl                 ← Feature normalization
│
├── graph/                                 ← Neo4j setup
│   ├── schema.cypher                      ← Graph schema initialization
│   └── queries.py                         ← Neo4j query templates
│
├── notebooks/                             ← Learning & experimentation
│   ├── 01_xgboost_training.ipynb          ← Build fraud classifier
│   ├── 02_feature_engineering.ipynb       ← Feature exploration
│   ├── 03_graph_analysis.ipynb            ← Community detection
│   └── 04_langgraph_agent.ipynb           ← AI detective design
│
├── artifacts/                             ← Generated outputs
│   ├── training_logs/
│   ├── investigation_reports/
│   └── metrics/
│
├── tests/                                 ← Test suite
│   ├── __init__.py
│   ├── test_fraud_detector.py
│   ├── test_api.py
│   └── test_integration.py
│
├── docs/                                  ← Documentation
│   ├── API.md                             ← API reference
│   ├── ARCHITECTURE.md                    ← System design
│   └── DEPLOYMENT.md                      ← Production setup
│
├── docker-compose.yml                     ← Infrastructure setup
├── requirements.txt                       ← Python dependencies
├── .env.example                           ← Environment variables template
├── PROJECT_SETUP.md                       ← This file
└── README.md                              ← Quick start guide
```

---

## 🔧 Step-by-Step Setup Instructions

### **Step 1: Install Python Dependencies**

```bash
cd c:\Users\rohan\OneDrive\Desktop\Fin_Gurdain
myenv\Scripts\activate

# Install core packages
pip install -r requirements.txt

# Add additional packages for full pipeline
pip install neo4j redis pytest jupyter notebook scikit-learn langgraph langchain-openai
```

### **Step 2: Start Infrastructure Services (Docker)**

```bash
# From the Fin_Gurdain folder
docker-compose up -d

# Verify all services are healthy
docker-compose ps

# Check each service:
# Redis
docker exec fin_guardian_redis redis-cli ping          # Should return PONG
# Kafka
docker exec fin_guardian_kafka kafka-topics --bootstrap-server localhost:9092 --list
# Neo4j - access at http://localhost:7474 (user: neo4j / password: fingurdain123)
```

### **Step 3: Initialize Neo4j Graph Schema**

1. Open http://localhost:7474 in your browser
2. Login with: **neo4j** / **fingurdain123**
3. Run the following Cypher commands:

```cypher
// Create account nodes
CREATE (priya:Account {
  account_id: 'C_PRIYA_STUDENT_001',
  name: 'Priya (Student)',
  account_type: 'PERSONAL',
  created_at: datetime('2024-06-15T00:00:00Z'),
  risk_score: 0.2
});

CREATE (landlord:Account {
  account_id: 'C_LANDLORD_RK_APARTMENTS_002',
  name: 'RK Apartments Rent Collection',
  account_type: 'BUSINESS',
  created_at: datetime('2023-01-01T00:00:00Z'),
  risk_score: 0.1
});

CREATE (mule:Account {
  account_id: 'C_UNKNOWN_RECIPIENT_999',
  name: 'Unknown Recipient (Money Mule)',
  account_type: 'PERSONAL',
  created_at: datetime('2025-12-01T00:00:00Z'),
  risk_score: 0.95
});

// You can add more relationships as the system runs
```

### **Step 4: Create Configuration File (.env)**

```bash
# Create .env file in Fin_Gurdain folder
cat > .env << EOF
# FastAPI Settings
ENVIRONMENT=development
API_TITLE=Fin-Guardian AI
API_VERSION=1.0.0

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

# Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=fingurdain123
NEO4J_DATABASE=neo4j

# Kafka
KAFKA_BOOTSTRAP_SERVERS=localhost:29092
KAFKA_HOLD_TOPIC=transactions.hold
KAFKA_INVESTIGATION_TOPIC=investigations.completed

# OpenAI (for LangGraph agent - optional for now)
OPENAI_API_KEY=your_api_key_here

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json
EOF
```

### **Step 5: Run the FastAPI Application**

```bash
cd c:\Users\rohan\OneDrive\Desktop\Fin_Gurdain
myenv\Scripts\activate

# Start the API server
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# You should see:
# INFO:     Uvicorn running on http://0.0.0.0:8000
# Access Swagger UI: http://localhost:8000/docs
```

### **Step 6: Run the Detection Worker (in a new terminal)**

```bash
# Terminal 2
cd c:\Users\rohan\OneDrive\Desktop\Fin_Gurdain
myenv\Scripts\activate

# Start Kafka consumer for investigations
python workers/detection_worker.py

# You should see:
# {"service":"detection_worker","message":"Kafka consumer started — waiting for HOLD events..."}
```

### **Step 7: Test the Full Pipeline**

Open Swagger UI: http://localhost:8000/docs

**Test Transaction (Will trigger a HOLD):**
```json
{
  "account_id": "C_PRIYA_STUDENT_001",
  "recipient_id": "C_UNKNOWN_RECIPIENT_999",
  "amount": 45000.0,
  "transaction_type": "TRANSFER",
  "timestamp": "2026-01-15T14:30:00Z",
  "account_age_days": 180,
  "account_balance_before": 50000.0,
  "is_new_recipient": true,
  "sender_tx_count": 3
}
```

Expected result:
- API returns: `{"status":"HOLD", "investigation_id":"inv_xxx"}`
- Worker receives the event on Kafka and runs Neo4j analysis
- Investigation result stored in Redis under `investigation:inv_xxx`

---

## 📚 Learning Modules (What to Build First)

### **Module 1: XGBoost Fraud Classifier (4-6 hours)**
- Location: `app/services/fraud_detector.py`
- Notebook: `notebooks/01_xgboost_training.ipynb`
- Learn: Classification, feature importance, model evaluation
- **Status**: ⏳ To be created

### **Module 2: Feature Engineering (6-8 hours)**
- Location: `app/services/feature_store.py`
- Notebook: `notebooks/02_feature_engineering.ipynb`
- Learn: User behavior patterns, time-based features, aggregations
- **Status**: ⏳ To be created

### **Module 3: Neo4j Graph Analysis (5-7 hours)**
- Location: `app/services/graph_analyzer.py`
- Notebook: `notebooks/03_graph_analysis.ipynb`
- Learn: Graph databases, Cypher queries, community detection
- **Status**: ⏳ To be created

### **Module 4: LangGraph AI Detective (8-10 hours)**
- Location: `app/services/investigator.py`
- Notebook: `notebooks/04_langgraph_agent.ipynb`
- Learn: Multi-tool agents, LLM orchestration, investigation reports
- **Status**: ⏳ To be created

---

## 🧪 Testing Your Setup

After each module is built, run:

```bash
# Unit tests
pytest tests/ -v

# Integration test (full pipeline)
python test_api.py

# Performance test (30ms constraint)
python -c "
import time
from app.services.fraud_detector import FraudDetector
detector = FraudDetector()
start = time.time()
result = detector.predict({...})
elapsed = (time.time() - start) * 1000
print(f'Prediction latency: {elapsed:.2f}ms (must be <30ms)')
"
```

---

## 🐛 Troubleshooting

| Problem | Solution |
|---------|----------|
| Docker services won't start | `docker-compose down -v && docker-compose up -d` |
| Neo4j connection refused | Wait 30s for Neo4j to start, check: `docker-compose logs neo4j` |
| Kafka topics not created | Topics auto-create on first message, or manually run: `docker exec fin_guardian_kafka kafka-topics --create --topic transactions.hold --bootstrap-server localhost:9092` |
| Python imports fail | Ensure venv is activated: `myenv\Scripts\activate` |
| Port 8000 already in use | `netstat -ano \| findstr :8000` then kill the process |

---

## 📖 Recommended Learning Path

1. **Week 1**: Module 1 (XGBoost) + Module 2 (Features) — understand fraud signals
2. **Week 2**: Module 3 (Neo4j) — understand network patterns
3. **Week 3**: Module 4 (LangGraph) — build investigation automation
4. **Week 4**: Integration & Optimization — tie everything together

**Next Step**: Choose which module to start with!

