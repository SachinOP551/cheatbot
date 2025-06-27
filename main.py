import os
import logging
import re
from dotenv import load_dotenv
from pyrogram import Client, filters
from pyrogram.types import Message, BotCommand
from pyrogram.enums import ParseMode
from motor.motor_asyncio import AsyncIOMotorClient
from fastapi import FastAPI, Response
import uvicorn
from threading import Thread
import asyncio
from datetime import datetime

# Load environment variables
load_dotenv()

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Get credentials from environment variables
API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
BOT_TOKEN = os.getenv('CHEAT_BOT_TOKEN')
MONGODB_URL = os.getenv('MONGODB_URL')
ADMIN_IDS = [int(id) for id in os.getenv('ADMIN_IDS', '').split(',') if id]

# Initialize FastAPI app
app = FastAPI()

@app.get("/")
async def health_check():
    """Health check endpoint that returns 200 OK"""
    return Response(status_code=200)

@app.get("/health")
async def health_check_detailed():
    """Detailed health check endpoint"""
    try:
        # Check MongoDB connection
        await mongo_client.admin.command('ping')
        db_status = "healthy"
    except Exception as e:
        logger.error(f"MongoDB health check failed: {e}")
        db_status = "unhealthy"

    # Check Pyrogram client
    try:
        pyrogram_status = "healthy" if app.is_connected else "unhealthy"
    except Exception as e:
        logger.error(f"Pyrogram health check failed: {e}")
        pyrogram_status = "unhealthy"

    return {
        "status": "OK",
        "database": db_status,
        "bot": pyrogram_status,
        "timestamp": datetime.now().isoformat()
    }

# Initialize MongoDB client
mongo_client = AsyncIOMotorClient(MONGODB_URL)
db = mongo_client.marvel_collector
characters = db.characters

# Initialize Pyrogram client
app = Client(
    "character_cheat_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

def extract_character_info(text: str) -> dict:
    """Extract character information from message text"""
    try:
        # Extract name
        name_match = re.search(r"👤\s*ɴᴀᴍᴇ:\s*([^\n]+)", text)
        if not name_match:
            return None
        name = name_match.group(1).strip()

        # Extract ID
        id_match = re.search(r"🆔\s*ɪᴅ:\s*(\d+)", text)
        if not id_match:
            return None
        char_id = int(id_match.group(1))

        return {
            "name": name,
            "char_id": char_id
        }
    except Exception as e:
        logger.error(f"Error extracting character info: {e}")
        return None

@app.on_message(filters.photo & filters.private)
async def handle_character_message(client: Client, message: Message):
    """Handle forwarded character messages"""
    try:
        # Check if message has caption
        if not message.caption:
            return

        # Extract character info from caption
        char_info = extract_character_info(message.caption)
        if not char_info:
            return

        # Get file_id from photo
        file_unique_id = message.photo.file_unique_id

        # Check if character already exists
        existing = await characters.find_one({"char_id": char_info["char_id"]})
        if existing:
            # Update existing character
            await characters.update_one(
                {"char_id": char_info["char_id"]},
                {
                    "$set": {
                        "name": char_info["name"],
                        "file_unique_id": file_unique_id
                    }
                }
            )
            await message.reply_text(
                f"✅ Character updated!\n\n"
                f"👤 Name: {char_info['name']}\n"
                f"🆔 ID: {char_info['char_id']}"
            )
        else:
            # Add new character
            await characters.insert_one({
                "name": char_info["name"],
                "char_id": char_info["char_id"],
                "file_unique_id": file_unique_id
            })
            await message.reply_text(
                f"✅ Character added!\n\n"
                f"👤 Name: {char_info['name']}\n"
                f"🆔 ID: {char_info['char_id']}"
            )

    except Exception as e:
        logger.error(f"Error handling character message: {e}")
        await message.reply_text(
            "❌ An error occurred!"
        )

@app.on_message(filters.command("name") & filters.reply)
async def name_command(client: Client, message: Message):
    """Handle the /name command"""
    try:
        # Get the replied message
        replied_msg = message.reply_to_message
        
        # Check if the replied message has a photo
        if not replied_msg.photo:
            await message.reply_text(
                "❌ Please reply to a character image!"
            )
            return

        # Get the file_unique_id of the photo
        file_unique_id = replied_msg.photo.file_unique_id

        # Search for the character in database using file_unique_id
        character = await characters.find_one({"file_unique_id": file_unique_id})
        
        if character:
            # Format the response
            response = (
                f"🔍 Character identified!\n\n"
                f"👤 Character name: {character['name']}\n"
                f"🆔 ID: {character.get('char_id', character.get('character_id', 'Unknown'))}\n\n"
                f"💡 Use: `/collect {character['name']}`"
            )
            await message.reply_text(response, parse_mode=ParseMode.MARKDOWN)
        else:
            await message.reply_text(
                "❌ Character not found in database!"
            )

    except Exception as e:
        logger.error(f"Error in name command: {e}")
        await message.reply_text(
            "❌ An error occurred!"
        )

@app.on_message(filters.command("addchar") & filters.user(ADMIN_IDS))
async def add_character(client: Client, message: Message):
    """Add a character to the database (Admin only)"""
    try:
        if not message.reply_to_message or not message.reply_to_message.photo:
            await message.reply_text(
                "❌ Please reply to a character image with the command!"
            )
            return

        # Get character details from command arguments
        args = message.text.split(maxsplit=2)
        if len(args) < 3:
            await message.reply_text(
                "❌ Please provide character name and id!\n"
                "Usage: /addchar <name> <id>"
            )
            return

        name = args[1]
        char_id = int(args[2])
        file_unique_id = message.reply_to_message.photo.file_unique_id

        # Add character to database
        await characters.insert_one({
            "name": name,
            "char_id": char_id,
            "file_unique_id": file_unique_id
        })

        await message.reply_text(
            f"✅ Character added successfully!\n\n"
            f"👤 Name: {name}\n"
            f"🆔 ID: {char_id}"
        )

    except Exception as e:
        logger.error(f"Error in add_character: {e}")
        await message.reply_text(
            "❌ An error occurred!"
        )

def run_fastapi():
    """Run FastAPI server with proper configuration"""
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        workers=1,
        log_level="info",
        reload=False
    )

async def set_bot_commands(client: Client):
    """Set bot commands that will be shown in the Telegram interface"""
    commands = [
        BotCommand("name", "Identify character name from image"),
        BotCommand("addchar", "Add a character to database (Admin only)")
    ]
    await client.set_bot_commands(commands)
    logger.info("Bot commands have been set")

if __name__ == "__main__":
    # Start FastAPI in a separate thread
    fastapi_thread = Thread(target=run_fastapi)
    fastapi_thread.daemon = True  # Make thread daemon so it exits when main thread exits
    fastapi_thread.start()
    
    # Set bot commands before running
    app.set_bot_commands = set_bot_commands
    
    # Run the bot
    app.run() 
