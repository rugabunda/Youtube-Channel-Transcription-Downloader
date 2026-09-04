#!/usr/bin/env python3
# Standard library imports
import sys
import os
import json
import subprocess
import time
import re
import concurrent.futures
import argparse
import locale
import signal
import shutil
import random
import logging

# Third-party imports
from youtube_transcript_api import (
    YouTubeTranscriptApi,
    YouTubeTranscriptApiException,
    NoTranscriptFound,
    TranscriptsDisabled,
    IpBlocked,
    RequestBlocked,
    VideoUnavailable,
    VideoUnplayable,
    CouldNotRetrieveTranscript,
    AgeRestricted,
    YouTubeRequestFailed,
    InvalidVideoId
)
from tqdm import tqdm
from colorama import Fore, Back, Style, init as colorama_init

# Initialize colorama for cross-platform colored terminal text
colorama_init(autoreset=True)

# ==============================================================================
# SAFETY & RATE LIMITING CONFIGURATION
# ==============================================================================
# Adjust these values at the top of the script to prevent IP bans.
# If you have been banned before, it is highly recommended to keep these 
# values high (conservative) to avoid triggering YouTube's anti-scraping 
# defenses.
# ==============================================================================

# DEFAULT_DELAY: Time in seconds to wait between EACH download attempt.
# Default is 7.0 seconds. This adds a safe buffer between requests.
DEFAULT_DELAY = 7.0

# DEFAULT_WORKERS: Number of concurrent download threads.
# Default is 1. Using more than 1 worker drastically increases the risk of a ban.
DEFAULT_WORKERS = 1

# MIN_DELAY: The absolute minimum delay allowed via command-line arguments.
# This acts as a safeguard against accidental command-line typos.
MIN_DELAY = 3.0

# MAX_WORKERS: The absolute maximum number of workers allowed via command-line.
MAX_WORKERS = 2
# ==============================================================================

# Initialize the YouTube Transcript API instance globally
ytt_api = YouTubeTranscriptApi()

# Set up logging configuration with color support
class ColoredFormatter(logging.Formatter):
    """Custom formatter to add colors to log messages"""
    
    COLORS = {
        'DEBUG': Fore.CYAN,
        'INFO': Fore.WHITE,
        'WARNING': Fore.YELLOW,
        'ERROR': Fore.RED,
        'CRITICAL': Fore.RED + Style.BRIGHT,
    }
    
    def format(self, record):
        levelname = record.levelname
        if levelname in self.COLORS:
            record.levelname = f"{self.COLORS[levelname]}{levelname}{Style.RESET_ALL}"
            if record.levelno == logging.INFO:
                record.msg = f"{Fore.WHITE}{record.msg}{Style.RESET_ALL}"
            elif record.levelno == logging.WARNING:
                record.msg = f"{Fore.YELLOW}{record.msg}{Style.RESET_ALL}"
            elif record.levelno == logging.ERROR or record.levelno == logging.CRITICAL:
                record.msg = f"{Fore.RED}{record.msg}{Style.RESET_ALL}"
        return super().format(record)

# Configure logger
handler = logging.StreamHandler()
handler.setFormatter(ColoredFormatter('%(message)s'))
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(handler)

# Global variables to track active processes
active_processes = []

# Ban detection and recovery tracking
original_delay = None
original_workers = None
ban_detected = False
ban_recovery_time = None

def signal_handler(sig, frame):
    """Handle termination signals properly."""
    print(f"\n{Fore.YELLOW}Script termination requested. Cleaning up...{Style.RESET_ALL}")
    # Kill any active subprocesses
    for process in active_processes:
        try:
            if process.poll() is None:  # Process is still running
                process.terminate()
        except Exception as e:
            print(f"{Fore.RED}Error terminating process: {e}{Style.RESET_ALL}")
    
    print(f"{Fore.GREEN}Cleanup complete. Exiting.{Style.RESET_ALL}")
    os._exit(0)  # Use os._exit to force immediate termination

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
signal.signal(signal.SIGTERM, signal_handler)  # Kill command
if hasattr(signal, 'SIGTSTP'):  # Ctrl+Z (not available on Windows)
    signal.signal(signal.SIGTSTP, signal_handler)

def sanitize_filename(name):
    """Remove invalid characters from filenames."""
    return re.sub(r'[\\/*?:"<>|]', "_", name)

def display_logo():
    """Display an attractive ASCII logo."""
    logo = f"""
{Fore.CYAN}╭━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╮
{Fore.CYAN}┃ {Fore.YELLOW}__   __          _____      _            _____                          {Fore.CYAN}┃
{Fore.CYAN}┃ {Fore.YELLOW}\ \ / /__  _   _|_   _|   _| |__   ___  |_   _| __ __ _ _ __  ___  ___  {Fore.CYAN}┃
{Fore.CYAN}┃ {Fore.YELLOW} \ V / _ \| | | | | || | | | '_ \ / _ \   | || '__/ _` | '_ \/ __|/ __| {Fore.CYAN}┃
{Fore.CYAN}┃ {Fore.YELLOW}  | | (_) | |_| | | || |_| | |_) |  __/   | || | | (_| | | | \__ \ (__  {Fore.CYAN}┃
{Fore.CYAN}┃ {Fore.YELLOW}  |_|\___/ \__,_| |_| \__,_|_.__/ \___|   |_||_|  \__,_|_| |_|___/\___| {Fore.CYAN}┃
{Fore.CYAN}┃                                                                         {Fore.CYAN}┃
{Fore.CYAN}┃ {Fore.GREEN}Channel Transcript Downloader                                    v1.1.0 {Fore.CYAN}┃
{Fore.CYAN}╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯
{Style.RESET_ALL}"""
    print(logo)

def display_help(show_logo=True):
    """Display usage instructions and available languages."""
    if show_logo:
        display_logo()
    print(f"{Fore.CYAN}=" * 80)
    print(f"{Fore.YELLOW}USAGE INSTRUCTIONS")
    print(f"{Fore.CYAN}=" * 80)
    print("\nThis script downloads transcripts for videos on YouTube channels or individual videos.")
    print("It creates a separate folder for each channel and organizes files into subdirectories.")
    print(f"{Fore.YELLOW}Downloads are processed with rate limiting to avoid YouTube IP bans.")
    print("Files that already exist will be skipped, allowing you to resume or update channels.")
    
    print(f"\n{Fore.GREEN}USAGE:")
    print(f"  python Youtube.Transcribe.py [options] <channel_or_video_url(s)>")
    
    print(f"\n{Fore.GREEN}EXAMPLES:")
    print(f"{Fore.CYAN}  # Download transcript for a single YouTube video")
    print("  python Youtube.Transcribe.py https://www.youtube.com/watch?v=dQw4w9WgXcQ -en")
    print(f"{Fore.CYAN}  # Short URL also works")
    print("  python Youtube.Transcribe.py https://youtu.be/dQw4w9WgXcQ -en")
    print(f"{Fore.CYAN}  # Multiple URLs also works")
    print("  Youtube.Transcribe.py https://youtu.be/aDkzgTWhVY4 https://youtu.be/3ZC1iqYfFGU -en")
    
    print(f"{Fore.CYAN}  # Download English transcripts from a channel")
    print("  python Youtube.Transcribe.py https://www.youtube.com/channel/UC-lHJZR3Gqxm24_Vd_AJ5Yw -en")
    
    print(f"{Fore.CYAN}  # Download multiple languages")
    print("  python Youtube.Transcribe.py https://youtube.com/c/channel1 -en -es -fr")
    
    print(f"{Fore.CYAN}  # Download all available languages")
    print("  python Youtube.Transcribe.py https://youtube.com/c/channel1 -all")
    
    print(f"{Fore.CYAN}  # Download only TXT files (no JSON)")
    print("  python Youtube.Transcribe.py https://youtube.com/c/channel1 -en -txt")
    
    print(f"{Fore.CYAN}  # Download only JSON files (no TXT)")
    print("  python Youtube.Transcribe.py https://youtube.com/c/channel1 -en -json")
    
    print(f"{Fore.CYAN}  # Faster downloads (may increase risk of IP ban)")
    print("  python Youtube.Transcribe.py https://youtube.com/c/channel1 -en -delay 3 -workers 2")
    
    print(f"{Fore.CYAN}  # Slower, safer downloads (to prevent IP bans)")
    print(f"  python Youtube.Transcribe.py https://youtube.com/c/channel1 -en -delay {DEFAULT_DELAY} -workers {DEFAULT_WORKERS}")
    
    print(f"{Fore.CYAN}  # Download from multiple channels")
    print("  python Youtube.Transcribe.py https://youtube.com/c/channel1 https://youtube.com/c/channel2 -en")
    
    print(f"{Fore.CYAN}  # Download from channels listed in a file (one URL per line or comma-separated)")
    print("  python Youtube.Transcribe.py -f channels.txt -en")
    
    print(f"\n{Fore.GREEN}OPTIONS:")
    print(f"{Fore.YELLOW}  -f, --file FILE{Style.RESET_ALL}    Read channel URLs from a text file (one per line or comma-separated)")
    print(f"{Fore.YELLOW}  -LANG{Style.RESET_ALL}              Language code for transcripts (e.g., -en for English)")
    print("                     Multiple language codes can be specified (e.g., -en -es -fr)")
    print(f"{Fore.YELLOW}  -all{Style.RESET_ALL}               Download all available languages for each video")
    print(f"{Fore.YELLOW}  -txt{Style.RESET_ALL}               Download only TXT files (no JSON)")
    print(f"{Fore.YELLOW}  -json{Style.RESET_ALL}              Download only JSON files (no TXT)")
    print(f"{Fore.YELLOW}  -delay N{Style.RESET_ALL}           Delay between API requests in seconds (default: {DEFAULT_DELAY})")
    print("                     Higher values reduce risk of IP bans but slow downloads")
    print(f"{Fore.YELLOW}  -workers N{Style.RESET_ALL}         Number of concurrent downloads (default: {DEFAULT_WORKERS}, max: {MAX_WORKERS})")
    print("                     Lower values reduce risk of IP bans but slow downloads")
    print(f"{Fore.YELLOW}  -h, --help{Style.RESET_ALL}         Show this help message")
    
    print(f"\n{Fore.GREEN}RATE LIMITING:")
    print(f"{Fore.YELLOW}  To avoid YouTube IP bans, this script implements several protection measures:")
    print("  1. Request delays: Controlled delay between API calls (adjust with -delay)")
    print("  2. Random jitter: ±20% randomness added to each delay to avoid pattern detection")
    print("  3. Limited concurrency: Restricted parallel downloads (adjust with -workers)")
    print("  4. Smart retries: Automatic detection of non-retryable errors (age-restricted videos, etc.)")
    print("  5. Exponential backoff: Increasingly longer delays after rate limit errors")
    print("  6. Error skipping: No retry for videos that cannot have transcripts (subtitles disabled, etc.)")
    
    print(f"\n{Fore.GREEN}  RECOMMENDED SETTINGS:")
    print(f"  - Safe usage: Default values ({Fore.CYAN}-delay {DEFAULT_DELAY} -workers {DEFAULT_WORKERS}{Style.RESET_ALL})")
    print(f"  - If IP banned:")
    print("    1. Switch to very slow settings (-delay 10 -workers 1) until ban is lifted")
    print("    2. After ban is lifted, continue with these slow settings for 5-7 minutes")
    print("    3. Then reduce to half your original speed (double delay, halve workers)")
    print("    4. If banned again, repeat the halving process until bans stop permanently")
    
    print(f"\n{Fore.GREEN}REQUIREMENTS:")
    print("  - python 3.6+")
    print("  - youtube_transcript_api (pip install youtube-transcript-api)")
    print("  - yt-dlp (pip install yt-dlp)")
    print("  - colorama (pip install colorama)")
    print("  - tqdm (pip install tqdm)")
    print(f"{Fore.CYAN}=" * 80)

def get_system_language():
    """Get the user's system language."""
    try:
        # Set locale to the user's default
        locale.setlocale(locale.LC_ALL, '')
        
        # Try to get the language from the locale
        lang_code = None
        
        # First try getlocale
        try:
            loc = locale.getlocale(locale.LC_MESSAGES)
            if loc and loc[0]:
                lang_code = loc[0].split('_')[0].lower()
        except (AttributeError, ValueError):
            pass
            
        # If that didn't work, try getencoding
        if not lang_code:
            try:
                encoding = locale.getencoding()
                if encoding and encoding.startswith(('en', 'es', 'fr', 'de', 'it', 'ja', 'ko', 'ru', 'zh')):
                    lang_code = encoding[:2]
            except (AttributeError, ValueError):
                pass
                
        # If we found a language code, use it
        if lang_code:
            logging.info(f"Detected system language: {Fore.CYAN}{lang_code}{Style.RESET_ALL}")
            return lang_code
            
    except Exception as e:
        logging.warning(f"Could not detect system language: {e}")
    
    logging.info(f"Defaulting to {Fore.CYAN}English (en){Style.RESET_ALL}")
    return 'en'

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="YouTube Channel Transcript Downloader", add_help=False)
    parser.add_argument('-f', '--file', help="File containing channel URLs")
    parser.add_argument('-h', '--help', action='store_true', help="Show help message")
    parser.add_argument('-all', action='store_true', help="Download all available languages")
    parser.add_argument('-txt', action='store_true', help="Download only TXT files")
    parser.add_argument('-json', action='store_true', help="Download only JSON files")
    parser.add_argument('-delay', type=float, default=DEFAULT_DELAY, help=f"Delay between API requests in seconds (default: {DEFAULT_DELAY})")
    parser.add_argument('-workers', type=int, default=DEFAULT_WORKERS, help=f"Number of concurrent downloads (default: {DEFAULT_WORKERS})")
    
    # First parse just the file and help arguments
    args, remaining = parser.parse_known_args()
    
    if args.help or len(sys.argv) <= 1:  # Show help if -h or no arguments
        display_help(show_logo=False)  # Logo is already displayed in main()
        sys.exit(0)
        
    # Extract channel URLs and languages
    urls = []
    languages = []
    download_all = args.all  # Flag to download all languages
    download_txt = True if not args.json else False  # Default to both unless only JSON is specified
    download_json = True if not args.txt else False  # Default to both unless only TXT is specified
    delay = max(MIN_DELAY, args.delay)  # Ensure minimum delay
    workers = max(1, min(MAX_WORKERS, args.workers))  # Limit workers
    
    # Check for conflict
    if args.txt and args.json:
        logging.warning("Both -txt and -json specified. Will download both formats.")
        download_txt = True
        download_json = True
    
    # Parse URLs from file if specified
    if args.file:
        if not os.path.exists(args.file):
            logging.error(f"File not found: {args.file}")
            sys.exit(1)
        
        try:
            with open(args.file, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Split by commas or newlines
            content = content.replace(',', '\n')
            file_urls = [url.strip() for url in content.split('\n') if url.strip()]
            urls.extend(file_urls)
            
            logging.info(f"Loaded {Fore.CYAN}{len(file_urls)}{Style.RESET_ALL} URLs from file: {Fore.CYAN}{args.file}{Style.RESET_ALL}")
        except Exception as e:
            logging.error(f"Error reading file {args.file}: {str(e)}")
            sys.exit(1)
    
    # Parse URLs and languages from command line
    for arg in remaining:
        if arg.startswith('-'):
            if arg == '-all':
                download_all = True
            elif arg == '-txt':
                download_txt = True
                download_json = False
            elif arg == '-json':
                download_json = True
                download_txt = False
            elif arg.startswith('-delay') or arg.startswith('-workers'):
                # These are already handled by argparse
                continue
            else:
                # This is a language code
                lang_code = arg[1:]  # Remove the dash
                languages.append(lang_code)
        elif arg.startswith(('http://', 'https://', 'www.')):
            urls.append(arg)  # This is a URL
    
    # Ensure we have at least one URL
    if not urls:
        logging.error("No channel URLs provided. Use -h for help.")
        sys.exit(1)
    
    # Default to system language if no language is specified and not downloading all
    if not languages and not download_all:
        languages = [get_system_language()]
    
    return urls, languages, download_all, download_txt, download_json, delay, workers

def detect_languages_in_folder(channel_dir):
    """Detect existing transcript languages in a channel directory."""
    languages = set()
    
    if not os.path.exists(channel_dir):
        return languages
    
    # First check for dedicated language folders
    for item in os.listdir(channel_dir):
        item_path = os.path.join(channel_dir, item)
        # Check if it's a directory and follows language code naming pattern (2-10 characters)
        # Exclude the "json" directory from being treated as a language
        if os.path.isdir(item_path) and re.match(r'^[a-zA-Z\-]{2,10}$', item) and item != "json":
            languages.add(item)
    
    # If no language folders, check file suffixes
    if not languages:
        # Check TXT files in main folder
        for file in os.listdir(channel_dir):
            if file.endswith(".txt"):
                # Extract language from filename (assuming format: *_LANG.txt)
                match = re.search(r'_([a-zA-Z\-]{2,10})\.txt$', file)
                if match:
                    languages.add(match.group(1))
        
        # Check JSON files in json folder
        json_dir = os.path.join(channel_dir, "json")
        if os.path.exists(json_dir) and os.path.isdir(json_dir):
            for file in os.listdir(json_dir):
                if file.endswith(".json"):
                    # Extract language from filename (assuming format: *_LANG.json)
                    match = re.search(r'_([a-zA-Z\-]{2,10})\.json$', file)
                    if match:
                        languages.add(match.group(1))
    
    return languages

def normalize_channel_url(url):
    """
    Normalize YouTube channel URLs to ensure yt-dlp can extract all videos.
    Appends '/videos' to channel URLs if they don't already point to a specific tab.
    """
    if not url:
        return url
        
    # Only process YouTube channel/user URLs
    if not any(x in url for x in ['/channel/', '/c/', '/user/', '/@']):
        return url
        
    # Don't modify if it already has a specific tab or playlist
    if any(x in url for x in ['/videos', '/playlists', '/shorts', '/streams', '/community', '/about', '/featured']):
        return url
        
    # Append /videos to ensure yt-dlp extracts the video list
    return url.rstrip('/') + '/videos'

def is_single_video_url(url):
    """Check if the URL points to a single video rather than a channel or playlist."""
    if not url:
        return False
    return any(x in url for x in ['watch?v=', 'youtu.be/', '/shorts/', '/live/'])

def get_channel_name(channel_url):
    """Get the channel name for directory creation."""
    logging.info("Retrieving channel name...")
    
    try:
        command = [
            "yt-dlp",
            "--skip-download",
            "--print", "%(channel)s",
            "-q",
            "--no-warnings"
        ]
        
        if not is_single_video_url(channel_url):
            command.extend(["--playlist-items", "1"])
            
        command.append(channel_url)
        
        logging.debug(f"Running command: {' '.join(command)}")
        
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        active_processes.append(process)
        
        try:
            stdout, stderr = process.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            logging.error("Timeout while fetching channel name")
            process.kill()
            stdout, stderr = process.communicate()
            return "youtube_channel"
        finally:
            if process in active_processes:
                active_processes.remove(process)
        
        channel_name = stdout.strip()
        
        if not channel_name:
            logging.warning("Couldn't retrieve channel name, using default.")
            if stderr.strip():
                logging.debug(f"yt-dlp stderr: {stderr.strip()[:500]}")
            return "youtube_channel"
            
        logging.info(f"Channel name: {Fore.CYAN}{channel_name}{Style.RESET_ALL}")
        return sanitize_filename(channel_name)
    
    except Exception as e:
        logging.error(f"Error fetching channel name: {e}")
        return "youtube_channel"

def get_videos_from_channel(channel_url):
    """Get all video IDs and titles from a YouTube channel using yt-dlp."""
    logging.info(f"Fetching videos from: {Fore.CYAN}{channel_url}{Style.RESET_ALL}")
    logging.info("This may take a while for channels with many videos...")
    
    print(f"{Fore.CYAN}Executing yt-dlp... (please wait){Style.RESET_ALL}")
    
    try:
        command = [
            "yt-dlp", 
            "--print", "%(id)s %(title)s",
            "--no-warnings"
        ]
        
        if not is_single_video_url(channel_url):
            command.insert(1, "--flat-playlist")
            
        command.append(channel_url)
        
        logging.debug(f"Running command: {' '.join(command)}")
        
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        active_processes.append(process)
        
        try:
            stdout, stderr = process.communicate(timeout=600)
        except subprocess.TimeoutExpired:
            logging.error("Timeout while fetching videos list. Try again or use a different channel.")
            process.kill()
            stdout, stderr = process.communicate()
            return []
        finally:
            if process in active_processes:
                active_processes.remove(process)
        
        if not stdout.strip():
            logging.error("No video data returned. Check the channel URL.")
            if stderr.strip():
                err_snippet = stderr.strip()[:500]
                logging.error(f"yt-dlp output: {err_snippet}")
                if any(x in err_snippet.lower() for x in ["bot", "sign in", "consent", "403", "forbidden"]):
                    logging.warning(f"{Fore.YELLOW}Hint: YouTube may be blocking yt-dlp. Try updating yt-dlp (`pip install --upgrade yt-dlp`) or using a cookies file.{Style.RESET_ALL}")
            return []
            
        videos_data = []
        lines = stdout.strip().split('\n')
        
        print(f"{Fore.GREEN}Found {len(lines)} videos. Processing...{Style.RESET_ALL}")
        
        # Process the video data
        for line in lines:
            if line:
                parts = line.split(maxsplit=1)
                if len(parts) >= 2:
                    video_id = parts[0]
                    title = parts[1]
                    videos_data.append({
                        'id': video_id,
                        'title': title
                    })
                else:
                    logging.warning(f"Couldn't parse video data from: {line}")
        
        logging.info(f"Total videos found: {Fore.GREEN}{len(videos_data)}{Style.RESET_ALL}")
        return videos_data
    
    except Exception as e:
        logging.error(f"Error fetching videos from channel: {e}")
        return []

def should_use_language_folders(existing_languages, requested_languages):
    """Determine if we should use language-specific folders."""
    if len(requested_languages) > 1:
        return True
    
    if len(existing_languages) > 1:
        return True
    
    if len(requested_languages) == 1 and len(existing_languages) == 1:
        if list(requested_languages)[0] not in existing_languages:
            return True
    
    if len(requested_languages) == 1 and len(existing_languages) == 0:
        return False
    
    if len(requested_languages) == 1 and len(existing_languages) > 0:
        if list(requested_languages)[0] not in existing_languages:
            return True
    
    return False

def move_files_to_language_folders(channel_dir, languages):
    """Move existing files to language-specific folders if needed."""
    if not os.path.exists(channel_dir):
        return
    
    logging.info(f"{Fore.YELLOW}Reorganizing existing files into language folders...{Style.RESET_ALL}")
    
    for lang in languages:
        lang_dir = os.path.join(channel_dir, lang)
        os.makedirs(lang_dir, exist_ok=True)
        json_dir = os.path.join(lang_dir, "json")
        os.makedirs(json_dir, exist_ok=True)
    
    files_to_move = []
    for file in os.listdir(channel_dir):
        if file.endswith(".txt"):
            for lang in languages:
                if f"_{lang}.txt" in file:
                    files_to_move.append((file, lang, "txt"))
    
    json_dir = os.path.join(channel_dir, "json")
    if os.path.exists(json_dir) and os.path.isdir(json_dir):
        for file in os.listdir(json_dir):
            if file.endswith(".json"):
                for lang in languages:
                    if f"_{lang}.json" in file:
                        files_to_move.append((file, lang, "json"))
    
    if files_to_move:
        with tqdm(total=len(files_to_move), desc=f"{Fore.YELLOW}Moving files{Style.RESET_ALL}", colour='yellow') as pbar:
            for file, lang, file_type in files_to_move:
                if file_type == "txt":
                    src = os.path.join(channel_dir, file)
                    dst = os.path.join(channel_dir, lang, file)
                else:
                    src = os.path.join(channel_dir, "json", file)
                    dst = os.path.join(channel_dir, lang, "json", file)
                
                if not os.path.exists(dst):
                    try:
                        shutil.move(src, dst)
                    except Exception as e:
                        logging.error(f"Error moving file {file}: {e}")
                pbar.update(1)
        
        logging.info(f"Successfully moved {Fore.GREEN}{len(files_to_move)}{Style.RESET_ALL} files to language-specific folders")
    else:
        logging.info("No files needed to be moved")
    
    json_dir = os.path.join(channel_dir, "json")
    if os.path.exists(json_dir) and os.path.isdir(json_dir):
        if not os.listdir(json_dir):
            try:
                os.rmdir(json_dir)
            except Exception as e:
                logging.error(f"Error removing empty json directory: {e}")
    
    logging.info(f"{Fore.GREEN}File reorganization complete{Style.RESET_ALL}")

def get_available_languages(video_id):
    """Get all available languages for a video using the new API."""
    try:
        with tqdm(total=1, desc=f"{Fore.CYAN}Checking available languages{Style.RESET_ALL}", bar_format='{desc}: {bar}| {elapsed}', colour='cyan') as pbar:
            transcript_list = ytt_api.list(video_id)
            languages = []
            
            for transcript in transcript_list:
                # Get the language code
                lang_code = transcript.language_code
                languages.append(lang_code)
            
            pbar.update(1)
        return languages
    except Exception as e:
        logging.error(f"Error getting available languages for video {video_id}: {e}")
        return []

def controlled_delay(base_delay):
    """Add a controlled delay with jitter to avoid predictable patterns."""
    # Add random jitter (±20% of base delay)
    jitter = base_delay * 0.2 * (random.random() * 2 - 1)
    sleep_time = base_delay + jitter
    time.sleep(sleep_time)

def adjust_rate_for_ban_recovery(current_delay, current_workers):
    """Adjust rate limiting parameters when a ban is detected or after recovery."""
    global original_delay, original_workers, ban_detected, ban_recovery_time
    
    if original_delay is None:
        original_delay = current_delay
        original_workers = current_workers
    
    if not ban_detected:
        ban_detected = True
        print(f"\n{Fore.RED}⚠️  YouTube rate limit/ban detected! Switching to recovery mode...{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}Original settings: delay={original_delay}s, workers={original_workers}{Style.RESET_ALL}")
        print(f"{Fore.GREEN}Switching to slow mode: delay=10s, workers=1{Style.RESET_ALL}")
        return 10.0, 1
    
    if ban_recovery_time is None:
        ban_recovery_time = time.time()
        print(f"\n{Fore.GREEN}✓ Ban appears to be lifted, starting recovery period...{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}Continuing slow mode for 5-7 minutes: delay=10s, workers=1{Style.RESET_ALL}")
        return 10.0, 1
    
    minutes_since_recovery = (time.time() - ban_recovery_time) / 60
    if minutes_since_recovery < random.uniform(5, 7):
        return 10.0, 1
    
    new_delay = original_delay * 2
    new_workers = max(1, original_workers // 2)
    
    original_delay = new_delay
    original_workers = new_workers
    
    ban_detected = False
    ban_recovery_time = None
    
    print(f"\n{Fore.GREEN}✓ Recovery period complete. Switching to half speed:{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}New settings: delay={new_delay}s, workers={new_workers}{Style.RESET_ALL}")
    
    return new_delay, new_workers

def download_transcript_with_retry(video_id, language, max_retries=3, base_delay=1.5):
    """Download transcript with retries and exponential backoff."""
    global ban_detected
    retries = 0
    while retries <= max_retries:
        try:
            if retries > 0:
                backoff_delay = base_delay * (2 ** retries)
                logging.info(f"Retry {retries}/{max_retries} for {video_id} - waiting {backoff_delay:.1f} seconds...")
                time.sleep(backoff_delay)
            
            controlled_delay(base_delay)
            
            # Attempt to get the transcript using the new API and convert to raw dict format
            transcript = ytt_api.fetch(video_id, languages=[language]).to_raw_data()
            return transcript, None  # Success
            
        except NoTranscriptFound:
            return None, f"No {language} transcript available"
            
        except TranscriptsDisabled:
            return None, f"Subtitles are disabled for this video"
            
        except AgeRestricted:
            return None, f"Age restricted video (requires authentication)"
            
        except (VideoUnavailable, VideoUnplayable, InvalidVideoId) as e:
            return None, f"Video unavailable or unplayable: {str(e)}"
            
        except Exception as e:
            error_str = str(e).lower()
            exception_name = type(e).__name__.lower()
            
            if "subtitles are disabled" in error_str or "disabled" in exception_name:
                return None, f"Subtitles are disabled for this video"
                
            if "this video doesn't have" in error_str or "transcript unavailable" in error_str or "notranscriptavailable" in exception_name:
                return None, f"No transcript available for this video"
            
            # Check for rate limiting indicators
            if "429" in error_str or "too many requests" in error_str or "rate limit" in error_str or "ipblocked" in exception_name or "requestblocked" in exception_name or isinstance(e, (IpBlocked, RequestBlocked, YouTubeRequestFailed)):
                logging.warning(f"Rate limit detected for {video_id}. Backing off...")
                ban_detected = True
                
                if retries < max_retries:
                    retries += 1
                    backoff_delay = base_delay * (3 ** retries)
                    time.sleep(backoff_delay)
                else:
                    return None, f"Rate limited: {str(e)}"
            else:
                if retries < 1:
                    retries += 1
                else:
                    return None, str(e)
    
    return None, "Maximum retries exceeded"

def download_transcript(video_data, language, output_dir, use_language_folders, download_txt, download_json, delay):
    """Download transcript for a single video."""
    video_id = video_data['id']
    title = sanitize_filename(video_data['title'])
    
    # Create filename with title and video ID at the end
    base_filename = f"{title}_{video_id}"
    
    # Set up directories based on whether we're using language folders
    if use_language_folders:
        # Language-specific folders
        lang_dir = os.path.join(output_dir, language)
        json_dir = os.path.join(lang_dir, "json")
        text_dir = lang_dir
        
        # Create language directory if it doesn't exist
        os.makedirs(lang_dir, exist_ok=True)
    else:
        # Original structure
        json_dir = os.path.join(output_dir, "json")
        text_dir = output_dir
    
    # Create json directory if it doesn't exist and we're downloading JSON
    if download_json:
        os.makedirs(json_dir, exist_ok=True)
    
    # Define file paths
    json_filename = os.path.join(json_dir, f"{base_filename}_{language}.json")
    text_filename = os.path.join(text_dir, f"{base_filename}_{language}.txt")
    
    # Check if files already exist - only check files we plan to download
    files_exist = True
    if download_json and not os.path.exists(json_filename):
        files_exist = False
    if download_txt and not os.path.exists(text_filename):
        files_exist = False
    
    if files_exist:
        return {
            'success': True,
            'video_id': video_id,
            'title': title,
            'skipped': True,
            'language': language
        }
    
    # Download transcript with retry logic
    transcript, error = download_transcript_with_retry(video_id, language, base_delay=delay)
    
    if transcript:
        # Save transcript to JSON file if requested
        if download_json:
            try:
                with open(json_filename, 'w', encoding='utf-8') as f:
                    json.dump(transcript, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logging.error(f"Error saving JSON file {json_filename}: {e}")
                return {
                    'success': False,
                    'video_id': video_id,
                    'title': title,
                    'error': f"Error saving JSON file: {str(e)}",
                    'language': language
                }
        
        # Save text version if requested
        if download_txt:
            try:
                with open(text_filename, 'w', encoding='utf-8') as f:
                    full_text = " ".join([item['text'] for item in transcript])
                    f.write(full_text)
            except Exception as e:
                logging.error(f"Error saving TXT file {text_filename}: {e}")
                return {
                    'success': False,
                    'video_id': video_id,
                    'title': title,
                    'error': f"Error saving TXT file: {str(e)}",
                    'language': language
                }
        
        return {
            'success': True,
            'video_id': video_id,
            'title': title,
            'skipped': False,
            'language': language
        }
    else:
        return {
            'success': False,
            'video_id': video_id,
            'title': title,
            'error': error,
            'language': language
        }

def download_transcripts_parallel(videos_data, languages, channel_name, download_all=False, 
                                 download_txt=True, download_json=True, delay=1.5, workers=3):
    """Download transcripts for all videos in parallel with rate limiting."""
    global ban_detected, ban_recovery_time
    
    # Create channel-specific directory
    output_dir = os.path.join("transcripts", channel_name)
    os.makedirs(output_dir, exist_ok=True)
    logging.info(f"Created directory: {Fore.CYAN}{output_dir}{Style.RESET_ALL}")
    
    # Detect existing languages in the folder
    existing_languages = detect_languages_in_folder(output_dir)
    if existing_languages:
        lang_list = f"{Fore.CYAN}{', '.join(existing_languages)}{Style.RESET_ALL}"
    else:
        lang_list = f"{Fore.YELLOW}None{Style.RESET_ALL}"
    logging.info(f"Detected {Fore.CYAN}{len(existing_languages)}{Style.RESET_ALL} existing language(s) in folder: {lang_list}")
    
    # Determine if we should use language folders
    use_language_folders = should_use_language_folders(existing_languages, set(languages))
    
    # If we need to reorganize existing files when switching to language folders
    if use_language_folders:
        move_files_to_language_folders(output_dir, languages)
        logging.info(f"Using {Fore.CYAN}language-specific folders{Style.RESET_ALL} for organization")
    else:
        logging.info(f"Using {Fore.CYAN}standard folder structure{Style.RESET_ALL} (not using language folders)")
    
    successful = 0
    failed = 0
    skipped = 0
    
    # If download_all is True, we need to query available languages for the first video
    if download_all and videos_data:
        logging.info(f"{Fore.YELLOW}Checking available languages for the channel...{Style.RESET_ALL}")
        try:
            # Try to get available languages for the first video
            first_video = videos_data[0]['id']
            available_langs = get_available_languages(first_video)
            
            if available_langs:
                logging.info(f"Found {Fore.GREEN}{len(available_langs)}{Style.RESET_ALL} available languages: {Fore.CYAN}{', '.join(available_langs)}{Style.RESET_ALL}")
                languages = available_langs
                # If downloading all languages, we will definitely use language folders
                use_language_folders = True
                # If we need to reorganize after finding all languages
                move_files_to_language_folders(output_dir, languages)
            else:
                logging.warning("No languages detected. Defaulting to specified languages.")
        except Exception as e:
            logging.error(f"Error detecting available languages: {e}")
            logging.warning("Defaulting to specified languages.")
    
    file_types = []
    if download_txt:
        file_types.append("TXT")
    if download_json:
        file_types.append("JSON")
    
    # Print a nice header for the download session
    print(f"\n{Fore.CYAN}{'='*80}{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}DOWNLOAD SESSION STARTED{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*80}{Style.RESET_ALL}")
    logging.info(f"Downloading {Fore.CYAN}{', '.join(file_types)}{Style.RESET_ALL} files in {Fore.CYAN}{len(languages)}{Style.RESET_ALL} language(s): {Fore.CYAN}{', '.join(languages)}{Style.RESET_ALL}")
    logging.info(f"Rate limiting: {Fore.YELLOW}{delay}s{Style.RESET_ALL} delay between requests with {Fore.YELLOW}{workers}{Style.RESET_ALL} concurrent workers")
    logging.info(f"Saving to directory: {Fore.CYAN}{output_dir}{Style.RESET_ALL}")
    logging.info(f"Processing {Fore.GREEN}{len(videos_data)}{Style.RESET_ALL} videos...")
    print(f"{Fore.CYAN}{'-'*80}{Style.RESET_ALL}")
    
    # Track remaining tasks for reprocessing
    remaining_tasks = []
    for video in videos_data:
        for lang in languages:
            remaining_tasks.append((video, lang))
    
    # Process while we have remaining tasks and adjusting rate as needed
    current_delay = delay
    current_workers = workers
    
    # Create a progress tracker for the total tasks
    total_tasks = len(remaining_tasks)
    progress_bar = tqdm(total=total_tasks, desc=f"{Fore.LIGHTBLACK_EX}Overall progress{Style.RESET_ALL}", 
                         bar_format='{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]',
                         colour='cyan')
    progress_bar.update(0)
    
    while remaining_tasks:
        # Check if we need to adjust rate limiting due to bans
        if ban_detected:
            current_delay, current_workers = adjust_rate_for_ban_recovery(current_delay, current_workers)
            logging.info(f"Adjusted rate limiting: {Fore.YELLOW}{current_delay}s{Style.RESET_ALL} delay with {Fore.YELLOW}{current_workers}{Style.RESET_ALL} workers")
        
        # Take a subset of tasks based on current worker count
        batch_size = min(len(remaining_tasks), 100)  # Process in batches of 100 or fewer
        current_batch = remaining_tasks[:batch_size]
        
        # Process videos with limited concurrency
        with concurrent.futures.ThreadPoolExecutor(max_workers=current_workers) as executor:
            # Submit tasks for current batch
            future_to_task = {}
            for video, lang in current_batch:
                future = executor.submit(
                    download_transcript, 
                    video, 
                    lang, 
                    output_dir, 
                    use_language_folders, 
                    download_txt, 
                    download_json,
                    current_delay
                )
                future_to_task[future] = (video, lang)
            
            logging.info(f"Processing batch of {Fore.CYAN}{len(future_to_task)}{Style.RESET_ALL} tasks with {Fore.CYAN}{current_workers}{Style.RESET_ALL} workers...")
            
            # Process results as they complete
            completed_tasks = []
            for i, future in enumerate(concurrent.futures.as_completed(future_to_task)):
                video, lang = future_to_task[future]
                completed_tasks.append((video, lang))
                
                try:
                    result = future.result()
                    
                    if result['success']:
                        if result.get('skipped', False):
                            # Successfully skipped
                            title_display = result['title'][:40] + "..." if len(result['title']) > 40 else result['title']
                            print(f"[{Fore.CYAN}SKIP{Style.RESET_ALL}] {title_display} ({lang})")
                            skipped += 1
                        else:
                            # Successfully downloaded
                            title_display = result['title'][:40] + "..." if len(result['title']) > 40 else result['title']
                            print(f"[{Fore.GREEN}OK{Style.RESET_ALL}  ] {title_display} ({lang})")
                            successful += 1
                    else:
                        # Failed
                        title_display = result['title'][:40] + "..." if len(result['title']) > 40 else result['title']
                        error_msg = result.get('error', 'Unknown error')
                        if "no transcript available" in error_msg.lower():
                            print(f"[{Fore.YELLOW}MISS{Style.RESET_ALL}] {title_display} ({lang}) - {error_msg}")
                        else:
                            print(f"[{Fore.RED}FAIL{Style.RESET_ALL}] {title_display} ({lang}) - {error_msg}")
                        failed += 1
                        
                    # Update the progress bar
                    progress_bar.update(1)
                    progress_bar.set_postfix({'✓': successful, '↺': skipped, '✗': failed})
                        
                except Exception as e:
                    title_display = video['title'][:40] + "..." if len(video['title']) > 40 else video['title']
                    print(f"[{Fore.RED}ERR{Style.RESET_ALL} ] {title_display} ({lang}) - {str(e)}")
                    failed += 1
                    progress_bar.update(1)
                    progress_bar.set_postfix({'✓': successful, '↺': skipped, '✗': failed})
        
        # Remove completed tasks from remaining
        for task in completed_tasks:
            if task in remaining_tasks:
                remaining_tasks.remove(task)
        
        # If we still have tasks but had a ban, we might need to pause
        if remaining_tasks and ban_detected and ban_recovery_time is None:
            wait_time = random.uniform(300, 420)  # 5-7 minutes in seconds
            mins = int(wait_time // 60)
            secs = int(wait_time % 60)
            
            print(f"\n{Fore.RED}⚠️  Rate limit detected. Pausing for {mins}m {secs}s before continuing...{Style.RESET_ALL}")
            
            # Create a countdown timer
            for remaining in tqdm(range(int(wait_time), 0, -1), 
                                 desc=f"{Fore.YELLOW}Waiting for rate limit to reset{Style.RESET_ALL}", 
                                 bar_format='{desc}: {bar} {n_fmt}s',
                                 colour='yellow'):
                time.sleep(1)
                
            ban_recovery_time = time.time()  # Mark recovery start time
    
    # Close the progress bar
    progress_bar.close()
    
    # Print summary with color
    print(f"\n{Fore.CYAN}{'='*80}{Style.RESET_ALL}")
    print(f"{Fore.LIGHTBLACK_EX}DOWNLOAD SUMMARY FOR: {channel_name}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*80}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}✓ Downloaded: {successful}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}↺ Skipped (already exist): {skipped}{Style.RESET_ALL}")
    print(f"{Fore.RED}✗ Failed: {failed}{Style.RESET_ALL}")
    
    if use_language_folders:
        folder_structure = f"Transcripts organized in language folders under: {Fore.CYAN}{output_dir}{Style.RESET_ALL}"
    else:
        folder_structure = f"Transcripts saved in: {Fore.CYAN}{output_dir}{Style.RESET_ALL}"
    print(folder_structure)
    print(f"{Fore.CYAN}{'-'*80}{Style.RESET_ALL}")
    
    return successful, skipped, failed

def process_channel(channel_url, languages, download_all, download_txt, download_json, delay, workers):
    """Process a single channel."""
    # Normalize URL for better yt-dlp compatibility
    normalized_url = normalize_channel_url(channel_url)
    if normalized_url != channel_url:
        logging.info(f"Normalized URL: {Fore.CYAN}{normalized_url}{Style.RESET_ALL}")
        channel_url = normalized_url
        
    # Get channel name for directory creation
    channel_name = get_channel_name(channel_url)
    
    # Get video metadata
    videos_data = get_videos_from_channel(channel_url)
    
    if not videos_data:
        logging.warning(f"No videos found for {channel_url}. Skipping channel.")
        return 0, 0, 0
    
    # Download transcripts
    return download_transcripts_parallel(
        videos_data, 
        languages, 
        channel_name, 
        download_all, 
        download_txt, 
        download_json,
        delay,
        workers
    )

def main():
    # Clear screen for better presentation
    os.system('cls' if os.name == 'nt' else 'clear')
    
    # Display logo
    display_logo()
    
    # Parse arguments
    try:
        urls, languages, download_all, download_txt, download_json, delay, workers = parse_arguments()
    except Exception as e:
        logging.error(f"Error parsing arguments: {e}")
        display_help()
        sys.exit(1)
    
    print(f"{Fore.CYAN}{'='*80}{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}SESSION CONFIGURATION{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*80}{Style.RESET_ALL}")
    
    if download_all:
        logging.info(f"Processing {Fore.CYAN}{len(urls)}{Style.RESET_ALL} channels with {Fore.GREEN}ALL available languages{Style.RESET_ALL}")
    else:
        logging.info(f"Processing {Fore.CYAN}{len(urls)}{Style.RESET_ALL} channels with languages: {Fore.CYAN}{', '.join(languages)}{Style.RESET_ALL}")
    
    file_types = []
    if download_txt:
        file_types.append("TXT")
    if download_json:
        file_types.append("JSON")
    logging.info(f"File types to download: {Fore.CYAN}{', '.join(file_types)}{Style.RESET_ALL}")
    logging.info(f"Rate limiting: {Fore.YELLOW}{delay}s{Style.RESET_ALL} delay between requests, {Fore.YELLOW}{workers}{Style.RESET_ALL} concurrent workers")
    
    # Safety warning for aggressive scraping
    if delay < 5.0 or workers > 1:
        print(f"{Fore.RED}{'='*80}{Style.RESET_ALL}")
        logging.warning(f"{Fore.YELLOW}⚠️  WARNING: Aggressive rate limiting detected (-delay {delay}s, -workers {workers}).{Style.RESET_ALL}")
        logging.warning(f"{Fore.YELLOW}This may trigger an IP ban. Safe defaults are: -delay {DEFAULT_DELAY} -workers {DEFAULT_WORKERS}{Style.RESET_ALL}")
        print(f"{Fore.RED}{'='*80}{Style.RESET_ALL}")
        time.sleep(2) # Brief pause so the user sees it
    
    print(f"{Fore.CYAN}{'-'*80}{Style.RESET_ALL}")
    
    total_downloaded = 0
    total_skipped = 0
    total_failed = 0
    
    # Process each channel
    for i, url in enumerate(urls):
        print(f"\n{Fore.CYAN}{'='*80}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}CHANNEL {i+1}/{len(urls)}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{'='*80}{Style.RESET_ALL}")
        logging.info(f"Processing: {Fore.CYAN}{url}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{'-'*80}{Style.RESET_ALL}")
        
        try:
            downloaded, skipped, failed = process_channel(
                url, 
                languages, 
                download_all, 
                download_txt, 
                download_json,
                delay,
                workers
            )
            total_downloaded += downloaded
            total_skipped += skipped
            total_failed += failed
        except Exception as e:
            logging.error(f"Error processing channel {url}: {e}")
    
    # Print overall summary for multiple channels
    if len(urls) > 1:
        print(f"\n{Fore.CYAN}{'='*80}{Style.RESET_ALL}")
        print(f"{Fore.GREEN}OVERALL SUMMARY{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{'='*80}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}Total channels processed: {len(urls)}{Style.RESET_ALL}")
        print(f"{Fore.GREEN}✓ Total files downloaded: {total_downloaded}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}↺ Total files skipped (already exist): {total_skipped}{Style.RESET_ALL}")
        print(f"{Fore.RED}✗ Total files failed: {total_failed}{Style.RESET_ALL}")
        
        # Add a graphical representation of the results
        total = total_downloaded + total_skipped + total_failed
        if total > 0:
            dl_percent = int((total_downloaded / total) * 100)
            skip_percent = int((total_skipped / total) * 100)
            fail_percent = int((total_failed / total) * 100)
            
            # Ensure percentages add up to 100%
            remainder = 100 - (dl_percent + skip_percent + fail_percent)
            dl_percent += remainder  # Add any rounding remainder to downloads
            
            print("\nResults distribution:")
            bar_width = 50
            dl_width = int(bar_width * dl_percent / 100)
            skip_width = int(bar_width * skip_percent / 100)
            fail_width = bar_width - dl_width - skip_width
            
            print(f"[{Fore.GREEN}{dl_width * '■'}{Fore.CYAN}{skip_width * '■'}{Fore.RED}{fail_width * '■'}{Style.RESET_ALL}]")
            print(f"{Fore.GREEN}■ Downloaded ({dl_percent}%){Style.RESET_ALL} {Fore.CYAN}■ Skipped ({skip_percent}%){Style.RESET_ALL} {Fore.RED}■ Failed ({fail_percent}%){Style.RESET_ALL}")
        
        print(f"{Fore.CYAN}{'='*80}{Style.RESET_ALL}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        signal_handler(signal.SIGINT, None)
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        sys.exit(1)
