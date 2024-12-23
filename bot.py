import os
import asyncio
import logging
import traceback
from pyrogram import Client, filters
from pyrogram.types import InputMediaDocument, InputMediaVideo
from pyrogram.errors import RPCError
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

async def send_telegram_file_chunks(client, file_path, chat_id):
    """Sends a file to Telegram in chunks."""
    try:
        file_size = os.path.getsize(file_path)
        if file_size > 50 * 1024 * 1024:  # 50 MB max size for document
            logger.info(f"File size {file_size} exceeds 50MB, sending as chunks")
            await client.send_message(chat_id=chat_id, text="Sending large file in chunks...")
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
                            await client.send_media_group(chat_id=chat_id, media=media_list)
                        else:
                            await client.send_media_group(chat_id=chat_id, media=media_list)
                        media_list = []
                    #check if video or document
                    if file_path.lower().endswith(('.mp4', '.avi', '.mov', '.mkv')):
                       media_list.append(InputMediaVideo(chunk))
                    else:
                       media_list.append(InputMediaDocument(chunk))
                    i = i + 1
                if media_list:
                  if file_path.lower().endswith(('.mp4', '.avi', '.mov', '.mkv')):
                     await client.send_media_group(chat_id=chat_id, media=media_list)
                  else:
                      await client.send_media_group(chat_id=chat_id, media=media_list)
        else:
             logger.info(f"File size {file_size} does not exceed 50MB, sending as single file")
             with open(file_path, 'rb') as file:
               if file_path.lower().endswith(('.mp4', '.avi', '.mov', '.mkv')):
                  await client.send_video(chat_id=chat_id, video=file)
               else:
                   await client.send_document(chat_id=chat_id, document=file)
        return True
    except Exception as e:
        logger.error(f"Error sending telegram file: {e}")
        return False


async def handle_file_download(client, message):
    """Handles incoming document and video messages from telegram."""
    try:
        chat_id = message.chat.id
        file_path = None # initialize file path

        if message.document:
           logger.info(f"Received a document message: {message.document.file_name} and {message.document.file_id}")
           file_id = message.document.file_id
           file_name = message.document.file_name
           file_path = os.path.join(create_temp_dir(), file_name)

        elif message.video:
          logger.info(f"Received a video message: {message.video.file_name} and {message.video.file_id}")
          file_id = message.video.file_id
          file_name = message.video.file_name
          file_path = os.path.join(create_temp_dir(), file_name)

        if file_path:
          await client.send_message(chat_id=chat_id, text="Downloading file...")
          try:
            await client.download_media(message, file_path) # download directly with pyrogram, so we don't need to use URLs
            await send_telegram_file_chunks(client, file_path, chat_id)

          except RPCError as e:
             logger.error(f"Error downloading and sending the file: {e}")
             logger.error(traceback.format_exc())  # Log traceback
             await client.send_message(chat_id=chat_id, text="Download and send failed.")

          finally:
            if file_path and os.path.exists(file_path):
             os.remove(file_path)

    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        logger.error(traceback.format_exc())  # Log traceback
        await client.send_message(chat_id=chat_id, text=f"An unexpected error has occurred: {e}")


async def handle_url_download(client, message):
    """Handles incoming URL text messages."""
    try:
        chat_id = message.chat.id
        url = message.text

        if not url.startswith("http://") and not url.startswith("https://"):
            await client.send_message(chat_id=chat_id, text="Invalid URL format. Please provide a valid http or https URL.")
            return

        file_name = os.path.basename(url)
        file_path = os.path.join(create_temp_dir(), file_name)

        await client.send_message(chat_id=chat_id, text="Downloading file...")

        try:
            async with  requests.get(url, stream=True) as response: # requests to download file from URL
                response.raise_for_status()
                with open(file_path, 'wb') as file:
                   for chunk in response.iter_content(chunk_size=8192):
                       file.write(chunk)
            await send_telegram_file_chunks(client, file_path, chat_id)

        except Exception as e:
             logger.error(f"Error downloading and sending file using URL {e}")
             logger.error(traceback.format_exc())  # Log traceback
             await client.send_message(chat_id, "Download and send failed.")

        finally:
             if file_path and os.path.exists(file_path):
                 os.remove(file_path)

    except Exception as e:
       logger.error(f"An unexpected error occurred: {e}")
       logger.error(traceback.format_exc())  # Log traceback
       await client.send_message(chat_id, f"An unexpected error has occurred: {e}")

async def start(client, message):
  await client.send_message(chat_id=message.chat.id, text="Hello, I am a file transfer bot. Send me a file or a file URL, and I'll send it back!")

async def main():
  api_id = os.environ.get("TELEGRAM_API_ID")
  api_hash = os.environ.get("TELEGRAM_API_HASH")


  if not api_id or not api_hash:
      logger.error("TELEGRAM_API_ID and TELEGRAM_API_HASH environment variables must be set")
      return

  try:
    app = Client(
        "file_transfer_bot",
        api_id=int(api_id),  # Check if TELEGRAM_API_ID exists
        api_hash=api_hash, # Check if TELEGRAM_API_HASH exists
        bot_token=TELEGRAM_BOT_TOKEN
    )
  except ValueError as e:
       logger.error(f"Error: TELEGRAM_API_ID must be an integer. {e}")
       return


  @app.on_message(filters.command("start"))
  async def start_command(client, message):
    await start(client,message)

  @app.on_message(filters.text & ~filters.command("start"))
  async def handle_text_messages(client, message):
    await handle_url_download(client, message)

  @app.on_message(filters.document | filters.video)
  async def handle_file_messages(client, message):
        await handle_file_download(client, message)

  print("Bot is running...")
  await app.run()

if __name__ == "__main__":
   asyncio.run(main())
