#!/usr/bin/env python3
"""
Fetch tweets from multiple Twitter accounts and generate RSS feed.
Uses twscrape with guest token (no login required) or account cookies.
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any
import html

try:
    from twscrape import API, gather
except ImportError:
    print("Installing twscrape...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "twscrape"])
    from twscrape import API, gather

# Configuration
ACCOUNTS = [
    "BitcoinNewsCom",
    "gladstein",
    "mononautical",
    "utexocom",
    "JoeNakamoto",
    "jack",
    "SimplyBitcoin",
    "sminston_with",
    "BitcoinMagazine",
]

TWEETS_PER_ACCOUNT = 20
MAX_TOTAL_TWEETS = 100
STATE_FILE = Path("seen_tweets.json")
OUTPUT_FILE = Path("feed.xml")
FEED_TITLE = "Bitcoin News Feed (via twscrape)"
FEED_DESCRIPTION = "Aggregated tweets from curated Bitcoin Twitter accounts"
FEED_LINK = "https://github.com/YOUR_USERNAME/YOUR_REPO"


def load_state() -> set:
    """Load previously seen tweet IDs."""
    if STATE_FILE.exists():
        try:
            return set(json.loads(STATE_FILE.read_text()))
        except Exception:
            return set()
    return set()


def save_state(seen_ids: set):
    """Save seen tweet IDs."""
    STATE_FILE.write_text(json.dumps(sorted(list(seen_ids))))


def tweet_to_rss_item(tweet: Dict[str, Any]) -> str:
    """Convert a tweet dict to RSS item XML."""
    tweet_id = tweet.get("id", "")
    username = tweet.get("user", {}).get("username", "")
    display_name = tweet.get("user", {}).get("displayname", "")
    content = tweet.get("rawContent", "") or tweet.get("content", "")
    url = tweet.get("url", f"https://x.com/{username}/status/{tweet_id}")
    created_at = tweet.get("date", "")
    
    # Parse date for RFC 822 format
    try:
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        pub_date = dt.strftime("%a, %d %b %Y %H:%M:%S %z")
    except Exception:
        pub_date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
    
    # Escape HTML
    content_escaped = html.escape(content)
    title = f"@{username}: {content[:100]}..." if len(content) > 100 else f"@{username}: {content}"
    title = html.escape(title)
    
    # Handle media
    media_html = ""
    photos = tweet.get("media", {}).get("photos", [])
    videos = tweet.get("media", {}).get("videos", [])
    for photo in photos:
        media_html += f'<br/><img src="{html.escape(photo.get("url", ""))}" alt="Tweet image" style="max-width:100%;"/>'
    for video in videos:
        variants = video.get("variants", [])
        for v in variants:
            if v.get("contentType") == "video/mp4":
                media_html += f'<br/><video controls src="{html.escape(v.get("url", ""))}" style="max-width:100%;"></video>'
                break
    
    description = f"{content_escaped}{media_html}"
    
    return f"""    <item>
      <title>{title}</title>
      <link>{html.escape(url)}</link>
      <guid isPermaLink="false">{tweet_id}</guid>
      <pubDate>{pub_date}</pubDate>
      <author>{html.escape(username)}</author>
      <description><![CDATA[{description}]]></description>
    </item>"""


def generate_rss(tweets: List[Dict[str, Any]]) -> str:
    """Generate RSS 2.0 XML from tweets."""
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
    
    items = "\n".join(tweet_to_rss_item(t) for t in tweets)
    
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{html.escape(FEED_TITLE)}</title>
    <link>{html.escape(FEED_LINK)}</link>
    <description>{html.escape(FEED_DESCRIPTION)}</description>
    <language>en</language>
    <lastBuildDate>{now}</lastBuildDate>
    <atom:link href="{html.escape(FEED_LINK)}/feed.xml" rel="self" type="application/rss+xml"/>
{items}
  </channel>
</rss>"""


async def fetch_tweets(api: API, accounts: List[str], limit: int) -> List[Dict[str, Any]]:
    """Fetch tweets from multiple accounts."""
    all_tweets = []
    
    for username in accounts:
        try:
            print(f"Fetching tweets from @{username}...")
            user = await api.user_by_login(username)
            if not user:
                print(f"  User @{username} not found")
                continue
            
            tweets = await gather(api.user_tweets(user.id, limit=limit))
            for tweet in tweets:
                # Convert to dict
                tweet_dict = {
                    "id": str(tweet.id),
                    "url": f"https://x.com/{username}/status/{tweet.id}",
                    "date": tweet.date.isoformat() if tweet.date else "",
                    "rawContent": tweet.rawContent,
                    "content": tweet.content,
                    "user": {
                        "username": tweet.user.username,
                        "displayname": tweet.user.displayname,
                    },
                    "media": {"photos": [], "videos": []},
                }
                # Add media if present
                if tweet.media:
                    tweet_dict["media"]["photos"] = [
                        {"url": p.url, "width": p.width, "height": p.height}
                        for p in tweet.media.photos
                    ]
                    tweet_dict["media"]["videos"] = [
                        {
                            "url": v.url,
                            "duration": v.duration,
                            "variants": [
                                {"url": var.url, "contentType": var.contentType, "bitrate": var.bitrate}
                                for var in v.variants
                            ],
                        }
                        for v in tweet.media.videos
                    ]
                all_tweets.append(tweet_dict)
            print(f"  Got {len(tweets)} tweets from @{username}")
        except Exception as e:
            print(f"  Error fetching @{username}: {e}")
    
    return all_tweets


async def setup_api() -> API:
    """Set up twscrape API with guest token or account cookies."""
    api = API()
    
    # Option 1: Use account cookies from environment (more reliable)
    auth_token = os.environ.get("TWITTER_AUTH_TOKEN")
    ct0 = os.environ.get("TWITTER_CT0")
    
    if auth_token and ct0:
        print("Using Twitter account cookies from environment...")
        try:
            await api.pool.add_account(
                "twitter_account", 
                "",  # password not needed with cookies
                "",  # email not needed
                "",  # email_password not needed
                cookies={"auth_token": auth_token, "ct0": ct0}
            )
            await api.pool.login_all()
            print("Account authenticated successfully")
            return api
        except Exception as e:
            print(f"Failed to use account cookies: {e}")
            print("Falling back to guest token...")
    
    # Option 2: Use guest token (may be blocked on some IPs)
    print("Attempting guest token...")
    try:
        await api.pool.add_account("guest", "", "", "")
        await api.pool.login_all()
        print("Guest token ready")
    except Exception as e:
        print(f"Warning: Could not initialize guest token: {e}")
        print("Note: Guest token may be blocked by Cloudflare on some IPs.")
        print("GitHub Actions IPs may work better.")
    
    return api


async def main():
    print("Initializing twscrape API...")
    api = await setup_api()
    
    # Load state
    seen_ids = load_state()
    print(f"Loaded {len(seen_ids)} previously seen tweet IDs")
    
    # Fetch tweets
    tweets = await fetch_tweets(api, ACCOUNTS, TWEETS_PER_ACCOUNT)
    
    # Filter new tweets
    new_tweets = [t for t in tweets if t["id"] not in seen_ids]
    print(f"Found {len(new_tweets)} new tweets")
    
    # Update state
    for t in new_tweets:
        seen_ids.add(t["id"])
    
    # Keep only recent tweets in feed (last 100)
    all_feed_tweets = sorted(tweets, key=lambda x: x["date"], reverse=True)[:MAX_TOTAL_TWEETS]
    
    # Generate RSS
    rss_xml = generate_rss(all_feed_tweets)
    OUTPUT_FILE.write_text(rss_xml)
    print(f"RSS feed written to {OUTPUT_FILE} ({len(all_feed_tweets)} items)")
    
    # Save state
    save_state(seen_ids)
    print("State saved")
    
    return len(new_tweets)


if __name__ == "__main__":
    try:
        new_count = asyncio.run(main())
        if new_count == 0:
            print("No new tweets found (this is normal on first run or if rate limited)")
        sys.exit(0)
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)