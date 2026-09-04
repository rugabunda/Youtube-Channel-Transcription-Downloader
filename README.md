
# YouTube Channel Transcript Downloader (v1.1.0)

A robust, safety-first Python script that downloads transcripts (subtitles/captions) for all videos in one or more YouTube channels, or individual videos. 

Designed with strict anti-ban mechanisms, it protects your IP from YouTube's aggressive scraping defenses while organizing your data into clean, language-specific folders. Existing files are automatically skipped, allowing you to safely resume or update large channels over time.

## ✨ Key Features

- **Safe-by-Default Rate Limiting:** Defaults to a 7-second delay and 1 concurrent worker to prevent IP bans.
- **Multi-Language Support:** Download specific languages (e.g., `-en -es -fr`) or grab ALL available languages (`-all`).
- **Top-Level Configuration:** Easily adjust global safety thresholds at the top of the script.
- **Comprehensive Downloads:** Target single videos, playlists, or entire channels.
- **Dual Formats:** Export to human-readable `.txt` and structured `.json` formats.
- **Resumable:** Automatically skips videos that have already been downloaded.
- **Smart Organization:** Creates dedicated folders for channels and automatically sorts transcripts by language.
- **Reliable Extraction:** Automatically normalizes channel URLs (appending `/videos`) for bulletproof `yt-dlp` compatibility.
- **Intelligent Error Handling:** Skips age-restricted, unplayable, or disabled-subtitle videos without wasting retries.
- **Automated Recovery:** Implements exponential backoff and automatic pausing if a rate limit (429) is detected.

---

## 📦 Requirements & Installation

This script requires **Python 3.7+** and relies on the modern (v1.0.0+) `youtube-transcript-api`.

Install the required dependencies via pip:

```bash
pip install youtube-transcript-api yt-dlp colorama tqdm
```

*Note: Ensure your `yt-dlp` is up to date (`pip install --upgrade yt-dlp`) as YouTube frequently changes its frontend, which can break older versions of `yt-dlp`.*

---

## ⚙️ Configuration (Safety First!)

To protect your IP, open `Youtube.Transcribe.py` and locate the **Safety & Rate Limiting Configuration** block at the very top of the file. Adjust these values based on your risk tolerance:

```python
# DEFAULT_DELAY: Time in seconds to wait between EACH download attempt.
DEFAULT_DELAY = 7.0

# DEFAULT_WORKERS: Number of concurrent download threads. 
# Keep at 1 to avoid triggering YouTube's anti-bot defenses.
DEFAULT_WORKERS = 1

# MIN_DELAY: The absolute minimum delay allowed via command-line arguments.
MIN_DELAY = 3.0

# MAX_WORKERS: The absolute maximum number of workers allowed via command-line.
MAX_WORKERS = 2
```

> **⚠️ Warning:** If you have previously been IP-banned by YouTube, it is highly recommended to leave these at their safe defaults. Running with high concurrency (`-workers > 1`) or low delays (`-delay < 5`) will flash a red warning in the console and significantly increase your risk of a multi-month ban.

---

## 🚀 Usage

```bash
python Youtube.Transcribe.py [options] <channel_or_video_url(s)>
```

### Examples

**Download English transcript for a single YouTube video**
```bash
python Youtube.Transcribe.py https://www.youtube.com/watch?v=dQw4w9WgXcQ -en
```

**Short URL also works**
```bash
python Youtube.Transcribe.py https://youtu.be/dQw4w9WgXcQ -en
```

**Multiple URLs**
```bash
python Youtube.Transcribe.py https://youtu.be/aDkzgTWhVY4 https://youtu.be/3ZC1iqYfFGU -en
```

**Download English transcripts from an entire channel**
```bash
python Youtube.Transcribe.py https://www.youtube.com/@ChannelName -en
```

**Download multiple languages simultaneously**
```bash
python Youtube.Transcribe.py https://youtube.com/c/channel1 -en -es -fr
```

**Download ALL available languages for a channel**
```bash
python Youtube.Transcribe.py https://youtube.com/c/channel1 -all
```

**Download only TXT files (no JSON)**
```bash
python Youtube.Transcribe.py https://youtube.com/c/channel1 -en -txt
```

**Download only JSON files (no TXT)**
```bash
python Youtube.Transcribe.py https://youtube.com/c/channel1 -en -json
```

**Aggressive downloads (⚠️ High risk of IP ban)**
```bash
python Youtube.Transcribe.py https://youtube.com/c/channel1 -en -delay 3 -workers 2
```

**Download from channels listed in a text file**
```bash
python Youtube.Transcribe.py -f channels.txt -en
```

---

## 🛠️ Command-Line Options

| Option | Description |
| :--- | :--- |
| `-f, --file FILE` | Read channel URLs from a text file (one per line or comma-separated). |
| `-LANG` | Language code for transcripts (e.g., `-en` for English). Multiple codes can be specified (`-en -es -fr`). |
| `-all` | Download **all** available languages for each video. |
| `-txt` | Download **only** TXT files (skips JSON). |
| `-json` | Download **only** JSON files (skips TXT). |
| `-delay N` | Delay between API requests in seconds (Default: `7.0`). |
| `-workers N` | Number of concurrent downloads (Default: `1`, Max: `2`). |
| `-h, --help` | Show the help message and exit. |

## Available Language Codes

- `-en`      - English                    - `-es`      - Spanish                    - `-fr`      - French
- `-de`      - German                     - `-it`      - Italian                    - `-pt`      - Portuguese
- `-ru`      - Russian                    - `-ja`      - Japanese                   - `-ko`      - Korean
- `-zh-Hans` - Chinese (Simplified)       - `-zh-Hant` - Chinese (Traditional)      - `-ar`      - Arabic
- `-hi`      - Hindi                      - `-bn`      - Bengali                    - `-nl`      - Dutch
- `-sv`      - Swedish                    - `-tr`      - Turkish                    - `-pl`      - Polish
- `-vi`      - Vietnamese                 - `-th`      - Thai                       - `-fa`      - Persian
- `-id`      - Indonesian                 - `-uk`      - Ukrainian                  - `-cs`      - Czech
- `-fi`      - Finnish                    - `-ro`      - Romanian                   - `-el`      - Greek
- `-he`      - Hebrew                     - `-da`      - Danish                     - `-no`      - Norwegian
- `-hu`      - Hungarian                  - `-bg`      - Bulgarian                  - `-hr`      - Croatian
- `-sk`      - Slovak                     - `-lt`      - Lithuanian                 - `-sl`      - Slovenian
- `-et`      - Estonian                   - `-lv`      - Latvian

---

## 🛡️ Rate Limiting & Anti-Ban Features

YouTube aggressively bans IPs that scrape transcripts too quickly. This script implements several layers of protection:

1. **Human-like Jitter:** Adds ±20% random variance to your delay (e.g., a 7s delay becomes 5.6s to 8.4s) to avoid robotic timing patterns.
2. **Hard Limits:** Prevents you from accidentally running dangerous CLI arguments by enforcing `MIN_DELAY` and `MAX_WORKERS`.
3. **Exponential Backoff:** If a request fails, the wait time doubles before the next retry.
4. **Automated Recovery Pause:** If the script detects a `429 Too Many Requests` or `IpBlocked` error, it immediately drops to 1 worker, increases the delay to 10 seconds, and pauses execution for 5–7 minutes to let the IP cooldown before resuming.
5. **Smart Skipping:** Instantly skips videos with disabled subtitles, age-restrictions, or unavailable transcripts without triggering retry penalties.

---

## 🔧 Troubleshooting

**"No video data returned" or `yt-dlp` errors:**
YouTube frequently updates its frontend. If `yt-dlp` fails to fetch the channel list, update it:
```bash
pip install --upgrade yt-dlp
```

**"type object 'YouTubeTranscriptApi' has no attribute 'get_transcript'":**
You are using an outdated version of the transcript API. Update it to v1.0.0+:
```bash
pip install --upgrade youtube-transcript-api
```

**"IpBlocked" or "RequestBlocked" errors:**
Your IP has been temporarily flagged by YouTube. 
1. Stop the script immediately.
2. Wait 24-48 hours (or switch to a different network/VPN).
3. Ensure your `DEFAULT_DELAY` is set to `7.0` or higher and `DEFAULT_WORKERS` is `1` before trying again.
```
