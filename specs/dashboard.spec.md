# dashboard.spec.md — Dashboard Module Specification
## Cycle-Safe Referral Engine v1.0

---

## Feature: Real-Time System Monitoring Dashboard

### Goal
Provide a unified React dashboard for monitoring system health, referral activity, fraud events, graph structure, and reward distribution. The dashboard aggregates data from PostgreSQL (metrics), Neo4j (graph visualization), and a WebSocket event stream (live activity feed) into a cohesive operator interface.

---

## Requirements

### Functional
- FR-D-01: Display key system metrics (users, referrals, rewards, fraud) with live updates
- FR-D-02: Render interactive referral graph for any user (up to 3 levels, configurable)
- FR-D-03: List rejected/fraud referrals with reasons, filterable and paginated
- FR-D-04: Real-time activity feed via WebSocket showing last 50 events
- FR-D-05: Allow graph exploration — click a node to recenter and re-render
- FR-D-06: Support time-range filtering on metrics (last 1h, 24h, 7d, 30d)
- FR-D-07: Show system health status (database connectivity, cache status)
- FR-D-08: Display per-fraud-reason breakdown

### Non-Functional
- NFR-D-01: Metrics panel loads in <100ms (cached aggregates)
- NFR-D-02: Graph view renders in <500ms for 3-level tree
- NFR-D-03: WebSocket reconnects automatically on disconnect
- NFR-D-04: Dashboard is read-only (no mutations except admin review actions)

---

## API Contract

### GET /api/v1/dashboard/metrics

**Query:** `?window=24h` (1h | 24h | 7d | 30d)

**Response 200:**
```json
{
  "success": true,
  "data": {
    "window": "24h",
    "generated_at": "2026-03-29T10:00:00Z",
    "users": {
      "total": 142850,
      "new_in_window": 1247,
      "active": 98230
    },
    "referrals": {
      "total": 89421,
      "valid": 81234,
      "rejected": 6432,
      "fraud": 1755,
      "in_window": 847,
      "valid_rate": 0.908
    },
    "rewards": {
      "total_issued": 284750,
      "amount_distributed": 284750.50,
      "pending_amount": 1240.00
    },
    "fraud": {
      "total_events": 1755,
      "by_reason": {
        "SELF_REFERRAL": 310,
        "CYCLE_DETECTED": 89,
        "VELOCITY_EXCEEDED": 512,
        "DUPLICATE_IP": 198,
        "DUPLICATE_DEVICE": 92,
        "SUSPICIOUS_PATTERN": 46
      },
      "unreviewed_high_severity": 12
    },
    "system": {
      "graph_node_count": 142850,
      "graph_edge_count": 89421,
      "avg_referral_latency_ms": 42,
      "cache_hit_rate": 0.94
    }
  }
}
```

---

### GET /api/v1/dashboard/graph/{user_id}

**Query:** `?depth=3`

**Response 200:**
```json
{
  "success": true,
  "data": {
    "root_user_id": "uuid",
    "depth": 3,
    "nodes": [
      {
        "id": "uuid",
        "username": "alice_wonder",
        "referral_count": 14,
        "is_root": true,
        "depth_from_root": 0
      },
      {
        "id": "uuid",
        "username": "bob_builder",
        "referral_count": 3,
        "is_root": false,
        "depth_from_root": 1
      }
    ],
    "edges": [
      {
        "source": "uuid_bob",
        "target": "uuid_alice",
        "referral_id": "uuid",
        "created_at": "2026-03-29T09:00:00Z"
      }
    ],
    "stats": {
      "total_nodes": 22,
      "total_edges": 21,
      "max_depth_found": 3
    }
  }
}
```

---

### GET /api/v1/dashboard/fraud-panel

**Query:** `?page=1&limit=20&reason=CYCLE_DETECTED&severity=3`

**Response 200:**
```json
{
  "success": true,
  "data": {
    "events": [
      {
        "id": "uuid",
        "user": { "id": "uuid", "username": "charlie" },
        "reason": "CYCLE_DETECTED",
        "severity": 3,
        "severity_label": "HIGH",
        "referral_attempt": {
          "attempted_referrer": { "id": "uuid", "username": "alice" },
          "timestamp": "2026-03-29T09:55:00Z"
        },
        "metadata": { "cycle_path_length": 3 },
        "reviewed": false,
        "created_at": "2026-03-29T09:55:00Z"
      }
    ],
    "pagination": { "page": 1, "limit": 20, "total": 38 },
    "summary": {
      "total_unreviewed": 38,
      "high_severity_unreviewed": 12
    }
  }
}
```

---

### GET /api/v1/dashboard/activity-feed

**Query:** `?limit=50` (initial load)

**Response 200:**
```json
{
  "success": true,
  "data": {
    "events": [
      {
        "id": "uuid",
        "event_type": "REFERRAL_CREATED",
        "label": "Bob referred by Alice",
        "actor": { "id": "uuid", "username": "alice" },
        "target": { "id": "uuid", "username": "bob" },
        "payload": { "referral_id": "uuid", "status": "VALID" },
        "created_at": "2026-03-29T10:00:00Z"
      },
      {
        "id": "uuid",
        "event_type": "FRAUD_FLAGGED",
        "label": "Cycle attempt blocked",
        "actor": { "id": "uuid", "username": "charlie" },
        "target": null,
        "payload": { "reason": "CYCLE_DETECTED", "severity": 3 },
        "created_at": "2026-03-29T09:59:50Z"
      }
    ]
  }
}
```

---

### WebSocket: ws://host/ws/dashboard

**Protocol:** JSON messages over WebSocket

**Client → Server (subscribe):**
```json
{ "action": "subscribe", "channel": "activity_feed" }
```

**Server → Client (event push):**
```json
{
  "type": "event",
  "channel": "activity_feed",
  "data": {
    "id": "uuid",
    "event_type": "REFERRAL_CREATED",
    "label": "Dave referred by Carol",
    "actor": { "id": "uuid", "username": "carol" },
    "target": { "id": "uuid", "username": "dave" },
    "payload": { "referral_id": "uuid", "status": "VALID" },
    "created_at": "2026-03-29T10:01:00Z"
  }
}
```

**Server → Client (metrics update, every 30s):**
```json
{
  "type": "metrics_update",
  "data": {
    "users_total": 142851,
    "referrals_valid": 81235,
    "fraud_events_total": 1756
  }
}
```

**Server → Client (heartbeat, every 15s):**
```json
{ "type": "ping", "timestamp": "2026-03-29T10:01:15Z" }
```

---

## Data Model

### Dashboard Metrics Cache (Redis)

```
Key: dashboard:metrics:{window}
Type: String (JSON blob)
TTL: 30s
Content: Full metrics payload for the given window (1h|24h|7d|30d)
Refresh: Background Celery task every 30s
```

```python
# Background metrics refresh task
@celery.task
async def refresh_dashboard_metrics():
    for window in ['1h', '24h', '7d', '30d']:
        metrics = await compute_metrics(window)
        await redis.setex(
            f"dashboard:metrics:{window}",
            30,
            json.dumps(metrics)
        )
```

### Activity Events (PostgreSQL + Redis pub/sub)

```sql
-- activity_events defined in global.spec.md
-- Dashboard reads from this table for initial load
-- New events are also published to Redis channel for WebSocket

-- Efficient recent events query
SELECT ae.*, 
       u1.username AS actor_username,
       u2.username AS target_username
FROM activity_events ae
LEFT JOIN users u1 ON u1.id = ae.actor_id
LEFT JOIN users u2 ON u2.id = ae.target_id
ORDER BY ae.created_at DESC
LIMIT 50;
```

### Neo4j Graph Query for Dashboard View

```cypher
-- Fetch all nodes and edges for a user's subtree (downward, up to depth D)
MATCH (root:User {id: $user_id})
OPTIONAL MATCH path = (child:User)-[:REFERRED*1..$depth]->(root)
WITH root, COLLECT(DISTINCT nodes(path)) AS node_sets,
     COLLECT(DISTINCT relationships(path)) AS rel_sets
UNWIND node_sets AS node_list
UNWIND node_list AS n
WITH root, COLLECT(DISTINCT n) AS all_nodes, rel_sets
UNWIND rel_sets AS rel_list
UNWIND rel_list AS r
RETURN all_nodes, COLLECT(DISTINCT r) AS all_rels
```

---

## Backend Architecture

### Metrics Computation SQL

```sql
-- Users metrics
SELECT
  COUNT(*) FILTER (WHERE TRUE) AS total_users,
  COUNT(*) FILTER (WHERE created_at > NOW() - $window) AS new_in_window,
  COUNT(*) FILTER (WHERE status = 'ACTIVE') AS active_users
FROM users;

-- Referrals metrics
SELECT
  COUNT(*) AS total,
  COUNT(*) FILTER (WHERE status = 'VALID') AS valid,
  COUNT(*) FILTER (WHERE status = 'REJECTED') AS rejected,
  COUNT(*) FILTER (WHERE status = 'FRAUD') AS fraud,
  COUNT(*) FILTER (WHERE created_at > NOW() - $window) AS in_window,
  ROUND(
    COUNT(*) FILTER (WHERE status = 'VALID')::NUMERIC / NULLIF(COUNT(*), 0),
    3
  ) AS valid_rate
FROM referrals;

-- Fraud breakdown
SELECT reason, COUNT(*) AS count
FROM fraud_events
GROUP BY reason;

-- Average latency (resolved_at - created_at)
SELECT ROUND(
  AVG(EXTRACT(EPOCH FROM (resolved_at - created_at)) * 1000)
) AS avg_latency_ms
FROM referrals
WHERE status = 'VALID'
  AND resolved_at IS NOT NULL
  AND created_at > NOW() - INTERVAL '1 hour';
```

### WebSocket Server (FastAPI)

```python
from fastapi import WebSocket
import asyncio
import redis.asyncio as aioredis

active_connections: List[WebSocket] = []

@app.websocket("/ws/dashboard")
async def dashboard_ws(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    
    # Start Redis pub/sub listener for this connection
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("activity_events")
    
    try:
        async def listen_redis():
            async for message in pubsub.listen():
                if message['type'] == 'message':
                    await websocket.send_text(message['data'])
        
        async def heartbeat():
            while True:
                await asyncio.sleep(15)
                await websocket.send_json({
                    "type": "ping",
                    "timestamp": datetime.utcnow().isoformat()
                })
        
        # Run both concurrently
        await asyncio.gather(listen_redis(), heartbeat())
    
    except WebSocketDisconnect:
        active_connections.remove(websocket)
        await pubsub.unsubscribe("activity_events")


# Publishing events (called by referral/fraud services)
async def publish_activity_event(event: ActivityEvent):
    # Write to PG
    await db.execute("""
        INSERT INTO activity_events (id, event_type, actor_id, target_id, payload)
        VALUES ($1, $2, $3, $4, $5)
    """, event.id, event.event_type, event.actor_id, event.target_id,
         json.dumps(event.payload))
    
    # Publish to Redis channel (WebSocket clients receive)
    await redis_client.publish(
        "activity_events",
        json.dumps({
            "type": "event",
            "channel": "activity_feed",
            "data": event.to_dict()
        })
    )
```

---

## Frontend Architecture (React)

### Component Tree

```
<App>
  <DashboardLayout>
    <Sidebar navigation />
    <MainContent>
      ├── <MetricsPanel>
      │     ├── <StatCard title="Total Users" />
      │     ├── <StatCard title="Valid Referrals" />
      │     ├── <StatCard title="Fraud Events" />
      │     ├── <StatCard title="Rewards Distributed" />
      │     └── <TimeRangeSelector />
      │
      ├── <GraphView>
      │     ├── <UserSearchBar />
      │     ├── <ForceDirectedGraph nodes edges />  (D3 or react-force-graph)
      │     └── <NodeDetailPanel />
      │
      ├── <FraudPanel>
      │     ├── <FraudFilter reason severity reviewed />
      │     ├── <FraudEventTable />
      │     └── <FraudEventDetail />
      │
      └── <ActivityFeed>
            ├── <WebSocketStatus />
            └── <EventList events />
    </MainContent>
  </DashboardLayout>
</App>
```

### WebSocket Client Hook

```typescript
function useDashboardWebSocket() {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    function connect() {
      const ws = new WebSocket(`wss://${host}/ws/dashboard`);
      
      ws.onopen = () => {
        setConnected(true);
        ws.send(JSON.stringify({ action: 'subscribe', channel: 'activity_feed' }));
      };
      
      ws.onmessage = (msg) => {
        const data = JSON.parse(msg.data);
        if (data.type === 'event') {
          setEvents(prev => [data.data, ...prev].slice(0, 50));
        }
        if (data.type === 'metrics_update') {
          // Update live metrics counters
        }
      };
      
      ws.onclose = () => {
        setConnected(false);
        setTimeout(connect, 3000); // Auto-reconnect
      };
      
      wsRef.current = ws;
    }
    
    connect();
    return () => wsRef.current?.close();
  }, []);

  return { events, connected };
}
```

### Graph Visualization

```typescript
// Uses react-force-graph or D3 force simulation
// Node color encoding:
//   Root user: #3B82F6 (blue)
//   Direct referral (depth 1): #10B981 (green)
//   Depth 2: #F59E0B (yellow)
//   Depth 3: #6B7280 (gray)
//
// Edge: directed arrow, labeled with referral date
// Click node: fetch /dashboard/graph/{node_id} and re-render
// Hover node: tooltip with username, referral count, join date
```

---

## Edge Cases

| Case | Handling |
|---|---|
| WebSocket connection drops | Client auto-reconnects after 3s with exponential backoff |
| Metrics cache miss | Compute synchronously from DB; cache result for 30s |
| Graph request for user with 0 referrals | Return single root node, empty edges array |
| Graph request for very popular user (1000+ referrals) | Depth-limited query prevents overload; warn in UI |
| Activity feed empty (new system) | Return empty array, UI shows "No events yet" |
| Multiple dashboard tabs open | Each tab maintains its own WebSocket; server broadcasts to all |
| Neo4j down during graph view request | Return 503 with message; UI shows "Graph temporarily unavailable" |

---

## Constraints

- C-D-01: Metrics endpoint must serve from cache (max 30s stale); never block on real-time computation
- C-D-02: Graph view depth is capped at 5 levels via query param validation
- C-D-03: Activity feed via WebSocket only; HTTP polling for activity feed is not supported
- C-D-04: Dashboard endpoints are read-only (no data mutations, except fraud review)
- C-D-05: WebSocket server must handle 1000 concurrent dashboard connections

---

## Acceptance Criteria

- AC-D-01: Metrics panel loads in <100ms with accurate counts for selected time window
- AC-D-02: Graph view renders referral tree for a user within 500ms, correctly structured
- AC-D-03: Clicking a node in the graph view re-renders the tree centered on that node
- AC-D-04: Fraud panel shows all unreviewed high-severity events by default
- AC-D-05: Activity feed receives new events via WebSocket within 500ms of occurrence
- AC-D-06: WebSocket reconnects automatically after disconnect, without page refresh
- AC-D-07: Metrics update in real time (every 30s) without user interaction
- AC-D-08: Dashboard remains functional (degraded mode) when Neo4j is unavailable (graph view shows error; metrics still work)
- AC-D-09: 1000 concurrent WebSocket connections do not degrade API response times
