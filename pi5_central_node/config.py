# Configuration for Raspberry Pi 5 Central Server
# Must point at the SAME HiveMQ Cloud cluster as every Pi4 edge node's
# config.py (HIVEMQ_HOST/USERNAME/PASSWORD) — this is the only channel
# edge nodes use to reach the server (see federated_client.py, Claim 3).

NODE_ID = "pi5_central"

# ── HiveMQ Cloud ──────────────────────────
HIVEMQ_HOST = "xxxxxxxxxxxx.s1.eu.hivemq.cloud"   # ← same cluster URL as edge nodes
HIVEMQ_PORT = 8883
HIVEMQ_USERNAME = "river_central_client"           # ← separate device credential
HIVEMQ_PASSWORD = "CHANGE_ME"
HIVEMQ_USE_TLS = True
HIVEMQ_KEEPALIVE = 60
HIVEMQ_QOS = 1
HIVEMQ_CLIENT_ID = f"{NODE_ID}_hivemq"
HIVEMQ_MAX_PAYLOAD_BYTES = 20 * 1024 * 1024

# Wildcard subscriptions — one topic tree per zone, zone is dynamic so we
# subscribe with '+' to catch every zone_id an edge node registers under.
TOPIC_REGISTER_SUB       = "river/+/register"
TOPIC_HEARTBEAT_SUB      = "river/+/heartbeat"
TOPIC_DATA_SUB           = "river/+/data"
TOPIC_FED_SUBMIT_SUB     = "river/+/federation/submit"
TOPIC_LABEL_PROPOSAL_SUB = "river/+/label_discovery/proposal"

# Per-zone publish targets (fill in {zone_id})
TOPIC_FED_GLOBAL_PUB = "river/{zone_id}/federation/global"

# Broadcast to every zone (all edge nodes subscribe to this same topic)
TOPIC_LABEL_REGISTRY_PUB = "river/label_registry/global"

# Node considered stale/offline if no heartbeat within this many seconds
NODE_STALE_TIMEOUT = 60

# Federation
FED_MIN_NODES = 1   # aggregate as soon as this many zone updates arrive
