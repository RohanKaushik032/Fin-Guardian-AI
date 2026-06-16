// graph/schema.cypher
// ────────────────────
// Fin-Guardian AI — Neo4j Graph Schema
//
// This file sets up the fraud detection graph database.
//
// CONCEPT: Think of this like creating tables in SQL,
// but instead of tables, we create NODES and RELATIONSHIPS.
//
// In a relational database (SQL):
//   accounts table: id, name, balance
//   transactions table: from_id, to_id, amount
//   Finding fraud networks = 10+ JOIN operations = slow
//
// In Neo4j (graph):
//   Account nodes connected by TRANSFERRED_TO edges
//   Finding fraud networks = 1 graph traversal = milliseconds
//
// RUN THIS FILE:
//   Open http://localhost:7474
//   Login: neo4j / fingurdain123
//   Paste each block and run it
//
// OR run via Python (graph_writer.py does this automatically on startup)

// ── Constraints (like PRIMARY KEY in SQL) ─────────────────────────────────
// Ensures every account_id is unique and speeds up lookups.

CREATE CONSTRAINT account_id_unique IF NOT EXISTS
FOR (a:Account) REQUIRE a.account_id IS UNIQUE;

CREATE CONSTRAINT transaction_id_unique IF NOT EXISTS
FOR (t:Transaction) REQUIRE t.transaction_id IS UNIQUE;

// ── Indexes (speeds up queries) ───────────────────────────────────────────
// Like adding an index to a DataFrame column for faster filtering.

CREATE INDEX account_fraud_flag IF NOT EXISTS
FOR (a:Account) ON (a.is_flagged);

CREATE INDEX transaction_verdict IF NOT EXISTS
FOR (t:Transaction) ON (t.verdict);

CREATE INDEX transaction_timestamp IF NOT EXISTS
FOR (t:Transaction) ON (t.timestamp);

// ── Sample data to verify setup ───────────────────────────────────────────
// Creates 3 accounts and 2 transactions to test the graph is working.
// DELETE THIS in production — it's just for verification.

MERGE (priya:Account {
    account_id   : "C_PRIYA_STUDENT_001",
    account_type : "STUDENT",
    age_days     : 180,
    is_flagged   : false,
    created_at   : datetime()
})

MERGE (mule:Account {
    account_id   : "C_UNKNOWN_RECIPIENT_999",
    account_type : "UNKNOWN",
    age_days     : 30,
    is_flagged   : true,
    created_at   : datetime()
})

MERGE (criminal:Account {
    account_id   : "C_CRIMINAL_COLLECTOR",
    account_type : "UNKNOWN",
    age_days     : 15,
    is_flagged   : true,
    created_at   : datetime()
})

// Create transaction edges
MERGE (priya)-[:TRANSFERRED_TO {
    transaction_id : "TEST_TXN_001",
    amount         : 92000.0,
    verdict        : "DENY",
    timestamp      : datetime("2026-01-15T23:45:00Z"),
    is_fraud       : true
}]->(mule)

MERGE (mule)-[:TRANSFERRED_TO {
    transaction_id : "TEST_TXN_002",
    amount         : 91500.0,
    verdict        : "DENY",
    timestamp      : datetime("2026-01-15T23:52:00Z"),
    is_fraud       : true
}]->(criminal);

// ── Verify the graph was created ──────────────────────────────────────────
// Run this query to see your graph:
// MATCH (a:Account)-[r:TRANSFERRED_TO]->(b:Account) RETURN a, r, b

// ── Key queries used by the detection worker ──────────────────────────────

// 1. Find all accounts connected to a suspicious recipient
//    (run this to see if a recipient is part of a fraud network)
// MATCH (target:Account {account_id: $recipient_id})
// MATCH (other:Account)-[:TRANSFERRED_TO]->(target)
// WHERE other.is_flagged = true
// RETURN count(other) as flagged_senders

// 2. Find the community a recipient belongs to (money laundering ring)
// MATCH path = (a:Account)-[:TRANSFERRED_TO*1..3]->(target:Account {account_id: $recipient_id})
// RETURN path LIMIT 25

// 3. Check if recipient has received from many different senders recently
// MATCH (sender:Account)-[t:TRANSFERRED_TO]->(recipient:Account {account_id: $recipient_id})
// WHERE t.timestamp > datetime() - duration({days: 30})
// RETURN count(DISTINCT sender) as unique_senders_30d,
//        sum(t.amount) as total_received_30d
