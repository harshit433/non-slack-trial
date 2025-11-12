from slack_bolt import App
from slack_bolt.adapter.fastapi import SlackRequestHandler
from fastapi import FastAPI, Request
import requests, os
import logging
import sys

# Configure root logger
logging.basicConfig(
    level=logging.INFO,  # Or DEBUG for more details
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger("myapp")
logger.setLevel(logging.INFO)

logger.info("Logger initialized!")

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
            reply = "You said: " + text
            logger.info(f"Sending reply: {reply}")
        except Exception as e:
            logger.error(f"Error contacting backend: {e}")
            reply = "Sorry, I couldn't reach the NoX brain right now."

        say(reply)
        logger.info("Reply sent successfully")
    except Exception as e:
        logger.error(f"Error in handle_app_mention: {e}", exc_info=True)

@slack_app.event("message")
def handle_message_events(body, say, logger):
    """Handle all message events (including DMs and channel messages)"""
    try:
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
        
        # Handle direct messages (DMs)
        if event.get("channel_type") == "im":
            user = event.get("user")
            channel = event.get("channel")
            logger.info(f"Received DM from user {user} in channel {channel}: {text}")
            
            # Call NoX backend (same logic as app_mention)
            try:
                # res = requests.post(NOX_BACKEND_URL, json={"user": user, "message": text}, timeout=10)
                # reply = res.json().get("reply", "I'm thinking...")
                reply = "You said: " + event.get("text", "I'm thinking...")
                logger.info(f"Sending reply to DM: {reply}")
            except Exception as e:
                logger.error(f"Error contacting backend: {e}")
                reply = "Sorry, I couldn't reach the NoX brain right now."
            
            say(reply)
            logger.info("DM reply sent successfully")
            return
        
        # Log other message events (channel messages without mentions)
        logger.info(f"Received message event from {event.get('user', 'unknown')} in channel {event.get('channel', 'unknown')}")
    except Exception as e:
        logger.error(f"Error in handle_message_events: {e}", exc_info=True)

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
