from slack_bolt import App
from slack_bolt.adapter.fastapi import SlackRequestHandler
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
import requests, os
import logging
import sys
import uuid
from typing import Dict, Tuple, Optional

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

# Thread management: Maps (user_id, task_id) -> thread_ts
# Also maintain reverse mapping: thread_ts -> (user_id, task_id) for quick lookup
thread_mapping: Dict[Tuple[str, str], str] = {}  # (user_id, task_id) -> thread_ts
thread_to_task: Dict[str, Tuple[str, str]] = {}  # thread_ts -> (user_id, task_id)

def generate_task_id() -> str:
    """Generate a unique task ID"""
    return str(uuid.uuid4())

def get_task_id_from_thread(thread_ts: str) -> Optional[Tuple[str, str]]:
    """Get (user_id, task_id) from thread_ts"""
    return thread_to_task.get(thread_ts)

def store_thread_mapping(user_id: str, task_id: str, thread_ts: str):
    """Store the mapping between (user_id, task_id) and thread_ts"""
    key = (user_id, task_id)
    thread_mapping[key] = thread_ts
    thread_to_task[thread_ts] = (user_id, task_id)
    logger.info(f"Stored thread mapping: user={user_id}, task={task_id}, thread_ts={thread_ts}")

def get_thread_ts(user_id: str, task_id: str) -> Optional[str]:
    """Get thread_ts for a given (user_id, task_id)"""
    key = (user_id, task_id)
    return thread_mapping.get(key)

@slack_app.event("message")
def handle_message_events(body, say, logger):
    """Handle direct messages from users - creates new threads or replies to existing ones"""
    try:
        event = body.get("event", {})
        
        # Skip bot messages
        if event.get("subtype") == "bot_message":
            logger.debug("Skipping bot message")
            return
        
        # Only handle direct messages (DMs)
        if event.get("channel_type") != "im":
            logger.debug("Skipping non-DM message")
            return
        
        user_id = event.get("user")
        channel = event.get("channel")
        text = event.get("text", "")
        message_ts = event.get("ts")
        thread_ts = event.get("thread_ts")  # None if new message, exists if reply
        
        if not user_id or not text:
            logger.warning("Received message without user_id or text")
            return
        
        logger.info(f"Received DM from user {user_id}: {text[:50]}... (thread_ts: {thread_ts})")

        does_user_exist = requests.get(f"https://nox-backend.onrender.com/api/user/{user_id}").json()
        if not does_user_exist:
            logger.warning(f"User {user_id} does not exist")
            say(blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"Hey there! It looks like you're new here. I'm Nox, your AI assistant. Let's get you started."
                    }
                },
                {
                    "type": "context",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"Create an account with me to get started."
                    }
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": "Create Account",
                            "url": f"https://nox.stremly.in/"
                        }
                    ]
                }
            ], thread_ts=thread_ts)
            return
        # Determine if this is a new message or a reply
        if thread_ts is None:
            # New message - create new thread
            task_id = generate_task_id()
            # For new messages, the thread_ts is the message_ts itself
            thread_ts = message_ts
            store_thread_mapping(user_id, task_id, thread_ts)
            logger.info(f"New conversation started: user={user_id}, task={task_id}, thread_ts={thread_ts}")
        else:
            # Reply to existing thread - find the task_id
            task_info = get_task_id_from_thread(thread_ts)
            if task_info is None:
                logger.warning(f"Received reply to unknown thread: {thread_ts}")
                # Generate new task_id for orphaned thread
                task_id = generate_task_id()
                store_thread_mapping(user_id, task_id, thread_ts)
                logger.info(f"Created new task for orphaned thread: user={user_id}, task={task_id}")
            else:
                task_id = task_info[1]
                logger.info(f"Reply to existing thread: user={user_id}, task={task_id}, thread_ts={thread_ts}")
        
        # Forward message to NoX backend
        try:
            payload = {
                "user_id": user_id,
                "task_id": task_id,
                "message": text,
                "thread_ts": thread_ts,
                "is_new_thread": thread_ts == message_ts
            }
            
            logger.info(f"Forwarding message to backend: task={task_id}, user={user_id}")
            # Uncomment when backend is ready:
            # res = requests.post(NOX_BACKEND_URL, json=payload, timeout=10)
            # if res.status_code != 200:
            #     logger.error(f"Backend returned error: {res.status_code}")
            #     say("Sorry, I couldn't process your message right now.", thread_ts=thread_ts)
            #     return
            
            # For now, just acknowledge
            logger.info(f"Message forwarded to backend (simulated): {payload}")
            say("Message forwarded to backend (simulated)", thread_ts=thread_ts)
            
        except Exception as e:
            logger.error(f"Error forwarding to backend: {e}", exc_info=True)
            say("Sorry, I couldn't reach the backend right now.", thread_ts=thread_ts)
        
    except Exception as e:
        logger.error(f"Error in handle_message_events: {e}", exc_info=True)


def get_user_info(user_id: str):
    """Get user information from Slack"""
    try:
        user_info = slack_app.client.users_info(user=user_id)
        if user_info["ok"]:
            return user_info["user"]
        return None
    except Exception as e:
        logger.error(f"Got an error while getting user info: {e}")
        return None

def check_user_exists(user_id: str) -> bool:
    """Check if user exists in backend"""
    try:
        response = requests.get(f"https://nox-backend.onrender.com/api/user/{user_id}", timeout=5)
        if response.status_code == 200:
            user_data = response.json()
            return user_data.get("exists", False) if isinstance(user_data, dict) else bool(user_data)
        return False
    except Exception as e:
        logger.error(f"Error checking user existence: {e}")
        return False

def create_app_home_blocks(user_id: str, user_name: str, is_logged_in: bool):
    """Create Block Kit blocks for App Home page"""
    
    if not is_logged_in:
        # Not logged in - First time user
        return [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "👋 Welcome to NOX!",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Hey there!*\n\nWe're meeting for the first time! I'm *NOX*, your intelligent AI assistant. I'm here to help you with a wide range of tasks and make your work easier.\n\n*Let me get to know you better* so I can provide personalized assistance tailored just for you."
                }
            },
            {
                "type": "divider"
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*🌟 What is NOX?*\n\nNOX is your intelligent AI assistant powered by cutting-edge technology. I can help you with:\n\n• 📊 *Data Analysis* - Get insights from your data\n• 💬 *Conversational AI* - Chat naturally about anything\n• 🔍 *Information Retrieval* - Find answers quickly\n• 📝 *Content Creation* - Generate and refine content\n• 🚀 *Task Automation* - Streamline your workflow\n• 📚 *Knowledge Management* - Organize and access information"
                }
            },
            {
                "type": "divider"
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*✨ What I Can Do For You*\n\n• *Smart Conversations* - Have natural, context-aware discussions\n• *Quick Responses* - Get instant answers to your questions\n• *Task Management* - Help organize and track your work\n• *Learning & Growth* - Continuously improve to serve you better\n• *24/7 Availability* - Always here when you need me"
                }
            },
            {
                "type": "divider"
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*🎯 Ready to Get Started?*\n\nCreate your account now and let's begin our journey together!"
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "🚀 Create Account",
                            "emoji": True
                        },
                        "style": "primary",
                        "url": "https://nox.stremly.in/",
                        "action_id": "create_account"
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "💬 Start Chat",
                            "emoji": True
                        },
                        "action_id": "start_chat_dm"
                    }
                ]
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "💡 *Tip:* Once you create an account, you'll unlock all features and personalized assistance!"
                    }
                ]
            }
        ]
    else:
        # Logged in user
        return [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"👋 Hey, {user_name}!",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*How's it going today?* Need my help? 😊\n\nI'm here and ready to assist you with whatever you need!"
                }
            },
            {
                "type": "divider"
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*🌟 What is NOX?*\n\nNOX is your intelligent AI assistant powered by cutting-edge technology. I'm designed to help you work smarter and faster."
                }
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": "*📊 Data Analysis*\nGet insights from your data"
                    },
                    {
                        "type": "mrkdwn",
                        "text": "*💬 Conversational AI*\nChat naturally about anything"
                    },
                    {
                        "type": "mrkdwn",
                        "text": "*🔍 Information Retrieval*\nFind answers quickly"
                    },
                    {
                        "type": "mrkdwn",
                        "text": "*📝 Content Creation*\nGenerate and refine content"
                    },
                    {
                        "type": "mrkdwn",
                        "text": "*🚀 Task Automation*\nStreamline your workflow"
                    },
                    {
                        "type": "mrkdwn",
                        "text": "*📚 Knowledge Management*\nOrganize and access info"
                    }
                ]
            },
            {
                "type": "divider"
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*✨ What I Can Do For You*\n\n• *Smart Conversations* - Have natural, context-aware discussions with me\n• *Quick Responses* - Get instant answers to your questions\n• *Task Management* - Help organize and track your work efficiently\n• *Learning & Growth* - I continuously improve to serve you better\n• *24/7 Availability* - Always here when you need assistance\n• *Thread Management* - Keep organized conversations in threads"
                }
            },
            {
                "type": "divider"
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*🚀 Quick Actions*"
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "💬 Start New Chat",
                            "emoji": True
                        },
                        "style": "primary",
                        "action_id": "start_chat_dm"
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "📊 View Dashboard",
                            "emoji": True
                        },
                        "url": "https://nox.stremly.in/dashboard",
                        "action_id": "view_dashboard"
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "⚙️ Settings",
                            "emoji": True
                        },
                        "url": "https://nox.stremly.in/settings",
                        "action_id": "view_settings"
                    }
                ]
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "💡 *Tip:* Send me a direct message to start a conversation! I'll create a thread for each task to keep things organized."
                    }
                ]
            }
        ]

@slack_app.event("app_home_opened")
def handle_app_home_opened(client, event, logger):
    """Handle app home opened event - Update App Home tab"""
    try:
        user_id = event.get("user")
        logger.info(f"App home opened by user {user_id}")
        
        # Get user info from Slack
        user_info = get_user_info(user_id)
        user_name = user_info.get("real_name", user_info.get("name", "there")) if user_info else "there"
        
        # Check if user is logged in
        is_logged_in = check_user_exists(user_id)
        
        # Create blocks
        blocks = create_app_home_blocks(user_id, user_name, is_logged_in)
        
        # Publish the App Home view
        client.views_publish(
            user_id=user_id,
            view={
                "type": "home",
                "blocks": blocks
            }
        )
        
        logger.info(f"App Home updated for user {user_id} (logged_in: {is_logged_in})")
        
    except Exception as e:
        logger.error(f"Error in handle_app_home_opened: {e}", exc_info=True)

@slack_app.action("start_chat_dm")
def handle_start_chat_dm(ack, body, client, logger):
    """Handle start chat button - opens DM with bot"""
    ack()
    try:
        user_id = body["user"]["id"]
        # Open DM with the bot
        conversation = client.conversations_open(users=[user_id])
        if conversation["ok"]:
            channel_id = conversation["channel"]["id"]
            client.chat_postMessage(
                channel=channel_id,
                text="Hey! 👋 Ready to chat? Just send me a message and I'll help you out!"
            )
            logger.info(f"Opened DM for user {user_id}")
    except Exception as e:
        logger.error(f"Error opening DM: {e}", exc_info=True)

# Request model for backend to send messages
class BackendSendMessage(BaseModel):
    user_id: str
    task_id: str
    message: str

# Endpoint for backend to send messages to users
@api.post("/backend/send-message")
async def backend_send_message(request: BackendSendMessage):
    """
    Backend endpoint to send a message to a user.
    
    Request body:
    - user_id: Slack user ID (e.g., "U1234567890")
    - task_id: Task ID to identify the conversation thread
    - message: Message text to send
    
    If a thread exists for (user_id, task_id), replies to that thread.
    If no thread exists, creates a new DM thread and stores the mapping.
    """
    try:
        logger.info(f"Backend request: user={request.user_id}, task={request.task_id}, message={request.message[:50]}...")
        
        # Check if thread exists for this (user_id, task_id)
        thread_ts = get_thread_ts(request.user_id, request.task_id)
        
        if thread_ts:
            # Thread exists - reply to it
            logger.info(f"Replying to existing thread: thread_ts={thread_ts}")
            
            # Open or get the DM channel with the user
            conversation_response = slack_app.client.conversations_open(users=[request.user_id])
            
            if not conversation_response["ok"]:
                error_msg = conversation_response.get("error", "Unknown error")
                logger.error(f"Failed to open conversation: {error_msg}")
                raise HTTPException(status_code=400, detail=f"Failed to open DM: {error_msg}")
            
            channel_id = conversation_response["channel"]["id"]
            
            # Send message as reply in thread
            message_response = slack_app.client.chat_postMessage(
                channel=channel_id,
                text=request.message,
                thread_ts=thread_ts
            )
            
            if not message_response["ok"]:
                error_msg = message_response.get("error", "Unknown error")
                logger.error(f"Failed to send message: {error_msg}")
                raise HTTPException(status_code=400, detail=f"Failed to send message: {error_msg}")
            
            logger.info(f"Message sent as reply to thread {thread_ts}")
            return {
                "status": "success",
                "channel_id": channel_id,
                "thread_ts": thread_ts,
                "ts": message_response.get("ts"),
                "message": "Message sent as reply to existing thread"
            }
        else:
            # No thread exists - create new DM thread
            logger.info(f"No thread found for (user={request.user_id}, task={request.task_id}), creating new thread")
            
            # Open or get the DM channel with the user
            conversation_response = slack_app.client.conversations_open(users=[request.user_id])
            
            if not conversation_response["ok"]:
                error_msg = conversation_response.get("error", "Unknown error")
                logger.error(f"Failed to open conversation: {error_msg}")
                raise HTTPException(status_code=400, detail=f"Failed to open DM: {error_msg}")
            
            channel_id = conversation_response["channel"]["id"]
            
            # Send new message (this creates a new thread)
            message_response = slack_app.client.chat_postMessage(
                channel=channel_id,
                text=request.message
            )
            
            if not message_response["ok"]:
                error_msg = message_response.get("error", "Unknown error")
                logger.error(f"Failed to send message: {error_msg}")
                raise HTTPException(status_code=400, detail=f"Failed to send message: {error_msg}")
            
            # Get the thread_ts (for new messages, it's the message ts itself)
            new_thread_ts = message_response.get("ts")
            store_thread_mapping(request.user_id, request.task_id, new_thread_ts)
            
            logger.info(f"New thread created: thread_ts={new_thread_ts}")
            return {
                "status": "success",
                "channel_id": channel_id,
                "thread_ts": new_thread_ts,
                "ts": new_thread_ts,
                "message": "New thread created and message sent"
            }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending message from backend: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

# Endpoint to refresh App Home page
@api.post("/refresh-app-home/{user_id}")
async def refresh_app_home(user_id: str):
    """Manually refresh the App Home page for a user"""
    try:
        # Get user info from Slack
        user_info = get_user_info(user_id)
        user_name = user_info.get("real_name", user_info.get("name", "there")) if user_info else "there"
        
        # Check if user is logged in
        is_logged_in = check_user_exists(user_id)
        
        # Create blocks
        blocks = create_app_home_blocks(user_id, user_name, is_logged_in)
        
        # Publish the App Home view
        response = slack_app.client.views_publish(
            user_id=user_id,
            view={
                "type": "home",
                "blocks": blocks
            }
        )
        
        if response["ok"]:
            return {
                "status": "success",
                "message": "App Home refreshed successfully",
                "user_name": user_name,
                "is_logged_in": is_logged_in
            }
        else:
            raise HTTPException(status_code=400, detail=response.get("error", "Failed to refresh App Home"))
            
    except Exception as e:
        logger.error(f"Error refreshing App Home: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

# Endpoint to get thread info (for debugging/monitoring)
@api.get("/thread-info/{user_id}/{task_id}")
async def get_thread_info(user_id: str, task_id: str):
    """Get thread information for a given user_id and task_id"""
    thread_ts = get_thread_ts(user_id, task_id)
    if thread_ts:
        return {
            "user_id": user_id,
            "task_id": task_id,
            "thread_ts": thread_ts,
            "exists": True
        }
    else:
        return {
            "user_id": user_id,
            "task_id": task_id,
            "thread_ts": None,
            "exists": False
        }

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
