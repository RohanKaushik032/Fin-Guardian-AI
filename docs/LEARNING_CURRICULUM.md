# 📚 Fin-Guardian AI — Learning Curriculum

## 🎯 Learning Objectives

By the end of this course, you will understand and implement:
1. **Real-time fraud detection** under 30ms latency constraint
2. **Machine learning pipelines** for classification & anomaly detection
3. **Graph databases** for money laundering network detection
4. **AI agents** for automated investigations
5. **Distributed systems** (Kafka, Redis, Neo4j)
6. **Production-grade API design** with graceful degradation

---

## 📊 Curriculum Overview

### **Foundation Phase (Weeks 1-2)**
Understand the fraud problem and why existing systems fail.

**Topics:**
- Financial fraud types and attack patterns
- Why 30ms matters (real-time constraint)
- Feature engineering for transactional data
- Time-series analysis of user behavior

**Resources:**
- "Fraud Analytics: Methods and Applications" (2020)
- Kaggle: IEEE-CIS Fraud Detection
- Your document: Section 1 "What Is Wrong With Today's Systems"

---

### **Module 1: Building the Hot Path (Layer 1)**
Time: 4-6 weeks

#### 1.1 XGBoost Fraud Classifier (Week 1)
**Goal:** Build a fast classification model that scores transactions in <5ms

**Learning Path:**
1. Understand gradient boosting and XGBoost algorithm (2 hrs)
2. Load and explore fraud detection dataset (2 hrs)
3. Build baseline XGBoost model (3 hrs)
4. Feature importance analysis with SHAP (3 hrs)
5. Optimize for latency: tree depth, batch prediction (2 hrs)

**Key Concepts:**
- Decision trees and ensemble methods
- Feature importance (SHAP values)
- Model serialization (pickle, ONNX)
- Batch vs. single prediction latency

**Implementation:**
```python
# Location: app/services/fraud_detector.py

class FraudDetector:
    def __init__(self, model_path: str):
        self.model = xgboost.XGBClassifier()
        self.model.load_model(model_path)
    
    def predict(self, features: dict) -> dict:
        # Must return in <5ms
        X = self.encode_features(features)
        fraud_prob = self.model.predict_proba(X)[0][1]
        explanation = self.shap_explainer.values(X)[0]
        return {
            "fraud_probability": fraud_prob,
            "top_features": explanation.argsort()[-3:]
        }
```

**Testing:**
- Latency: `python tests/test_latency.py`
- Accuracy: `pytest tests/test_fraud_detector.py`

---

#### 1.2 Autoencoder for Anomaly Detection (Week 2)
**Goal:** Detect novel fraud patterns the classifier hasn't seen

**Learning Path:**
1. Understand autoencoders and reconstruction error (2 hrs)
2. Build a neural network encoder-decoder in PyTorch (3 hrs)
3. Train on normal transactions, test on outliers (3 hrs)
4. Optimize for inference speed: model size, batch norm (2 hrs)

**Key Concepts:**
- Neural network architecture: encoder → bottleneck → decoder
- Reconstruction error as anomaly score
- Dimensionality reduction
- Real-time inference optimization

**Implementation:**
```python
# Location: app/services/anomaly_detector.py

class TransactionAutoencoder(nn.Module):
    def __init__(self, input_dim, latent_dim):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(input_dim, 64),
            nn.ReLU(),
            nn.Linear(64, latent_dim)
        )
        self.decoder = nn.Sequential(
            nn.Linear(latent_dim, 64),
            nn.ReLU(),
            nn.Linear(64, input_dim)
        )
    
    def forward(self, x):
        z = self.encoder(x)
        recon = self.decoder(z)
        return recon, torch.mean((x - recon) ** 2)
```

---

#### 1.3 Feature Engineering Pipeline (Week 3)
**Goal:** Extract relevant features from raw transactions in <3ms

**Learning Path:**
1. Understand time-based features (hour encoding fix!) (2 hrs)
2. User behavior aggregations: rolling averages, velocity (3 hrs)
3. Device fingerprinting and IP reputation (2 hrs)
4. Real-time feature computation with Redis (3 hrs)

**Key Concepts:**
- Temporal encoding (hour as sin/cos, not raw 0-23)
- Rolling statistics (30-day average, 7-day volatility)
- Categorical encoding (account age bins, etc.)
- Cache-aware feature retrieval

**Challenge: Hour Encoding Fix**
Raw hour numbers are misleading:
- Hour 23 (11 PM) vs Hour 0 (midnight) = 60 minutes apart
- But numerically: |23 - 0| = 23 hours! ❌

**Solution: Circular encoding**
```python
import numpy as np

hour = transaction.timestamp.hour
hour_sin = np.sin(2 * np.pi * hour / 24)
hour_cos = np.cos(2 * np.pi * hour / 24)
# Now hour 23 and hour 0 are numerically close ✓
```

**Implementation:**
```python
# Location: app/services/feature_engineering.py

def build_features(transaction: Transaction) -> dict:
    """Extract all features in <3ms."""
    
    # User behavior (from Redis, pre-computed)
    user_stats = redis_client.get(f"user:{transaction.account_id}")
    
    # Temporal features
    hour_sin = np.sin(2 * np.pi * transaction.timestamp.hour / 24)
    hour_cos = np.cos(2 * np.pi * transaction.timestamp.hour / 24)
    
    # Transaction features
    amount_ratio = transaction.amount / user_stats['avg_amount']
    is_new_recipient = transaction.recipient_id not in user_stats['recipients']
    
    return {
        "amount": transaction.amount,
        "hour_sin": hour_sin,
        "hour_cos": hour_cos,
        "amount_ratio": amount_ratio,
        "is_new_recipient": is_new_recipient,
        "account_age_days": transaction.account_age_days,
        "sender_tx_count": transaction.sender_tx_count,
        # ... more features
    }
```

---

### **Module 2: Network Graph Analysis (Layer 2)**
Time: 3-4 weeks

#### 2.1 Neo4j Fundamentals (Week 1)
**Goal:** Model financial networks as graphs

**Learning Path:**
1. Graph theory basics: nodes, edges, paths (2 hrs)
2. Neo4j architecture and Cypher query language (3 hrs)
3. Creating and querying account transaction graphs (3 hrs)

**Key Concepts:**
- Property graphs: nodes have properties, edges have labels
- Cypher: SQL-like syntax for graph queries
- Indexes and query optimization
- APOC utilities

**Example: Money Laundering Network**
```
Account A → sends ₹50K → Account B
Account B → sends ₹45K → Account C
Account C → sends ₹40K → Account D
Account D → sends ₹35K → Account E

Visible pattern: Money flowing through a chain (laundering ring!)
```

**Implementation:**
```cypher
// Create accounts
CREATE (a:Account {account_id: 'ACC001', risk_score: 0.1})
CREATE (b:Account {account_id: 'ACC002', risk_score: 0.9})

// Create transaction edge
MATCH (a:Account {account_id: 'ACC001'}),
      (b:Account {account_id: 'ACC002'})
CREATE (a)-[:SENT {amount: 50000, timestamp: datetime()}]->(b)

// Find all recipients of a suspicious account
MATCH (suspect:Account)-[:SENT]->(recipient)
RETURN recipient.account_id, COUNT(*) as transaction_count
ORDER BY transaction_count DESC
```

---

#### 2.2 Community Detection with Louvain Algorithm (Week 2)
**Goal:** Find tightly-connected fraud clusters

**Learning Path:**
1. Understanding community detection algorithms (2 hrs)
2. Louvain algorithm for modularity optimization (2 hrs)
3. Running Louvain in Neo4j GDS (2 hrs)
4. Interpreting results and finding fraud rings (2 hrs)

**Key Concepts:**
- Graph modularity: measure of community quality
- Louvain algorithm: greedy optimization
- Neo4j GDS (Graph Data Science) library

**Example:**
```
Community 1: [ACC001, ACC002, ACC003, ACC004]
- 47 transactions between these accounts in past month
- Pattern: Each receives from external, passes through chain
- Verdict: 95% confidence money laundering ring
```

**Implementation:**
```cypher
// Run Louvain community detection
CALL gds.louvain.stream('transactions', {relationshipTypes: ['SENT']})
YIELD nodeId, communityId
WITH gds.util.asNode(nodeId) as account, communityId
RETURN account.account_id, communityId, COUNT(*) as accounts_in_community
ORDER BY communityId

// Find high-risk communities (many transactions, no delay)
MATCH (a:Account)-[t:SENT {timestamp: ..}]->(b:Account)
WHERE a.community = b.community
WITH a.community as community, COUNT(t) as tx_count, 
     AVG(t.delay_minutes) as avg_delay
WHERE tx_count > 10 AND avg_delay < 5
RETURN community, tx_count, avg_delay  // Likely laundering!
```

---

#### 2.3 Centrality Analysis (Week 3)
**Goal:** Identify hub accounts (money mules, collection points)

**Learning Path:**
1. Centrality measures: betweenness, closeness, eigenvector (2 hrs)
2. Neo4j GDS centrality algorithms (2 hrs)
3. Interpreting central accounts as money mules (2 hrs)

**Key Concepts:**
- Betweenness centrality: frequency of appearing on shortest paths
- Money mule: account that routes money from many sources
- Collection account: receives funds, immediately forwards

**Implementation:**
```cypher
// Find high-betweenness accounts (connectors)
CALL gds.betweenness.stream('transactions', {relationshipTypes: ['SENT']})
YIELD nodeId, score
WITH gds.util.asNode(nodeId) as account, score
WHERE score > 100  // High betweenness
RETURN account.account_id, score, account.risk_score
ORDER BY score DESC

// Money mule detector
// (receives from many, all with 1-2 day gaps, then forwards)
MATCH (source:Account)-[in_tx:SENT]->(mule:Account)-[out_tx:SENT]->(dest)
WHERE in_tx.timestamp < out_tx.timestamp
  AND duration.inDays(in_tx.timestamp, out_tx.timestamp).days <= 2
WITH mule, COUNT(DISTINCT source) as sources, COUNT(DISTINCT dest) as dests
WHERE sources >= 5 AND dests >= 3  // Likely money mule
RETURN mule.account_id, sources, dests
```

---

### **Module 3: AI Detective with LangGraph (Layer 3)**
Time: 3-4 weeks

#### 3.1 LangGraph Fundamentals (Week 1)
**Goal:** Build an AI agent that orchestrates multiple investigation tools

**Learning Path:**
1. LangChain & LangGraph concepts (2 hrs)
2. Agent state management and tool calling (3 hrs)
3. Building a stateful investigation workflow (3 hrs)

**Key Concepts:**
- Agent: AI making decisions on which tool to use
- Tools: Functions the agent can call (Neo4j query, Redis lookup, etc.)
- State: Shared context across steps
- ReAct pattern: Reasoning → Acting → Observing

**Agent Architecture:**
```
User Query: "Is this transaction suspicious?"
    ↓
Agent thinks: "I need to check this recipient's history"
    ↓
Agent calls tool: query_neo4j("recipient history")
    ↓
Agent sees result: "47 transactions in past month"
    ↓
Agent thinks: "High activity. Now check for patterns"
    ↓
Agent calls tool: run_community_detection()
    ↓
Agent sees result: "Detected 1 community with this recipient"
    ↓
Agent synthesizes: "Likely money mule. Recommend DENY"
```

**Implementation:**
```python
# Location: app/services/investigator.py

from langgraph.graph import StateGraph, END
from typing import TypedDict

class InvestigationState(TypedDict):
    transaction_id: str
    recipient_id: str
    fraud_score: float
    findings: list[dict]  # Investigation findings
    recommendation: str  # APPROVE, HOLD, DENY

# Define tools
def query_recipient_history(recipient_id: str) -> dict:
    """Query Neo4j for recipient transaction history."""
    # Implementation...
    pass

def check_community_membership(account_id: str) -> dict:
    """Check if account is in detected fraud community."""
    # Implementation...
    pass

def get_risk_score(account_id: str) -> float:
    """Get account risk score from database."""
    # Implementation...
    pass

# Define agent steps
def step_gather_history(state: InvestigationState) -> InvestigationState:
    history = query_recipient_history(state['recipient_id'])
    state['findings'].append({'type': 'history', 'data': history})
    return state

def step_check_community(state: InvestigationState) -> InvestigationState:
    community = check_community_membership(state['recipient_id'])
    state['findings'].append({'type': 'community', 'data': community})
    return state

def step_synthesize(state: InvestigationState) -> InvestigationState:
    # Use LLM to synthesize findings into recommendation
    findings_text = "\n".join([f"{f['type']}: {f['data']}" for f in state['findings']])
    recommendation = llm.invoke(f"Given these findings, should we approve or deny?\n{findings_text}")
    state['recommendation'] = recommendation
    return state

# Build graph
graph = StateGraph(InvestigationState)
graph.add_node("gather_history", step_gather_history)
graph.add_node("check_community", step_check_community)
graph.add_node("synthesize", step_synthesize)
graph.add_edge("gather_history", "check_community")
graph.add_edge("check_community", "synthesize")
graph.add_edge("synthesize", END)
```

---

### **Module 4: Production Deployment & Monitoring**
Time: 2 weeks

#### 4.1 Kafka & Celery for Async Processing
**Goal:** Handle thousands of concurrent investigations without blocking

**Key Concepts:**
- Kafka for durable message replay (not Redis Pub/Sub)
- Celery workers for parallel investigation tasks
- Circuit breakers for graceful degradation
- Monitoring with Prometheus

---

## 🧑‍💻 Hands-On Exercises

### **Exercise 1: Build Your First Fraud Detector**
```bash
cd notebooks
jupyter notebook 01_xgboost_training.ipynb
```

**Deliverable:** A trained XGBoost model that classifies transactions with 95%+ accuracy

---

### **Exercise 2: Find Money Mules in a Real Network**
```bash
cd notebooks
jupyter notebook 03_graph_analysis.ipynb
```

**Deliverable:** Community detection output showing 2-3 detected fraud rings

---

### **Exercise 3: Build an Investigation Agent**
```bash
cd notebooks
jupyter notebook 04_langgraph_agent.ipynb
```

**Deliverable:** An agent that can autonomously investigate 5 test transactions and explain its reasoning

---

## 📚 Recommended Reading Order

### **Week 1-2: Fraud Fundamentals**
1. Your document: Sections 0, 1, 2, 3
2. "Fraud Analytics: Methods and Applications" (Chapter 1)
3. IEEE-CIS Fraud Detection Kaggle: Problem description

### **Week 3-4: Machine Learning for Fraud**
1. "Hands-On Machine Learning" (Chapters 6-7: Ensemble methods)
2. XGBoost paper: "XGBoost: A Scalable Tree Boosting System"
3. SHAP documentation & interpretability

### **Week 5-6: Graph Databases**
1. Neo4j official documentation
2. "Graph Databases in Action" (O'Reilly)
3. Louvain algorithm paper

### **Week 7-8: AI Agents**
1. LangChain & LangGraph documentation
2. "Agents as a Paradigm for Agentic AI"
3. ReAct framework paper

---

## 🎓 Learning Checkpoints

After each module, verify your understanding:

**Module 1 Checkpoint:**
- [ ] Build XGBoost model with >95% accuracy
- [ ] Latency <5ms for single prediction
- [ ] Autoencoder trained on normal transactions
- [ ] Feature engineering pipeline running in <3ms

**Module 2 Checkpoint:**
- [ ] Neo4j running with sample transaction graph
- [ ] Louvain community detection finds test fraud ring
- [ ] Centrality analysis identifies money mules
- [ ] All Neo4j queries <500ms

**Module 3 Checkpoint:**
- [ ] LangGraph agent makes 3+ sequential tool calls
- [ ] Agent explains its reasoning in natural language
- [ ] Investigation completes in <5 seconds

**Module 4 Checkpoint:**
- [ ] Full end-to-end: transaction → HOLD → investigation → result
- [ ] Kafka durable message handling
- [ ] System survives Neo4j shutdown (graceful degradation)

---

## 🚀 Next Steps

1. **Start with Exercise 1** — get hands-on with XGBoost in a notebook
2. **Follow the PROJECT_SETUP.md** — get infrastructure running
3. **Set up your first learning session** — schedule focused time blocks
4. **Build incrementally** — each module builds on the previous one

**Your goal:** By week 8, you'll have built a production-grade fraud detection system that works in real-time at scale.

Let's go! 🚀

