# Phase 4 Setup Guide
# ====================
# Follow these steps in order.

# ── STEP 1: Copy files into your project ─────────────────────────────────
#
# Your project should now look like:
#
# Fin_Gurdain/
# ├── app/                     ← Phase 3 (already done)
# ├── workers/
# │   └── detection_worker.py  ← copy from phase4/
# ├── graph/
# │   └── schema.cypher        ← copy from phase4/
# ├── artifacts/               ← already exists
# ├── docker-compose.yml       ← copy from phase4/ to ROOT
# └── requirements.txt

# ── STEP 2: Install new Python packages ──────────────────────────────────
pip install neo4j redis aiokafka

# ── STEP 3: Start all infrastructure services ─────────────────────────────
# Run this from Fin_Gurdain/ folder (where docker-compose.yml is)
# First time: downloads Docker images (~500MB), takes 3-5 minutes
# After that: starts in ~30 seconds

docker-compose up -d

# Verify all services are running:
docker-compose ps

# You should see all services as "healthy" or "running":
# fin_guardian_zookeeper   running
# fin_guardian_kafka       running
# fin_guardian_kafka_ui    running
# fin_guardian_redis       running
# fin_guardian_neo4j       running

# ── STEP 4: Verify each service ───────────────────────────────────────────

# Redis — should print PONG:
docker exec fin_guardian_redis redis-cli ping

# Kafka — should list topics:
docker exec fin_guardian_kafka kafka-topics --bootstrap-server localhost:9092 --list

# Neo4j browser (open in browser):
# http://localhost:7474
# Login: neo4j / fingurdain123

# Kafka UI (open in browser):
# http://localhost:8080

# ── STEP 5: Set up Neo4j graph schema ────────────────────────────────────
# Open http://localhost:7474
# Login with neo4j / fingurdain123
# Click the database icon on the left
# Paste the contents of graph/schema.cypher and run it
# You should see 3 Account nodes created

# ── STEP 6: Start the detection worker ───────────────────────────────────
# Open a NEW terminal (keep the gateway running in the other one)

cd C:\Users\rohan\OneDrive\Desktop\Fin_Gurdain
myenv\Scripts\activate
python workers/detection_worker.py

# You should see:
# {"service":"detection_worker","message":"Connected to Neo4j at bolt://localhost:7687"}
# {"service":"detection_worker","message":"Connected to Redis at redis://localhost:6379/0"}
# {"service":"detection_worker","message":"Kafka consumer started — waiting for HOLD events..."}

# ── STEP 7: Test the full pipeline ───────────────────────────────────────
# Terminal 1: Gateway running (python -m uvicorn app.main:app ...)
# Terminal 2: Worker running (python workers/detection_worker.py)

# Now trigger a HOLD event from the Swagger UI:
# Open http://localhost:8000/docs
# Click POST /api/v1/transactions/evaluate
# Click "Try it out"
# Paste this JSON and click Execute:
# {
#   "account_id": "C_PRIYA_STUDENT_001",
#   "recipient_id": "C_UNKNOWN_RECIPIENT_999",
#   "amount": 45000.0,
#   "transaction_type": "TRANSFER",
#   "timestamp": "2026-01-15T14:30:00Z",
#   "account_age_days": 180,
#   "account_balance_before": 50000.0,
#   "is_new_recipient": true,
#   "sender_tx_count": 3
# }

# Watch Terminal 2 — you should see the worker pick up the HOLD event
# and run the Neo4j investigation within seconds.

# ── STEP 8: Check investigation results in Redis ──────────────────────────
# After the worker processes a HOLD event, check the result:

python -c "
import redis, json
r = redis.Redis(host='localhost', port=6379, decode_responses=True)
keys = r.keys('investigation:*')
print(f'Found {len(keys)} investigations in Redis')
for key in keys[:3]:
    data = json.loads(r.get(key))
    print(f'  {key}: score={data[\"final_score\"]} action={data[\"action\"]}')
"

# ── TROUBLESHOOTING ───────────────────────────────────────────────────────

# Services not starting?
# docker-compose logs zookeeper
# docker-compose logs kafka
# docker-compose logs neo4j

# Neo4j GDS plugin not loading?
# It downloads automatically on first start — wait 2-3 minutes
# Check: docker-compose logs neo4j | grep -i "gds"

# Worker can't connect to Kafka?
# Make sure you're using port 29092 (external port), not 9092
# 9092 is for container-to-container communication only

# To stop everything when done:
# docker-compose down

# To stop and delete all data (fresh start):
# docker-compose down -v
