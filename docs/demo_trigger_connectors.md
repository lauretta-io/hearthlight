# Demo Trigger Connectors Runbook

This runbook covers the localhost demo path for routing Hearthlight triggers to Telegram and the third-party Claude-compatible API connector.

## Localhost Steps

1. Start Hearthlight locally and open the frontend, usually `http://localhost:5173`.
2. Open `Connectors`.
3. Configure Telegram:
   - Add a Telegram subscription.
   - Enter the bot token, chat ID, optional label, and enable it.
   - Save, then use `Send Test Message`.
4. Configure the third-party API connector:
   - Add an endpoint.
   - Set `Base URL` to the local Claude-compatible server, for example `http://localhost:8787/v1/messages`.
   - Add an optional auth token, timeout, retry count, and enable it.
   - Save, then use `Send Test Payload`.
5. Open `Rules`.
6. Click `Load Demo Presets`.
7. For each demo trigger, choose source targets and delivery targets. Select both Telegram and the third-party API endpoint for fan-out.
8. Click `Save Rules`.
9. Use `Fire Demo Trigger` for a manual end-to-end showcase, or run the pipeline to emit real anomaly, unattended bag, loitering, or alert-rule triggers.
10. Open `Monitoring` and check `Resource Events` for connector delivery status and errors.

## API Contracts

Connector config:

- `GET /settings/claude-api-connectors`
- `PUT /settings/claude-api-connectors`
- `POST /settings/claude-api-connectors/test`

`PUT /settings/claude-api-connectors` accepts:

```json
[
  {
    "id": 1,
    "enabled": true,
    "connector_label": "Local Claude Demo",
    "base_url": "http://localhost:8787/v1/messages",
    "auth_token": "optional-secret",
    "timeout_seconds": 10,
    "retry_count": 1
  }
]
```

Saved secrets are redacted as `********` on read. Saving the redacted value preserves the existing secret.

Trigger rules:

- `GET /settings/trigger-rules`
- `PUT /settings/trigger-rules`
- `POST /demo/triggers/fire`

Trigger rules use `delivery_target_ids` to route each trigger to one or more saved connector endpoints. An empty `delivery_target_ids` list preserves the existing fan-out behavior to all enabled connectors.

Third-party API payload shape:

```json
{
  "model": "hearthlight-trigger-router",
  "max_tokens": 256,
  "messages": [
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "Hearthlight Trigger: ..."
        }
      ]
    }
  ],
  "metadata": {
    "source": "hearthlight",
    "trigger_id": "ALERT-12",
    "trigger_type": "alert_rule_trigger",
    "display_title": "Alert: bag",
    "run_identifier": "run-123",
    "source_label": "Lobby",
    "camera_id": 0,
    "alert_level": "High",
    "occurred_at": "2026-05-19T12:00:00"
  },
  "hearthlight": {
    "trigger_id": "ALERT-12",
    "trigger_type": "alert_rule_trigger",
    "display_title": "Alert: bag",
    "run_identifier": "run-123",
    "source_label": "Lobby",
    "camera_id": 0,
    "alert_level": "High",
    "occurred_at": "2026-05-19T12:00:00",
    "metadata": {}
  }
}
```
