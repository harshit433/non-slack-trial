from slack_bolt import App
from slack_bolt.adapter.fastapi import SlackRequestHandler
from fastapi import FastAPI, Request
import requests, os
import logging

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
        # res = requests.post(NOX_BACKEND_URL, json={"user": user, "message": text}, timeout=10)
        # reply = res.json().get("reply", "I'm thinking...")
        reply = "I'm thinking..."
    except Exception as e:
        logger.error(f"Error contacting backend: {e}")
        reply = "Sorry, I couldn't reach the NoX brain right now."

    say(reply)

@slack_app.event("message")
def handle_message_events(body, logger):
    """Handle all message events (including DMs and channel messages)"""
    event = body.get("event", {})
    logger.info(f"Received message event: {event.get('type')} from {event.get('user', 'unknown')}")
    
    # Skip bot messages and messages that are app mentions (handled separately)
    if event.get("subtype") == "bot_message":
        logger.info("Skipping bot message")
        return
    
    # Only respond to direct messages (DMs) - app mentions are handled by handle_app_mention
    if event.get("channel_type") == "im":
        logger.info("Received DM, but not responding (only app mentions are handled)")
        # Uncomment below if you want to handle DMs
        # user = event.get("user")
        # text = event.get("text", "")
        # logger.info(f"DM from {user}: {text}")

# Slack events endpoint
@api.post("/slack/events")
async def endpoint(req: Request):
    try:
        return await handler.handle(req)
    except Exception as e:
        logging.error(f"Error handling Slack event: {e}")
        raise

# Simple health check
@api.get("/")
def health():
    return {"status": "ok"}
