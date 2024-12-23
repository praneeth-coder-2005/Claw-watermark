import os
import telebot
import subprocess
import threading
import requests

# --- CONFIGURATION ---
TELEGRAM_BOT_TOKEN = "7974031259:AAG2hVunyhQZsLXS44TROPKbjmruuwBLxDY"  # Replace with your token
WATERMARK_IMAGE = "https://envs.sh/JuG.jpg" # Replace if you are using image watermark
WATERMARK_TEXT = "@ClawMoviez" # Replace with your watermark text
TEMP_DIR = "temp_files"  # For temporary file storage

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)


def create_temp_dir():
  """Creates the temporary directory for saving files, if not exist"""
  if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)
  return TEMP_DIR


def download_file(url, file_path):
    """Downloads a file."""
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)

        with open(file_path, 'wb') as file:
            for chunk in response.iter_content(chunk_size=8192):
                file.write(chunk)
        return True
    except requests.exceptions.RequestException as e:
        print(f"Error downloading the file: {e}")
        return False

def add_video_watermark(video_path, output_path, watermark_image, watermark_text):
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

        subprocess.run(
            command,
            check=True,  # Raise exception if ffmpeg fails
            capture_output=True
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error processing the video with ffmpeg: {e.stderr.decode()}")
        return False
    except FileNotFoundError:
        print("ffmpeg not found. Please ensure it is in your system's PATH")
        return False

def send_telegram_file(bot, file_path, chat_id):
    """Sends a file to Telegram."""
    try:
        with open(file_path, "rb") as file:
            bot.send_document(chat_id=chat_id, document=file)
        return True
    except Exception as e:
      print(f"Error sending the telegram file: {e}")
      return False


def process_video(message, url):
  """Processes video file, including download, watermark, and sending."""
  temp_dir = create_temp_dir()
  file_name = url.split("/")[-1]
  file_path = os.path.join(temp_dir, file_name)
  output_path = os.path.join(temp_dir, "watermarked_" + file_name)

  bot.send_message(message.chat.id, "Downloading file...")
  if not download_file(url, file_path):
      bot.send_message(message.chat.id, "Download failed.")
      return

  bot.send_message(message.chat.id, "Applying watermark...")
  if add_video_watermark(file_path, output_path, WATERMARK_IMAGE, WATERMARK_TEXT):
      file_to_send = output_path
      bot.send_message(message.chat.id, "Watermark applied. Sending file.")
  else:
      file_to_send = file_path
      bot.send_message(message.chat.id, "Watermark failed. Sending original file.")

  if send_telegram_file(bot, file_to_send, message.chat.id):
    bot.send_message(message.chat.id, "File sent successfully!")
  else:
    bot.send_message(message.chat.id, "File sending failed.")


  # Clean up temporary files
  os.remove(file_path)
  if file_to_send != file_path:
    os.remove(file_to_send)

@bot.message_handler(commands=['start'])
def handle_start(message):
    bot.send_message(message.chat.id, "Hello, I am the watermark bot. Send me the file link and I'll add the watermark!")

@bot.message_handler(func=lambda message: True)
def handle_file_download(message):
  """Handles incoming messages, and creates thread for processing."""
  if message and message.text:
    url = message.text
    threading.Thread(target=process_video, args=(message, url)).start()


def main():
    bot.delete_webhook()
    print("Bot is running...")
    bot.polling(non_stop=True)


if __name__ == "__main__":
    main()
