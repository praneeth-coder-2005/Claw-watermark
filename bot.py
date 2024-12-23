import os
import asyncio
import logging
from telegram import Bot, Update, InputMediaDocument, InputMediaVideo
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from telegram.error import TelegramError
import requests
from config import TELEGRAM_BOT_TOKEN, TEMP_DIR

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


def create_temp_dir():
    """Creates the temporary directory for saving files, if not exist"""
    if not os.path.exists(TEMP_DIR):
        os.makedirs(TEMP_DIR)
    return TEMP_DIR

async def download_file_stream(url, file_path):
    """Downloads a file using stream processing."""
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(file_path, 'wb') as file:
            for chunk in response.iter_content(chunk_size=8192):
                file.write(chunk)
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Error downloading the file with stream: {e}")
        return False

async def send_telegram_file_chunks(bot, file_path, chat_id):
    """Sends a file to Telegram in chunks."""
    try:
        file_size = os.path.getsize(file_path)
        if file_size > 50 * 1024 * 1024:  # 50 MB max size for document
            logger.info(f"File size {file_size} exceeds 50MB, sending as chunks")
            await bot.send_message(chat_id=chat_id, text="Sending large file in chunks...")
            chunk_size = 20 * 1024 * 1024  # 20 MB chunk size
            with open(file_path, 'rb') as file:
                media_list = []
                i = 0
                while True:
                  chunk = file.read(chunk_size)
                  if not chunk:
                    break

                  if len(media_list) > 9:
                    if file_path.lower().endswith(('.mp4', '.avi', '.mov', '.mkv')):
                      await bot.send_media_group(chat_id=chat_id, media=media_list)
                    else:
                      await bot.send_media_group(chat_id=chat_id, media=media_list)
                    media_list = []
                  #check if video or document
                  if file_path.lower().endswith(('.mp4', '.avi', '.mov', '.mkv')):
                    media_list.append(InputMediaVideo(chunk))
                  else:
                    media_list.append(InputMediaDocument(chunk))
                  i = i + 1

                if media_list:
                  if file_path.lower().endswith(('.mp4', '.avi', '.mov', '.mkv')):
                     await bot.send_media_group(chat_id=chat_id, media=media_list)
                  else:
                    await bot.send_media_group(chat_id=chat_id, media=media_list)
        else:
            logger.info(f"File size {file_size} does not exceed 50MB, sending as single file")
            with open(file_path, 'rb') as file:
              if file_path.lower().endswith(('.mp4', '.avi', '.mov', '.mkv')):
                 await bot.send_video(chat_id=chat_id, video=file)
              else:
                  await bot.send_document(chat_id=chat_id, document=file)
        return True

    except TelegramError as e:
        logger.error(f"Error sending telegram file: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending telegram file: {e}")
        return False

async def process_file(update: Update, context: ContextTypes.DEFAULT_TYPE, file_path, file_type):
    """Processes the file, including download, and sending."""
    try:
        chat_id = update.effective_chat.id

        await context.bot.send_message(chat_id=chat_id, text="Downloading file...")

        if await send_telegram_file_chunks(context.bot, file_path, chat_id):
            await context.bot.send_message(chat_id=chat_id, text="File sent successfully!")
        else:
            await context.bot.send_message(chat_id=chat_id, text="File sending failed.")

        # Clean up temporary files
        os.remove(file_path)


    except Exception as e:
        logger.error(f"Error in processing file: {e}")
        await context.bot.send_message(chat_id=chat_id, text=f"An unexpected error has occurred: {e}")


async def handle_file_download_from_telegram(update: Update, context: ContextTypes.DEFAULT_TYPE):
  """Handles incoming document and video messages from telegram."""
  try:
        chat_id = update.effective_chat.id
        if update.message.document:
            logger.info(f"Received a document message: {update.message.document.file_name} and {update.message.document.file_id}")
            file_id = update.message.document.file_id
            file_name = update.message.document.file_name
            file_path = os.path.join(create_temp_dir(), file_name)

            file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_id}"

            if not await download_file_stream(file_url, file_path):
                await context.bot.send_message(chat_id=chat_id, text="Download failed.")
                return

            file_type = 'document'
            await process_file(update, context, file_path, file_type)

        elif update.message.video:
            logger.info(f"Received a video message: {update.message.video.file_name} and {update.message.video.file_id}")
            file_id = update.message.video.file_id
            file_name = update.message.video.file_name
            file_path = os.path.join(create_temp_dir(), file_name)


            file_url =  f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_id}"


            if not await download_file_stream(file_url, file_path):
                 await context.bot.send_message(chat_id=chat_id, text="Download failed.")
                 return

            file_type = 'video'
            await process_file(update, context, file_path, file_type)

  except TelegramError as e:
        logger.error(f"Telegram API error in handle_file_download: {e}")
        await context.bot.send_message(chat_id=chat_id, text=f"Error processing file. Please try again.")

  except Exception as e:
      logger.error(f"An unexpected error occurred: {e}")
      await context.bot.send_message(chat_id=chat_id, text=f"An unexpected error has occurred in handle_file_download: {e}")

async def handle_url_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
  """Handles incoming URL text messages."""
  try:
        chat_id = update.effective_chat.id
        url = update.message.text

        if not url.startswith("http://") and not url.startswith("https://"):
            await context.bot.send_message(chat_id=chat_id, text="Invalid URL format. Please provide a valid http or https URL.")
            return

        file_name = os.path.basename(url)
        file_path = os.path.join(create_temp_dir(), file_name)

        if not await download_file_stream(url, file_path):
            await context.bot.send_message(chat_id=chat_id, text="Download from URL failed.")
            return

        file_type = "other"
        if file_path.lower().endswith(('.mp4', '.avi', '.mov', '.mkv')):
            file_type = 'video'

        await process_file(update, context, file_path, file_type)


  except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        await context.bot.send_message(chat_id=chat_id, text=f"An unexpected error has occurred in handle_url_download: {e}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
  await context.bot.send_message(chat_id=update.effective_chat.id, text="Hello, I am a file transfer bot. Send me a file or a file URL, and I'll send it back!")

def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url_download))
    app.add_handler(MessageHandler(filters.ALL, handle_file_download_from_telegram))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
