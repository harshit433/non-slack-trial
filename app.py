from slack_bolt import App
from slack_bolt.adapter.fastapi import SlackRequestHandler
from fastapi import FastAPI, Request
import requests, os

# Load from environment
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET")
NOX_BACKEND_URL = os.getenv("NOX_BACKEND_URL", "https://your-nox-backend.onrender.com/api/process")

# Initialize Slack Bolt app
slack_app = App(
    token=SLACK_BOT_TOKEN,
    signing_secret=SLACK_SIGNING_SECRET
)

# FastAPI app
api = FastAPI()
handler = SlackRequestHandler(slack_app)

@slack_app.event("app_mention")
def handle_app_mention(body, say, logger):
    user = body["event"]["user"]
    text = body["event"]["text"]
    logger.info(f"Received mention from {user}: {text}")

    # Call NoX backend
    try:
        res = requests.post(NOX_BACKEND_URL, json={"user": user, "message": text}, timeout=10)
        reply = res.json().get("reply", "I'm thinking...")
    except Exception as e:
        logger.error(f"Error contacting backend: {e}")
        reply = "Sorry, I couldn't reach the NoX brain right now."

    say(reply)

# Slack events endpoint
@api.post("/slack/events")
async def endpoint(req: Request):
    return await handler.handle(req)

# Simple health check
@api.get("/")
def health():
    return {"status": "ok"}
