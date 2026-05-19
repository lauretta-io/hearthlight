# Demo Trigger Connectors Runbook

This runbook covers the localhost demo path for routing Hearthlight triggers to notification connectors and visible action connectors such as Philips Hue, music APIs, and robot controllers.

## Localhost Steps

1. Start Hearthlight locally and open the frontend at `http://localhost:3000`.
2. Start a local action receiver in another terminal:

```bash
python3 - <<'PY'
from http.server import BaseHTTPRequestHandler, HTTPServer

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        print(f"\n{self.path}\n{body}\n")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

HTTPServer(("localhost", 8790), Handler).serve_forever()
PY
```

3. Open `Connectors`.
4. Configure Telegram:
   - Add a Telegram subscription.
   - Enter the bot token, chat ID, optional label, and enable it.
   - Save, then use `Send Test Message`.
5. Configure the third-party API connector:
   - Add an endpoint.
   - Set `Base URL` to the local Claude-compatible server, for example `http://localhost:8787/v1/messages`.
   - Add an optional auth token, timeout, retry count, and enable it.
   - Save, then use `Send Test Payload`.
6. Configure action connectors:
   - Add `Philips Hue`, `Music API`, or `Robot Action`.
   - Set `Action URL` to a local action receiver, for example `http://localhost:8790/actions`.
   - Pick a command such as `flash_scene`, `play_alert`, or `move_to_zone`.
   - Set a target such as `lobby-light`, `demo-speaker`, or `demo-zone`.
   - Add optional JSON parameters, save, then use `Send Test Action`.
7. Open `Rules`.
8. Click `Load Demo Presets`.
9. For each demo trigger, choose source targets and delivery targets. Select any mix of notification and action connectors for fan-out.
10. Click `Save Rules`.
11. Use `Fire Demo Trigger` for a manual end-to-end showcase, or run the pipeline to emit real anomaly, unattended bag, loitering, or alert-rule triggers.
12. Open `Monitoring` and check `Resource Events` for connector delivery status and errors.

## API Contracts

Connector config:

- `GET /settings/claude-api-connectors`
- `PUT /settings/claude-api-connectors`
- `POST /settings/claude-api-connectors/test`
- `GET /settings/action-connectors`
- `PUT /settings/action-connectors`
- `POST /settings/action-connectors/test`
- `GET /settings/claude-anomaly-model`
- `PUT /settings/claude-anomaly-model`
- `POST /settings/claude-anomaly-model/test`

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

`PUT /settings/action-connectors` accepts:

```json
[
  {
    "id": 71,
    "enabled": true,
    "action_type": "philips_hue",
    "connector_label": "Demo Hue",
    "base_url": "http://localhost:8790/actions",
    "auth_token": "optional-secret",
    "command": "flash_scene",
    "target": "lobby-light",
    "parameters": {
      "color": "red",
      "brightness": 90
    },
    "timeout_seconds": 10,
    "retry_count": 1
  }
]
```

`action_type` must be one of `philips_hue`, `music_api`, or `robot_action`. The payload is intentionally generic so a local demo receiver can translate it into Hue bridge calls, music playback commands, or robot controller commands.

Trigger rules:

- `GET /settings/trigger-rules`
- `PUT /settings/trigger-rules`
- `POST /demo/triggers/fire`

Trigger rules use `delivery_target_ids` to route each trigger to one or more saved connector endpoints. For the new trigger-rules API, an empty list means no connector is selected. Legacy/default alert-rule flows that do not set `delivery_target_ids` keep the existing fan-out behavior to all enabled connectors.

Example trigger rule:

```json
{
  "trigger_key": "unattended_bag_trigger",
  "source_ids": [1],
  "enabled": true,
  "rule_label": "Lobby bag demo",
  "rule_kind": "detector",
  "signal_family": "detector",
  "target_key": "unattended_bag_trigger",
  "min_confidence": 0.5,
  "anomaly_cutoff": null,
  "alert_level": "high",
  "delivery_target_ids": [41, 61],
  "metadata": {}
}
```

Manual fire request:

```json
{
  "trigger_key": "manual_trigger",
  "display_title": "Manual Demo Trigger",
  "alert_level": "low",
  "source_id": null,
  "delivery_target_ids": [61, 71],
  "metadata": {
    "operator": "localhost-demo"
  }
}
```

Action connector payload shape:

```json
{
  "schema": "hearthlight.action.v1",
  "source": "hearthlight",
  "action": {
    "type": "philips_hue",
    "command": "flash_scene",
    "target": "lobby-light",
    "parameters": {
      "color": "red",
      "brightness": 90
    }
  },
  "trigger": {
    "id": "MANUAL_TRIGGER-0",
    "type": "manual_trigger",
    "display_title": "Manual Demo Trigger",
    "run_identifier": "run-123",
    "source_label": "Lobby",
    "camera_id": 0,
    "alert_level": "Low",
    "occurred_at": "2026-05-19T12:00:00",
    "metadata": {
      "operator": "localhost-demo"
    }
  }
}
```

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

## Claude-Compatible Anomaly Model

The third-party API connector above is a trigger delivery target. The Claude-compatible anomaly model is different: it is selected as an `anomaly_stage_2` model and called before an anomaly event is produced.

Local mock server:

```bash
python3 - <<'PY'
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        print(f"\n{self.path}\n{body}\n")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "content": [{
                "type": "text",
                "text": json.dumps({
                    "schema": "hearthlight.anomaly_response.v1",
                    "promote": True,
                    "category": "anomaly_event",
                    "title": "Mock Claude Anomaly",
                    "score": 0.91,
                    "reasoning": "The mock server promoted the candidate for localhost verification.",
                    "visible_items": ["person", "bag"],
                    "visible_activities": ["unexpected activity"]
                })
            }]
        }).encode("utf-8"))

HTTPServer(("localhost", 8788), Handler).serve_forever()
PY
```

Exact localhost verification:

1. Start the mock server above.
2. Open `http://localhost:3000`, then open `Connectors`.
3. In `Claude-Compatible Anomaly Model`, set `Base URL` to `http://localhost:8788/v1/messages`, set any model name, enable it, and click `Send Test Anomaly Request`.
4. Click `Save Anomaly Model API`.
5. Open `Model Library`, mount `Claude-Compatible Anomaly API` under `Anomaly Detection` if it is not already mounted.
6. Open `Sources` or `Model Bindings` and select `Claude-Compatible Anomaly API` for `Anomaly Detection`.
7. Start the runtime with a saved source. When stage 1 emits a candidate, the anomaly worker posts to the mock server. A response with `"promote": true` is converted to a Hearthlight anomaly event.

Config payload:

```json
{
  "enabled": true,
  "base_url": "http://localhost:8788/v1/messages",
  "auth_token": "optional-secret",
  "model_name": "claude-compatible-anomaly",
  "timeout_seconds": 10,
  "retry_count": 1,
  "prompt_template": "Evaluate the Hearthlight anomaly candidate and return JSON."
}
```

Anomaly request payload:

```json
{
  "model": "claude-compatible-anomaly",
  "max_tokens": 512,
  "messages": [
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "Prompt text plus Candidate context JSON"
        }
      ]
    }
  ],
  "metadata": {
    "source": "hearthlight",
    "purpose": "anomaly_detection",
    "schema": "hearthlight.anomaly_request.v1",
    "event_id": "heuristic_presence_stage_1:1:42:presence_resume",
    "source_id": 1,
    "camera_id": 0,
    "frame_id": 42,
    "candidate_category": "presence_resume"
  },
  "hearthlight": {
    "schema": "hearthlight.anomaly_request.v1",
    "source": "hearthlight",
    "candidate": {
      "event_id": "heuristic_presence_stage_1:1:42:presence_resume",
      "run_id": "run-123",
      "source_id": 1,
      "camera_id": 0,
      "frame_id": 42,
      "stage_1_model_key": "heuristic_presence_stage_1",
      "stage_2_model_key": "claude_compatible_stage_2",
      "category": "presence_resume",
      "score": 0.72,
      "reasoning": "Observed tracked objects after inactivity.",
      "visible_items": ["person", "bag"],
      "visible_activities": ["presence resume"],
      "asset_references": []
    },
    "prompt": {
      "template": "Evaluate the Hearthlight anomaly candidate and return JSON.",
      "anomaly_object_list": ["bag"],
      "anomaly_activity_list": ["loitering"]
    }
  }
}
```

Expected anomaly response:

```json
{
  "schema": "hearthlight.anomaly_response.v1",
  "promote": true,
  "category": "unattended_bag",
  "title": "Unattended Bag",
  "score": 0.91,
  "reasoning": "A bag remains visible without an owner nearby.",
  "visible_items": ["bag"],
  "visible_activities": ["standing nearby"]
}
```

Claude-style responses are also accepted when the JSON object is returned inside `content[].text`. If `promote` is false, no anomaly event is emitted. Timeouts and request failures are logged and skipped so one failed external model call does not crash the anomaly pipeline.
