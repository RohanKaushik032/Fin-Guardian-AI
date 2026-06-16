# Fin-Guardian AI — Quick Start Guide

> Real-time fraud detection in under 30 milliseconds  
> Autonomous, explainable, production-ready

## 🎯 What This System Does

Fin-Guardian AI stops fraud **before the transaction completes** by:
1. **Instantly scoring** transactions with XGBoost + Autoencoder (<30ms)
2. **Mapping fraud networks** with graph algorithms (Neo4j)
3. **Investigating deeply** with an AI agent (LangGraph)
4. **Responding smartly** with adaptive step-up challenges

---

## ⚡ Quick Start (5 minutes)

### 1. Install Dependencies
```bash
cd c:\Users\rohan\OneDrive\Desktop\Fin_Gurdain
myenv\Scripts\activate
pip install -r requirements.txt
pip install neo4j redis pytest jupyter langgraph langchain-openai
```

### 2. Start Infrastructure
```bash
# Terminal 1: Start all services (Kafka, Neo4j, Redis)
docker-compose up -d

# Verify everything is running
docker-compose ps
```

### 3. Initialize Database
```bash
# Open http://localhost:7474
# Login: neo4j / fingurdain123
# Paste these commands in the query editor:

CREATE (priya:Account {
  account_id: 'C_PRIYA_STUDENT_001',
  name: 'Priya (Student)',
  risk_score: 0.2
});

CREATE (unknown:Account {
  account_id: 'C_UNKNOWN_RECIPIENT_999',
  name: 'Money Mule Account',
  risk_score: 0.95
});
```

### 4. Start API
```bash
# Terminal 2: Run the FastAPI server
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Open Swagger UI: http://localhost:8000/docs
```

### 5. Test a Transaction
Open http://localhost:8000/docs → Try POST /api/v1/transactions/evaluate

```json
{
  "account_id": "C_PRIYA_STUDENT_001",
  "recipient_id": "C_UNKNOWN_RECIPIENT_999",
  "amount": 92000.0,
  "transaction_type": "TRANSFER",
  "timestamp": "2026-01-15T23:45:00Z",
  "account_age_days": 180,
  "account_balance_before": 95000.0,
  "is_new_recipient": true,
  "sender_tx_count": 3
}
```

**Expected Response:**
```json
{
  "verdict": "HOLD",
  "fraud_score": 0.87,
  "challenge_type": "BIOMETRIC",
  "inference_latency_ms": 18.5
}
```

---

## 📚 Learning Path

Start here based on your goals:

| Goal | Start Here | Time |
|------|-----------|------|
| Understand the architecture | Read `docs/LEARNING_CURRICULUM.md` | 2 hrs |
| Build fraud classifier | `notebooks/01_xgboost_training.ipynb` | 4-6 hrs |
| Learn graph analysis | `notebooks/03_graph_analysis.ipynb` | 4-6 hrs |
| Build AI agent | `notebooks/04_langgraph_agent.ipynb` | 6-8 hrs |
| Deploy to production | `docs/DEPLOYMENT.md` | 2-3 hrs |

---

## 🏗️ Project Structure

```
Fin_Gurdain/
├── app/                    ← FastAPI application (Layer 1)
├── workers/               ← Background workers (Layers 2-3)
├── graph/                 ← Neo4j queries
├── notebooks/             ← Learning & experiments
├── docs/                  ← Documentation & curriculum
├── docker-compose.yml     ← Infrastructure as code
└── requirements.txt       ← Python dependencies
```

---

## 🧠 Key Concepts (Explained Simply)

### **The 4 Layers**

**Layer 1 — Hot Path (under 30ms)**
- Runs XGBoost + Autoencoder in parallel
- Returns APPROVE, HOLD, or DENY instantly
- Example: Priya's unusual ₹92K transfer → **HOLD** ⏸

**Layer 2 — Warm Path (seconds)**
- Queries Neo4j for recipient's transaction network
- Runs Louvain algorithm to find fraud rings
- Example: Unknown recipient = money mule in ring → **Confirm HOLD**

**Layer 3 — Deep Path**
- AI agent autonomously investigates
- Calls tools: query Neo4j, check risk scores, analyze patterns
- Produces forensic investigation report

**Layer 4 — Smart Response**
- Not: "Your transaction is blocked" ❌
- But: "Please authenticate with Face ID" ✓ (adaptive)
- Levels: confirmation → biometric → behavior challenge

---

## 🚀 What You'll Build

### **Week 1: XGBoost Fraud Classifier**
- Train model on transaction features
- Achieve >95% accuracy
- Optimize latency to <5ms

### **Week 2: Feature Engineering**
- Extract user behavior patterns
- Real-time feature computation
- Redis-backed feature store

### **Week 3: Money Laundering Network Detection**
- Query Neo4j transaction graphs
- Run community detection (Louvain)
- Identify money mule accounts

### **Week 4: AI Detective**
- Build LangGraph agent
- Orchestrate investigation tools
- Generate forensic reports

### **Week 5: Full System Integration**
- Connect all 4 layers
- Handle 1000s concurrent transactions
- Monitor and optimize

---

## 🐛 Troubleshooting

**Docker services not starting?**
```bash
docker-compose down -v
docker-compose up -d
docker-compose logs neo4j  # Check Neo4j specifically
```

**Connection refused on port 8000?**
```bash
# Kill any process using 8000
netstat -ano | findstr :8000
taskkill /PID <PID> /F
```

**Neo4j won't accept passwords?**
```bash
# Reset Neo4j (delete all data)
docker exec fin_guardian_neo4j rm -rf /data/databases/*
docker restart fin_guardian_neo4j
```

---

## 📖 Next Steps

1. **Read the full curriculum:** `docs/LEARNING_CURRICULUM.md`
2. **Start a notebook:** `notebooks/01_xgboost_training.ipynb`
3. **Set up infrastructure:** Follow "Quick Start" above
4. **Join the journey:** Build Fin-Guardian AI with us!

---

## 🎓 Resources

- **Your Design Document:** `Fin-Guardian-AI-Document.docx`
- **Project Setup Guide:** `PROJECT_SETUP.md`
- **Learning Curriculum:** `docs/LEARNING_CURRICULUM.md`
- **API Documentation:** `docs/API.md` (coming soon)

---

**Questions?** Check `docs/LEARNING_CURRICULUM.md` for detailed explanations, or create an issue!

Happy learning! 🚀

