import asyncio
import logging
import os
import re
import time
import uuid
from io import BytesIO
from urllib.parse import urlparse
import requests
from PIL import Image, ImageDraw, ImageFont
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackContext,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from config import (
    DEBUG,
    DEFAULT_WATERMARK_TEXT,
    DEFAULT_WATERMARK_COLOR,
    DEFAULT_WATERMARK_FONT_SIZE,
    DEFAULT_OUTPUT_FILENAME,
    DEFAULT_DOWNLOAD_TIMEOUT
)

# Logging Setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# global dictionary to store user specific watermark settings
user_watermark_settings = {}

def generate_unique_filename(filename):
    """Generates a unique filename based on the original filename and a UUID."""
    name, ext = os.path.splitext(filename)
    return f"{name}_{uuid.uuid4()}{ext}"


async def start(update: Update, context: CallbackContext) -> None:
    """Start command handler."""
    await update.message.reply_text("Hello! Send me a file or a URL to add a watermark.")


async def help_command(update: Update, context: CallbackContext) -> None:
    """Help command handler with inline buttons."""
    keyboard = [
        [
            InlineKeyboardButton("Set Watermark", callback_data="set_watermark"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Available Commands:\n/start - Start the bot\n/help - Show this message",
        reply_markup=reply_markup,
    )

async def set_watermark_menu(update: Update, context: CallbackContext) -> None:
    """Shows a menu of options to modify the watermark."""
    query = update.callback_query
    await query.answer()  # Acknowledge the callback

    keyboard = [
        [InlineKeyboardButton("Text", callback_data="set_watermark_text")],
        [InlineKeyboardButton("Color", callback_data="set_watermark_color")],
        [InlineKeyboardButton("Size", callback_data="set_watermark_size")],
        [InlineKeyboardButton("Back", callback_data="help_back")],

    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Choose what to edit:", reply_markup=reply_markup)

async def set_watermark_text(update: Update, context: CallbackContext) -> None:
    """Prompts the user to enter custom text for the watermark."""
    query = update.callback_query
    await query.answer()  # Acknowledge the callback
    await query.edit_message_text(
        "Please enter the custom text for the watermark:"
    )
    context.user_data['setting'] = 'watermark_text'

async def set_watermark_color(update: Update, context: CallbackContext) -> None:
    """Prompts the user to enter custom text for the watermark."""
    query = update.callback_query
    await query.answer()  # Acknowledge the callback
    await query.edit_message_text(
        "Please enter the custom color for the watermark in rgba format:"
        "(e.g. 255,255,255,128)"
    )
    context.user_data['setting'] = 'watermark_color'

async def set_watermark_size(update: Update, context: CallbackContext) -> None:
    """Prompts the user to enter custom text for the watermark."""
    query = update.callback_query
    await query.answer()  # Acknowledge the callback
    await query.edit_message_text(
        "Please enter the custom size for the watermark (integer)"
    )
    context.user_data['setting'] = 'watermark_size'


async def handle_watermark_input(update: Update, context: CallbackContext) -> None:
    """Handles the user input for custom watermark settings."""
    setting_type = context.user_data.get('setting')
    text = update.message.text.strip()
    user_id = update.message.from_user.id
    
    try:
        if setting_type == 'watermark_text':
            if user_id not in user_watermark_settings:
                user_watermark_settings[user_id] = {}
            user_watermark_settings[user_id]['text'] = text
            await update.message.reply_text(f"Watermark text set to: `{text}`")
        elif setting_type == 'watermark_color':
            r, g, b, a = map(int, text.split(','))
            color = (r, g, b, a)
            if user_id not in user_watermark_settings:
                user_watermark_settings[user_id] = {}
            user_watermark_settings[user_id]['color'] = color
            await update.message.reply_text(f"Watermark color set to: `{color}`")
        elif setting_type == 'watermark_size':
            size = int(text)
            if user_id not in user_watermark_settings:
                user_watermark_settings[user_id] = {}
            user_watermark_settings[user_id]['size'] = size
            await update.message.reply_text(f"Watermark size set to: `{size}`")
        context.user_data.pop('setting',None)
    except Exception as e:
        await update.message.reply_text(f"Failed to set watermark, please check input\n\n {e}")


async def handle_callback_query(update: Update, context: CallbackContext) -> None:
    """Handles inline button callbacks."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "set_watermark":
        await set_watermark_menu(update, context)
    elif query.data == 'set_watermark_text':
        await set_watermark_text(update,context)
    elif query.data == 'set_watermark_color':
        await set_watermark_color(update,context)
    elif query.data == 'set_watermark_size':
        await set_watermark_size(update, context)
    elif query.data == "help_back":
        await help_command(update, context)
    elif query.data == "cancel":
        context.user_data["cancelled"] = True
        await query.edit_message_text("Task Cancelled.")
