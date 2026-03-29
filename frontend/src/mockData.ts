export const mockMetrics = {
  window: "24h",
  generated_at: new Date().toISOString(),
  users: {
    total: 142850,
    new_in_window: 1247,
    active: 98230
  },
  referrals: {
    total: 89421,
    valid: 81234,
    rejected: 6432,
    fraud: 1755,
    in_window: 847,
    valid_rate: 0.908
  },
  rewards: {
    total_issued: 284750,
    amount_distributed: 284750.50,
    pending_amount: 1240.00
  },
  fraud: {
    total_events: 1755,
    by_reason: {
      SELF_REFERRAL: 310,
      CYCLE_DETECTED: 89,
      VELOCITY_EXCEEDED: 512,
      DUPLICATE_IP: 198,
      DUPLICATE_DEVICE: 92,
      SUSPICIOUS_PATTERN: 46
    },
    unreviewed_high_severity: 12
  },
  system: {
    graph_node_count: 142850,
    graph_edge_count: 89421,
    avg_referral_latency_ms: 42,
    cache_hit_rate: 0.94
  }
};

export const mockFraudEvents = [
  {
    id: "uuid-1",
    user: { id: "u-1", username: "charlie" },
    reason: "CYCLE_DETECTED",
    severity: 3,
    severity_label: "HIGH",
    referral_attempt: { attempted_referrer: { id: "u-2", username: "alice" }, timestamp: new Date(Date.now() - 500000).toISOString() },
    metadata: { cycle_path_length: 3 },
    reviewed: false,
    created_at: new Date(Date.now() - 500000).toISOString()
  },
  {
    id: "uuid-2",
    user: { id: "u-3", username: "dave" },
    reason: "VELOCITY_EXCEEDED",
    severity: 2,
    severity_label: "MEDIUM",
    referral_attempt: { attempted_referrer: { id: "u-4", username: "eve" }, timestamp: new Date(Date.now() - 1500000).toISOString() },
    metadata: { limit: "10 per hour" },
    reviewed: true,
    created_at: new Date(Date.now() - 1500000).toISOString()
  },
  {
    id: "uuid-3",
    user: { id: "u-5", username: "mallory" },
    reason: "SUSPICIOUS_PATTERN",
    severity: 3,
    severity_label: "HIGH",
    referral_attempt: { attempted_referrer: { id: "u-6", username: "bob" }, timestamp: new Date(Date.now() - 3600000).toISOString() },
    metadata: { burst: true },
    reviewed: false,
    created_at: new Date(Date.now() - 3600000).toISOString()
  }
];

export const mockActivityFeed = Array.from({ length: 15 }, (_, i) => ({
  id: `event-${i}`,
  event_type: i % 4 === 0 ? 'FRAUD_FLAGGED' : 'REFERRAL_CREATED',
  label: i % 4 === 0 ? 'Cycle attempt blocked' : 'New referral link created',
  actor: { id: `u-${i}`, username: `user_${i}` },
  target: i % 4 === 0 ? null : { id: `t-${i}`, username: `target_${i}` },
  payload: i % 4 === 0 ? { reason: "CYCLE_DETECTED", severity: 3 } : { referral_id: `ref-${i}`, status: "VALID" },
  created_at: new Date(Date.now() - i * 60000).toISOString()
}));

export const mockGraphData = {
  nodes: [
    { id: "alice", group: 1, name: "Alice (Root)", val: 20 },
    { id: "bob", group: 2, name: "Bob", val: 10 },
    { id: "carol", group: 2, name: "Carol", val: 10 },
    { id: "dave", group: 3, name: "Dave", val: 5 },
    { id: "eve", group: 3, name: "Eve", val: 5 },
    { id: "frank", group: 3, name: "Frank", val: 5 }
  ],
  links: [
    { source: "bob", target: "alice" },
    { source: "carol", target: "alice" },
    { source: "dave", target: "bob" },
    { source: "eve", target: "bob" },
    { source: "frank", target: "carol" }
  ]
};
