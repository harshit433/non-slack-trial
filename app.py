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
    try:
        event = body.get("event", {})
        user = event.get("user")
        text = event.get("text", "")
        channel = event.get("channel")
        
        logger.info(f"Received mention from user {user} in channel {channel}: {text}")

        # Call NoX backend
        try:
            # res = requests.post(NOX_BACKEND_URL, json={"user": user, "message": text}, timeout=10)
            # reply = res.json().get("reply", "I'm thinking...")
            reply = "I'm thinking..."
            logger.info(f"Sending reply: {reply}")
        except Exception as e:
            logger.error(f"Error contacting backend: {e}")
            reply = "Sorry, I couldn't reach the NoX brain right now."

        say(reply)
        logger.info("Reply sent successfully")
    except Exception as e:
        logger.error(f"Error in handle_app_mention: {e}", exc_info=True)

@slack_app.event("message")
def handle_message_events(body, logger):
    """Handle all message events (including DMs and channel messages)"""
    event = body.get("event", {})
    
    # Skip bot messages
    if event.get("subtype") == "bot_message":
        logger.debug("Skipping bot message")
        return
    
    # Skip messages that contain app mentions (these are handled by handle_app_mention)
    # App mentions will have the bot's user ID in the text
    text = event.get("text", "")
    if "<@" in text and ">" in text:
        logger.debug("Skipping message with app mention (handled by app_mention handler)")
        return
    
    logger.info(f"Received message event from {event.get('user', 'unknown')} in channel {event.get('channel', 'unknown')}")
    
    # Only log direct messages (DMs) - app mentions are handled by handle_app_mention
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
