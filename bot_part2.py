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
from bot_part1 import (
    generate_unique_filename, start, help_command, set_watermark_menu, set_watermark_text,
    set_watermark_color,set_watermark_size,handle_watermark_input,handle_callback_query,
    user_watermark_settings,logger
    )
from config import (
   TOKEN,
   DEBUG,
   DEFAULT_WATERMARK_TEXT,
   DEFAULT_WATERMARK_COLOR,
   DEFAULT_WATERMARK_FONT_SIZE,
   DEFAULT_OUTPUT_FILENAME,
   DEFAULT_DOWNLOAD_TIMEOUT
)

async def handle_file(update: Update, context: CallbackContext) -> None:
    """Handles file uploads and processing."""
    if update.message.document:
        file = update.message.document
        file_id = file.file_id
        filename = file.file_name
        file_size = file.file_size
        file_mime_type = file.mime_type
        file_source = "telegram_file"
    elif update.message.photo:
        photo_list = update.message.photo
        #get largest photo size if multiple
        file = sorted(photo_list, key=lambda x: x.file_size)[-1]
        file_id = file.file_id
        filename = 'image.jpg'  # Default filename for images
        file_size = file.file_size
        file_mime_type = 'image/jpeg' # default mime type for images
        file_source = "telegram_photo"
    elif update.message.text:
        text = update.message.text.strip()
        if text.startswith("http://") or text.startswith("https://"):
          url = text
          filename = os.path.basename(urlparse(url).path)
          if not filename:
                filename = "downloaded_file"
          try:
            response = requests.head(url, timeout=5, allow_redirects=True)
            if response.status_code == 200:
               file_size = int(response.headers.get('content-length', 0))
               file_mime_type = response.headers.get('Content-Type', 'application/octet-stream') # get content-type
               file_source = "url_download"
            else:
              await update.message.reply_text("Invalid download link provided")
              return
          except requests.exceptions.RequestException as e:
                await update.message.reply_text(f"Error validating download link: {e}")
                return
          file_id = None # file id not available
        else:
            return # No file found
    else:
       return  # No valid file provided

    # Check file type
    if not file_mime_type.startswith('image/') and file_source != "url_download" and not file_mime_type.startswith('video/'):
        await update.message.reply_text("Unsupported file format. Only image and video formats are supported.")
        return
    
    
    await process_file(update, context, file_id, filename, file_size, file_mime_type, file_source, url=url if file_source == "url_download" else None)


async def process_file(update: Update, context: CallbackContext, file_id, filename, file_size, file_mime_type, file_source, url=None) -> None:
     """Processes a file by adding a watermark and handling the upload progress."""

    user_id = update.message.from_user.id
    # Default watermark settings
    watermark_text = DEFAULT_WATERMARK_TEXT
    watermark_color = DEFAULT_WATERMARK_COLOR
    watermark_font_size = DEFAULT_WATERMARK_FONT_SIZE
    
    if user_id in user_watermark_settings:
      watermark_text = user_watermark_settings[user_id].get('text', DEFAULT_WATERMARK_TEXT)
      watermark_color = user_watermark_settings[user_id].get('color', DEFAULT_WATERMARK_COLOR)
      watermark_font_size = user_watermark_settings[user_id].get('size', DEFAULT_WATERMARK_FONT_SIZE)

    await update.message.reply_text(
        "Please provide the custom filename you want to add, or send `/default` to keep default name."
        )
    
    context.user_data["original_file_id"] = file_id
    context.user_data["original_filename"] = filename
    context.user_data["original_file_size"] = file_size
    context.user_data["original_mime_type"] = file_mime_type
    context.user_data["file_source"] = file_source
    context.user_data["url"] = url
    context.user_data["watermark_text"] = watermark_text
    context.user_data["watermark_color"] = watermark_color
    context.user_data["watermark_font_size"] = watermark_font_size
    context.user_data["processing_file"] = True # Flag to indicate that file is being processed

async def handle_filename(update: Update, context: CallbackContext) -> None:
    """Handles the user's custom filename and starts the download/processing."""
    if not context.user_data.get('processing_file', False): # not processing file
        return
    
    custom_filename = update.message.text.strip()

    if custom_filename == '/default':
        custom_filename = DEFAULT_OUTPUT_FILENAME
    
    original_filename = context.user_data.get("original_filename", "original_file")
    original_file_size = context.user_data.get("original_file_size", 0)
    original_mime_type = context.user_data.get("original_mime_type", "application/octet-stream")
    file_source = context.user_data.get("file_source")
    file_id = context.user_data.get("original_file_id")
    url = context.user_data.get("url")
    
    name, ext = os.path.splitext(original_filename)
    if custom_filename == DEFAULT_OUTPUT_FILENAME:
      final_filename =  f"{custom_filename}{ext}"
    else:
      final_filename = f"{custom_filename}{ext}" # Ensure same extension
    
    await update.message.reply_text(f"Processing file: {final_filename}")

    # Initialize progress context for this file
    context.user_data["progress"] = {
        "download_start_time": time.time(),
        "upload_start_time": None,
        "download_bytes_complete": 0,
        "upload_bytes_complete": 0,
        "total_bytes": original_file_size,
        "last_update_percent": 0,
        "message": None,
        "cancelled": False, # To check for cancel
        "final_filename": final_filename
    }
    
    # Start the download and processing asynchronously
    try:
      await download_and_process(update, context, file_id, original_filename, original_file_size, final_filename, original_mime_type, file_source, url)
    except Exception as e:
       await update.message.reply_text(f"Error processing file: {e}")
    finally:
        context.user_data["processing_file"] = False # Reset the flag to allow more files to be processed


async def download_and_process(update: Update, context: CallbackContext, file_id, original_filename, original_file_size, final_filename, original_mime_type, file_source, url=None) -> None:
    """Handles the download, processing, and upload of a file."""
    
    progress_data = context.user_data["progress"]
    
    # Create initial message
    progress_data["message"] = await update.message.reply_text("Initializing file processing...", reply_markup=get_cancel_button())

    
    try:
      if file_source == "telegram_file" or file_source == "telegram_photo":
        # Download Telegram file
        file = await context.bot.get_file(file_id)
        downloaded_file = BytesIO()
        await file.download_async(
            out=downloaded_file,
            progress=download_progress_callback,
            progress_args=(update, context, original_file_size),
        )
        downloaded_file.seek(0)  # Rewind to start of file for processing
        # Check if cancelled during download
        if progress_data["cancelled"]:
            return
        processed_file = await add_watermark(downloaded_file, original_filename, final_filename, context)
      elif file_source == "url_download":
          # Download from URL
          processed_file = await download_from_url(url, update, context)
          if progress_data["cancelled"]:
            return
      
      # Check if cancelled during processing
      if progress_data["cancelled"]:
        return

      progress_data["upload_start_time"] = time.time()
      await upload_file(update, context, processed_file, final_filename, original_mime_type)

    except Exception as e:
        await update.message.reply_text(f"Failed to download or process file: {e}")
    finally:
        if progress_data and progress_data["message"]:
          if not progress_data["cancelled"]:
            await context.bot.edit_message_text(
              chat_id=progress_data["message"].chat_id,
              message_id=progress_data["message"].message_id,
              text="File processing completed!"
            )
    return


async def download_progress_callback(current, total, update: Update, context: CallbackContext, total_size: int) -> None:
    """Download progress callback function."""
    progress_data = context.user_data.get("progress", {})
    progress_data["download_bytes_complete"] = current
    progress_data["total_bytes"] = total_size
    await update_progress_message(update, context)


async def download_from_url(url, update: Update, context: CallbackContext) -> BytesIO:
    """Downloads a file from a URL and streams it into memory."""
    progress_data = context.user_data.get("progress", {})
    try:
        with requests.get(url, stream=True, timeout=DEFAULT_DOWNLOAD_TIMEOUT) as response:
            response.raise_for_status()  # Raise HTTPError for bad responses
            
            file_stream = BytesIO()
            downloaded_bytes = 0
            
            # Extract content length if available for total size, else fallback to 0
            total_size = int(response.headers.get('content-length', 0))
            progress_data["total_bytes"] = total_size
            
            for chunk in response.iter_content(chunk_size=4096):  # 4KB chunks
                if progress_data["cancelled"]: # Check for cancel in each chunk
                    return
                downloaded_bytes += len(chunk)
                file_stream.write(chunk)
                progress_data["download_bytes_complete"] = downloaded_bytes
                await update_progress_message(update, context)

            file_stream.seek(0)  # Rewind to start
            return file_stream
    
    except requests.exceptions.RequestException as e:
        await update.message.reply_text(f"Failed to download file from URL: {e}")
        return None
    

async def add_watermark(file_stream, original_filename, final_filename, context: CallbackContext) -> BytesIO:
    """Adds a text watermark to an image."""
    progress_data = context.user_data["progress"]

    if "image" not in context.user_data["original_mime_type"]:
        return file_stream # only image for watermark

    try:
        image = Image.open(file_stream)
        draw = ImageDraw.Draw(image)
        
        text = context.user_data["watermark_text"]
        color = context.user_data["watermark_color"]
        font_size = context.user_data["watermark_font_size"]

        # Adjust font size if the image is smaller than the default watermark font size
        if image.width < font_size or image.height < font_size:
          font_size = min(image.width, image.height) // 10
          
        font = ImageFont.truetype("arial.ttf", size=font_size) # Load default font
        
        # Calculate text bounding box
        text_bbox = draw.textbbox((0, 0), text, font=font)

        # Calculate text position, place it in the bottom right corner
        text_x = image.width - text_bbox[2] - 10
        text_y = image.height - text_bbox[3] - 10
        draw.text((text_x, text_y), text, font=font, fill=color)

        # Save the watermarked image to a new BytesIO object
        output_stream = BytesIO()
        if ".jpg" in original_filename.lower() or ".jpeg" in original_filename.lower():
            image.save(output_stream, format="JPEG", quality=95)
        elif ".png" in original_filename.lower():
            image.save(output_stream, format="PNG")
        elif ".webp" in original_filename.lower():
            image.save(output_stream, format="WEBP", quality=95)
        elif ".bmp" in original_filename.lower():
            image.save(output_stream, format="BMP")
        else:
           image.save(output_stream, format=image.format) # if no extension then use same
        output_stream.seek(0)
        return output_stream

    except Exception as e:
        logger.error(f"Error adding watermark: {e}")
        return file_stream
    
async def upload_file(update: Update, context: CallbackContext, file_stream, final_filename, original_mime_type) -> None:
    """Uploads the processed file to Telegram."""
    progress_data = context.user_data.get("progress", {})
    try:
      if file_stream: # check is file exists
        await context.bot.send_document(
          chat_id=update.effective_chat.id,
          document=file_stream,
          filename=final_filename,
          caption=f"Here is your watermarked file: `{final_filename}`",
          progress=upload_progress_callback,
          progress_args=(update, context),
        )
      else:
         await update.message.reply_text("No file to process")
    except Exception as e:
      await update.message.reply_text(f"Failed to upload the processed file: {e}")
      logger.error(f"Error during upload: {e}")
    return
  

async def upload_progress_callback(current, total, update: Update, context: CallbackContext) -> None:
    """Upload progress callback function."""
    progress_data = context.user_data.get("progress", {})
    progress_data["upload_bytes_complete"] = current
    await update_progress_message(update, context)


async def update_progress_message(update: Update, context: CallbackContext) -> None:
    """Updates the progress message."""
    progress_data = context.user_data.get("progress", {})

    if not progress_data or not progress_data.get("message"):
       return # prevent error from null data

    current_time = time.time()
    total_bytes = progress_data.get("total_bytes", 0)
    download_bytes_complete = progress_data.get("download_bytes_complete", 0)
    upload_bytes_complete = progress_data.get("upload_bytes_complete", 0)
    download_start_time = progress_data.get("download_start_time", current_time)
    upload_start_time = progress_data.get("upload_start_time")
    last_update_percent = progress_data.get("last_update_percent", 0)
    final_filename = progress_data.get("final_filename", "file")
    
    if progress_data["cancelled"]: # dont update progress bar if cancelled
        return
    
    
    if total_bytes > 0:
        download_percentage = (download_bytes_complete / total_bytes) * 100 if total_bytes > 0 else 0
        upload_percentage = (upload_bytes_complete / total_bytes) * 100 if total_bytes > 0 else 0
        
        download_speed_bps = (download_bytes_complete / (current_time - download_start_time)) if (current_time - download_start_time) > 0 else 0
        upload_speed_bps = (upload_bytes_complete / (current_time - upload_start_time)) if upload_start_time and (current_time - upload_start_time) > 0 else 0
        
        download_speed_kbps = download_speed_bps / 1024
        upload_speed_kbps = upload_speed_bps / 1024
        
        
        time_elapsed = current_time - download_start_time
        if download_speed_bps > 0 :
            remaining_time_download = (total_bytes-download_bytes_complete)/download_speed_bps
            remaining_time_download = f"{(remaining_time_download):.2f} seconds"
        else:
             remaining_time_download = "N/A"
             
        if upload_speed_bps > 0:
           remaining_time_upload = (total_bytes-upload_bytes_complete)/upload_speed_bps
           remaining_time_upload = f"{(remaining_time_upload):.2f} seconds"
        else:
          remaining_time_upload = "N/A"


        # check is download and upload complete
        download_progress_bar = get_progress_bar(int(download_percentage))
        upload_progress_bar = get_progress_bar(int(upload_percentage))
        
        text = f"Filename: `{final_filename}`\n"
        text += f"File Size: {get_human_readable_size(total_bytes)}\n"
        text += f"Download Speed: {download_speed_kbps:.2f} KB/s | Remaining: {remaining_time_download}\n"
        text += f"Upload Speed: {upload_speed_kbps:.2f} KB/s  | Remaining: {remaining_time_upload}\n\n"
        text += f"Download: {download_progress_bar} {int(download_percentage)}%\n"
        text += f"Upload: {upload_progress_bar} {int(upload_percentage)}%"
        
        if abs(int(download_percentage) - last_update_percent) >= 10 or abs(int(upload_percentage) - last_update_percent) >= 10 or int(download_percentage) == 100 or int(upload_percentage) == 100:
            try:
                await context.bot.edit_message_text(
                    chat_id=progress_data["message"].chat_id,
                    message_id=progress_data["message"].message_id,
                    text=text,
                    reply_markup=get_cancel_button()
                )
            except Exception as e:
               logger.error(f"Error updating progress message: {e}")
            progress_data["last_update_percent"] = max(int(download_percentage), int(upload_percentage))
    else: # send default msg for starting
      try:
        await context.bot.edit_message_text(
            chat_id=progress_data["message"].chat_id,
            message_id=progress_data["message"].message_id,
            text="Initializing download ...",
             reply_markup=get_cancel_button()
        )
      except Exception as e:
          logger.error(f"Error updating initial progress message: {e}")


def get_human_readable_size(size_bytes):
  """Converts bytes to a human-readable size string."""
  if size_bytes < 1024:
    return f"{size_bytes} B"
  elif size_bytes < 1024 * 1024:
    return f"{size_bytes / 1024:.2f} KB"
  elif size_bytes < 1024 * 1024 * 1024:
    return f"{size_bytes / (1024 * 1024):.2f} MB"
  else:
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def get_progress_bar(percentage: int) -> str:
    """Creates an ascii progress bar based on a percentage."""
    filled_blocks = int(percentage / 10)
    bar = "█" * filled_blocks + "░" * (10 - filled_blocks)
    return bar


def get_cancel_button() -> InlineKeyboardMarkup:
    """Creates the cancel inline button."""
    keyboard = [[InlineKeyboardButton("Cancel", callback_data="cancel")]]
    return InlineKeyboardMarkup(keyboard)


def main(token) -> None:
    """Main function to start the bot."""
    application = (
        Application.builder().token(token).build()
    )

    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))

    # Callback handlers
    application.add_handler(CallbackQueryHandler(handle_callback_query))

    # Message handlers
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_watermark_input))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_filename)) # filename handler
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_file)) # file and url

    # Start the bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main(TOKEN)
