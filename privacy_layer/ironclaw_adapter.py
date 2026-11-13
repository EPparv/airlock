"""Current IronClaw HTTPS MCP extension configuration, never a stdio claim.

This generates a reviewable data-only manifest. It does not publish an endpoint,
change host egress policy, install a package or include a credential value.
"""
import json
from urllib.parse import urlsplit
from .core import Denied


def manifest(endpoint='https://airlock.invalid/mcp'):
    if not isinstance(endpoint,str):raise Denied('Use a secured HTTPS MCP endpoint.')
    u=urlsplit(endpoint)
    if u.scheme!='https' or not u.hostname or u.username or u.password or u.query or u.fragment or u.path!='/mcp':
        raise Denied('Use an HTTPS endpoint ending in /mcp with no credentials, query or fragment.')
    return '''# REVIEW TEMPLATE: replace airlock.invalid with your secured MCP endpoint.
# No public endpoint is created by Airlock. Never expose the owner UI.
schema_version = "reborn.extension_manifest.v3"
id = "airlock"
name = "Airlock"
version = "0.1.0"
description = "Owner-controlled local context and approved private task results."
trust = "third_party"

[mcp]
origin_gate_matrix = { loop_run = "gated_unless_granted", product = "forbidden", automation = "forbidden" }
server = '''+json.dumps(endpoint)+'''
namespace = "airlock"
max_tools = 32
default_permission = "ask"
effects = ["network", "use_secret", "external_write"]

[[mcp.credentials]]
handle = "airlock_scoped_token"
vendor = "airlock"
scopes = []
injection = { type = "header", name = "authorization", prefix = "Bearer " }

[auth.airlock]
method = "api_key"
display_name = "Airlock scoped agent connection"
fields = [{ handle = "airlock_scoped_token", label = "Scoped agent token", secret = true }]
'''
