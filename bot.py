import os
import telebot
import threading
import requests
import logging
from config import TELEGRAM_BOT_TOKEN, TEMP_DIR

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

def create_temp_dir():
    """Creates the temporary directory for saving files, if not exist"""
    if not os.path.exists(TEMP_DIR):
        os.makedirs(TEMP_DIR)
    return TEMP_DIR

def download_file_stream(url, file_path):
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


def send_telegram_file_chunks(bot, file_path, chat_id):
    """Sends a file to Telegram in chunks."""
    try:
        file_size = os.path.getsize(file_path)
        if file_size > 50 * 1024 * 1024:  # 50 MB max size for document
            logger.info(f"File size {file_size} exceeds 50MB, sending as chunks")
            bot.send_message(chat_id=chat_id, text="Sending large file in chunks...")
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
                            bot.send_media_group(chat_id=chat_id, media=media_list)
                        else:
                            bot.send_media_group(chat_id=chat_id, media=media_list)
                        media_list = []
                    #check if video or document
                    if file_path.lower().endswith(('.mp4', '.avi', '.mov', '.mkv')):
                        media_list.append(telebot.types.InputMediaVideo(chunk))
                    else:
                        media_list.append(telebot.types.InputMediaDocument(chunk))
                    i = i + 1

                if media_list:
                   if file_path.lower().endswith(('.mp4', '.avi', '.mov', '.mkv')):
                      bot.send_media_group(chat_id=chat_id, media=media_list)
                   else:
                      bot.send_media_group(chat_id=chat_id, media=media_list)
        else:
            logger.info(f"File size {file_size} does not exceed 50MB, sending as single file")
            with open(file_path, 'rb') as file:
              if file_path.lower().endswith(('.mp4', '.avi', '.mov', '.mkv')):
                bot.send_video(chat_id=chat_id, video=file)
              else:
                  bot.send_document(chat_id=chat_id, document=file)
        return True
    except Exception as e:
        logger.error(f"Error sending telegram file: {e}")
        return False


def process_file(message, file_path):
    """Processes the file, including download, and sending."""
    try:
        chat_id = message.chat.id

        bot.send_message(chat_id, "Downloading file...")

        if send_telegram_file_chunks(bot, file_path, chat_id):
            bot.send_message(chat_id, "File sent successfully!")
        else:
            bot.send_message(chat_id, "File sending failed.")

        # Clean up temporary files
        os.remove(file_path)

    except Exception as e:
        logger.error(f"Error in processing file: {e}")
        bot.send_message(chat_id, f"An unexpected error has occurred: {e}")

def handle_file_download_from_telegram(message):
    """Handles incoming document and video messages from telegram."""
    try:
        chat_id = message.chat.id
        if message.document:
            logger.info(f"Received a document message: {message.document.file_name} and {message.document.file_id}")
            file_id = message.document.file_id
            file_name = message.document.file_name
            file_path = os.path.join(create_temp_dir(), file_name)

            file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_id}"

            if not download_file_stream(file_url, file_path):
              bot.send_message(chat_id=chat_id, text="Download failed.")
              return
            threading.Thread(target=process_file, args=(message, file_path)).start()


        elif message.video:
          logger.info(f"Received a video message: {message.video.file_name} and {message.video.file_id}")
          file_id = message.video.file_id
          file_name = message.video.file_name
          file_path = os.path.join(create_temp_dir(), file_name)

          file_url =  f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_id}"

          if not download_file_stream(file_url, file_path):
               bot.send_message(chat_id=chat_id, text="Download failed.")
               return
          threading.Thread(target=process_file, args=(message, file_path)).start()

    except Exception as e:
      logger.error(f"Error in handle_file_download: {e}")
      bot.send_message(chat_id, f"An unexpected error has occurred: {e}")

def handle_url_download(message):
  """Handles incoming URL text messages."""
  try:
        chat_id = message.chat.id
        url = message.text

        if not url.startswith("http://") and not url.startswith("https://"):
            bot.send_message(chat_id=chat_id, text="Invalid URL format. Please provide a valid http or https URL.")
            return

        file_name = os.path.basename(url)
        file_path = os.path.join(create_temp_dir(), file_name)

        if not download_file_stream(url, file_path):
            bot.send_message(chat_id=chat_id, text="Download from URL failed.")
            return

        threading.Thread(target=process_file, args=(message, file_path)).start()

  except Exception as e:
        logger.error(f"An unexpected error occurred in handle_url_download: {e}")
        bot.send_message(chat_id, f"An unexpected error has occurred: {e}")


@bot.message_handler(commands=['start'])
def handle_start(message):
    bot.send_message(message.chat.id, "Hello, I am a file transfer bot. Send me a file or a file URL, and I'll send it back!")

@bot.message_handler(func=lambda message: message.text and not message.text.startswith('/'))
def handle_text_messages(message):
  """Handles incoming text message and creates a thread."""
  handle_url_download(message)


@bot.message_handler(content_types=['document', 'video'])
def handle_file_messages(message):
   handle_file_download_from_telegram(message)

def main():
    bot.delete_webhook()
    print("Bot is running...")
    bot.polling(none_stop=True)


if __name__ == '__main__':
    main()
