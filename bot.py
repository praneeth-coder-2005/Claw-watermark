import os
import asyncio
import subprocess
import logging
from telegram import Bot, Update, InputMediaDocument, InputMediaVideo
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from telegram.error import TelegramError
import requests
from config import TELEGRAM_BOT_TOKEN, WATERMARK_IMAGE, WATERMARK_TEXT, TEMP_DIR

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

async def add_video_watermark(video_path, output_path, watermark_image, watermark_text):
    """Adds a watermark to a video using ffmpeg (image or text)."""
    try:
        if watermark_image and os.path.exists(watermark_image):
          # Watermark using image
          filter_complex = f"[1:v]scale=300:-1[wm];[0:v][wm]overlay=10:10"
          command = [
            "ffmpeg",
            "-i",
            video_path,
            "-i",
            watermark_image,
            "-filter_complex",
            filter_complex,
            output_path
          ]

        elif watermark_text:
          # Watermark using text
          drawtext_params = f"text='{watermark_text}':fontsize=30:fontcolor=white:x=10:y=10"
          command = [
              "ffmpeg",
              "-i",
              video_path,
              "-vf",
              f"drawtext={drawtext_params}",
              output_path
            ]
        else:
            return False


        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            logger.error(f"Error processing the video with ffmpeg: {stderr.decode()}")
            return False
        return True
    except FileNotFoundError:
        logger.error("ffmpeg not found. Please ensure it is in your system's PATH")
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
    """Processes the file, including download, watermark, and sending."""
    try:
        chat_id = update.effective_chat.id
        output_path = os.path.join(TEMP_DIR, "watermarked_" + os.path.basename(file_path))

        await context.bot.send_message(chat_id=chat_id, text="Applying watermark...")

        if file_type == "video":
            if await add_video_watermark(file_path, output_path, WATERMARK_IMAGE, WATERMARK_TEXT):
                file_to_send = output_path
                await context.bot.send_message(chat_id=chat_id, text="Watermark applied. Sending file...")
            else:
                file_to_send = file_path
                await context.bot.send_message(chat_id=chat_id, text="Watermark failed. Sending original file...")
        else:
            file_to_send = file_path
            await context.bot.send_message(chat_id=chat_id, text="File is not a video. Sending original file...")


        if await send_telegram_file_chunks(context.bot, file_to_send, chat_id):
            await context.bot.send_message(chat_id=chat_id, text="File sent successfully!")
        else:
            await context.bot.send_message(chat_id=chat_id, text="File sending failed.")

        # Clean up temporary files
        os.remove(file_path)
        if file_to_send != file_path:
            os.remove(file_to_send)


    except Exception as e:
        logger.error(f"Error in processing file: {e}")
        await context.bot.send_message(chat_id=chat_id, text=f"An unexpected error has occurred: {e}")

async def handle_file_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles incoming document and video messages."""
    try:
        chat_id = update.effective_chat.id
        if update.message.document:
            logger.info(f"Received a document message: {update.message.document.file_name} and {update.message.document.file_id}")
            file_id = update.message.document.file_id
            file_name = update.message.document.file_name
            file_path = os.path.join(create_temp_dir(), file_name)

            try:
              file_info = await context.bot.get_file(file_id)
              file_url =  f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_info.file_path}"
            except TelegramError as e:
              logger.error(f"Error getting file info: {e}")
              await context.bot.send_message(chat_id=chat_id, text=f"Error getting file information.")
              return


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

            try:
               file_info = await context.bot.get_file(file_id)
               file_url =  f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_info.file_path}"
            except TelegramError as e:
              logger.error(f"Error getting file info: {e}")
              await context.bot.send_message(chat_id=chat_id, text=f"Error getting file information.")
              return

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
  await context.bot.send_message(chat_id=update.effective_chat.id, text="Hello, I am the watermark bot. Send me the file and I'll add the watermark!")

def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.ALL, handle_file_download))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
