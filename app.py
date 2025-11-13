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
