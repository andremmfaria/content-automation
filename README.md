# Social Content Automation

Operator guide for the weekly DEV.to + LinkedIn publishing pipeline.

---

## Architecture

```
OpenClaw cron (Tue 14:00 UTC)
        │
        ▼
run_weekly.sh
  ├── publish_devto.py   → Forem API → DEV.to article published
  └── curate_devto.py    → DEV.to RSS + API → curation JSON
        │
        ▼  (agent turn, same cron job)
OpenClaw agent reads curation JSON
  └── drafts LinkedIn post text
        │
        ▼
queue_buffer.py → Buffer GraphQL API → post created as DRAFT
        │
        ▼  (manual step)
You review + approve draft in Buffer UI
        │
        ▼
Buffer posts to LinkedIn via its approved OAuth channel
```

**Important:** Direct browser automation of LinkedIn is prohibited by
LinkedIn's Terms of Service and is NOT used here. All LinkedIn publishing
goes through Buffer's approved API integration with your connected LinkedIn
channel.

---

## One-time setup

### 1. DEV.to API key

1. Log in to dev.to → Settings → Extensions.
2. Under "DEV Community API Keys", generate a new key.
3. Copy the key value.

### 2. Buffer access token

1. Create a Buffer developer app at <https://developers.buffer.com>.
2. Complete the OAuth 2.0 flow for your Buffer account.
3. Exchange the authorization code for an access token.
4. The token grants access to all channels connected to your Buffer account.

### 3. Buffer LinkedIn channel id

Run this query against the Buffer GraphQL API (replace `YOUR_TOKEN`):

```bash
curl -s https://api.buffer.com \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ channels { id service username } }"}' \
  | python3 -m json.tool
```

Find the object where `"service": "linkedin"` and copy its `"id"` value.

### 4. Set environment variables

```bash
cp .env.example .env
# Edit .env and fill in the three required values:
#   DEVTO_API_KEY
#   BUFFER_ACCESS_TOKEN
#   BUFFER_LINKEDIN_CHANNEL_ID
```

Load the vars before running scripts:

```bash
set -a && source .env && set +a
```

### 5. Install the OpenClaw cron routine

1. Open `openclaw-cron.example.json`.
2. Replace `/path/to/content-automation` with your actual repo path.
3. Replace `YOUR_OPENCLAW_CHANNEL_ID` with your notification channel id.
4. Verify the schema matches your OpenClaw instance (see Limitations below).
5. Register the job via the OpenClaw admin UI or API.

---

## Weekly schedule

**Tuesday 14:00 UTC** = 10:00 ET / 16:00 CEST.

This timing targets the LinkedIn golden hour: posts published Tue–Thu
between 08:00–10:00 local business time typically receive the highest
early engagement. LinkedIn's algorithm weights interactions in the first
60–90 minutes heavily, so being online to reply to comments during that
window compounds reach. Adjust the cron expression (`0 14 * * 2`) to
match your own analytics once you have data.

---

## Human-in-the-loop flow

1. The cron job runs automatically on Tuesday at 14:00 UTC.
2. `run_weekly.sh` publishes the queued DEV.to article and fetches curation candidates.
3. The OpenClaw agent drafts a LinkedIn post and calls `queue_buffer.py`.
4. The post lands in Buffer as a **draft** — it is NOT auto-published.
5. You receive a notification (via your OpenClaw delivery channel).
6. Review the draft in the Buffer dashboard; edit if needed; click **Approve**.
7. Buffer publishes to LinkedIn at the scheduled time (or immediately if
   you approve after the scheduled time).
8. Show up for the first 60 minutes to reply to comments.

---

## Script reference

### `publish_devto.py`

Publish or update a DEV.to article from a Markdown file with YAML frontmatter.

```bash
# Dry-run (no request sent)
python3 publish_devto.py --file post.md --dry-run

# Create draft
python3 publish_devto.py --file post.md

# Create and publish immediately
python3 publish_devto.py --file post.md --publish

# Update existing article
python3 publish_devto.py --file post.md --id 1234567 --publish
```

Rate limit: Forem enforces approximately 10 create requests per 30 seconds.
Space calls via the queue mechanism rather than bulk-creating.

### `curate_devto.py`

Fetch recent DEV.to articles for given tags. No authentication required.

```bash
# Default tags (ai, security, devops), both RSS + API sources
python3 curate_devto.py

# Custom tags, API only
python3 curate_devto.py --tags kubernetes platform-engineering --source api

# Dry-run
python3 curate_devto.py --dry-run
```

### `queue_buffer.py`

Queue a LinkedIn post in Buffer as a draft.

```bash
# Dry-run
python3 queue_buffer.py \
  --text "Your post text here" \
  --link "https://dev.to/..." \
  --dry-run

# Live (requires env vars)
python3 queue_buffer.py \
  --text "Your post text here" \
  --link "https://dev.to/..." \
  --at "2026-06-24T14:00:00Z"
```

### `run_weekly.sh`

Orchestration entrypoint. Called by the cron job.

```bash
# Dry-run
DRY_RUN=1 bash run_weekly.sh

# Live
bash run_weekly.sh
```

---

## Limitations / Verify against your instance

The Buffer items below were VERIFIED LIVE against the GraphQL API
(2026-06); the remaining items still need confirmation against your
Forem account and OpenClaw instance.

1. **Buffer LinkedIn first comment — VERIFIED, paid-plan gated** (`queue_buffer.py`).
   The correct path is `metadata.linkedin.firstComment` (NOT a top-level
   `metadata.firstComment`). Buffer rejects it on free plans with
   `"LinkedIn first comment requires a paid plan"`. The script therefore
   appends the link to the post body BY DEFAULT and only uses the first
   comment when you pass `--first-comment` (paid plan required).

2. **Buffer `schedulingType` enum — VERIFIED** (`queue_buffer.py`).
   Enum values are `notification` | `automatic`. The script uses
   `automatic`, which works.

3. **Buffer `mode` + draft — VERIFIED** (`queue_buffer.py`).
   Enum is `addToQueue` | `shareNow` | `shareNext` | `customScheduled`.
   `addToQueue` + `saveToDraft: true` creates a draft (returns
   `PostActionSuccess` with `status: draft`); `customScheduled` + `dueAt`
   is used when a time is given. Endpoint `https://api.buffer.com` and
   Bearer auth confirmed working.

4. **Forem `tags` field type** (`publish_devto.py`).
   The Forem API docs describe `tags` as a `string` (comma-separated).
   The script passes a list (`["ai", "security"]`); confirm the API
   accepts a JSON array or convert to a comma-separated string if needed.

5. **OpenClaw cron job schema** (`openclaw-cron.example.json`).
   The template is modelled on general OpenClaw cron-job conventions.
   Field names (`command`, `agent_turn`, `retry`, `delivery`, etc.) must
   be verified against your specific OpenClaw instance version.

6. **Forem create rate limit** (`publish_devto.py`).
   The 10 requests / 30 s figure comes from community documentation, not
   the official API reference (which does not publish rate limits). Verify
   via the `X-RateLimit-*` response headers on your first live call.
