from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel
import os
from dotenv import load_dotenv
import logging
import random
import time
from urllib.parse import quote
import re
from typing import Optional
import aiohttp
import asyncio

class ArticleContent(BaseModel):
    title: str
    content: str
    url: str
    date: str
    author: str
    source: str

class TweetContent(BaseModel):
    text: str
    author: str
    source: str

class ScrapedContent(BaseModel):
    articles: list[ArticleContent]
    tweets: list[TweetContent]

# Define your search terms
SEARCH_TERMS = ["murang'a", "kangata", "politics", "news"]  
# Adjust with actual terms

# Set up logging with more detail
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Updated Nitter instances
# Update NITTER_INSTANCES list with working servers
# Updated working Nitter instances (verified 2024-04-23)
NITTER_INSTANCES = [
    "https://nitter.kavin.rocks",
    "https://nitter.moomoo.me",
    "https://nitter.weiler.rocks"
]

async def test_nitter_instance(session: aiohttp.ClientSession, instance: str) -> Optional[str]:
    """Test instances with SSL verification flexibility"""
    for _ in range(2):
        try:
            # Bypass SSL verification for problematic instances
            connector = aiohttp.TCPConnector(ssl=False) if "projectsegfau" in instance else None
            async with session.get(
                f"{instance}/HonKangata",
                timeout=10,
                connector=connector
            ) as response:
                if response.status == 200:
                    return instance
                await asyncio.sleep(1)
        except Exception as e:
            logger.warning(f"Nitter instance {instance} failed: {str(e)}")
            await asyncio.sleep(2)
    return None

async def get_working_nitter_instance() -> Optional[str]:
    """Find a working Nitter instance"""
    async with aiohttp.ClientSession() as session:
        tasks = [test_nitter_instance(session, instance) for instance in NITTER_INSTANCES]
        results = await asyncio.gather(*tasks)
        working_instances = [instance for instance in results if instance]
        return working_instances[0] if working_instances else None

def get_random_headers():
    """Generate random headers with more variety"""
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36"
    ]
    return {
        "User-Agent": random.choice(user_agents),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "max-age=0"
    }

async def scrape_twitter_profile(username: str = "HonKangata") -> list:
    """Scrape tweets with multiple parsing strategies"""
    tweets = []
    try:
        instance = await get_working_nitter_instance()
        if not instance:
            logger.error("No working Nitter instances found")
            return tweets

        url = f"{instance}/{username.lstrip('@')}"
        headers = get_random_headers()
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=20) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'lxml')  # Use lxml parser for better performance
                    
                    # Multiple parsing strategies
                    selectors = [
                        ('div.tweet-body', 'div.tweet-content'),  # Standard Nitter
                        ('div.tweet', 'div.tweet-text'),          # Alternative layout
                        ('article.tweet', 'div.content')          # Mobile layout
                    ]
                    
                    for container_sel, text_sel in selectors:
                        containers = soup.select(container_sel)
                        if containers:
                            for container in containers[:5]:
                                text_element = container.select_one(text_sel)
                                if text_element:
                                    tweet_text = text_element.get_text(strip=True)
                                    if tweet_text and 20 < len(tweet_text) < 500:
                                        tweets.append({
                                            'text': tweet_text,
                                            'author': username,
                                            'source': 'X/Twitter'
                                        })
                            break  # Stop if we found matching elements
                    
                    if not tweets:
                        logger.warning(f"No tweets found at {url}")
                        logger.debug(f"HTML snippet:\n{soup.prettify()[:1000]}")
                        
    except Exception as e:
        logger.error(f"Error scraping Twitter: {str(e)}")
    
    return tweets
# Update SEARCH_TERMS to be more inclusive
SEARCH_TERMS = [
    "murang'a", "kangata", "politics", "news",
    "county", "government", "assembly", "leader"
]

async def scrape_nation_articles() -> list:
    """Scrape articles with enhanced content validation"""
    articles = []
    
    try:
        urls_to_try = [
            "https://nation.africa/kenya/counties/murang-a",
            "https://nation.africa/kenya/news",
            "https://nation.africa/kenya/politics"
        ]
        
        async with aiohttp.ClientSession() as session:
            for base_url in urls_to_try:
                try:
                    async with session.get(base_url, headers=get_random_headers(), timeout=20) as response:
                        if response.status == 200:
                            html = await response.text()
                            soup = BeautifulSoup(html, 'lxml')
                            
                            # Find articles using semantic markup
                            articles_found = soup.select('article, [itemtype="http://schema.org/Article"]')
                            
                            for article in articles_found[:8]:  # Limit initial processing
                                try:
                                    link = article.select_one('a[href]')
                                    if not link:
                                        continue
                                    
                                    href = link['href']
                                    if not href.startswith('http'):
                                        href = f"https://nation.africa{href}"
                                    
                                    # Skip non-article URLs
                                    if not re.search(r'/\d{4}/\d{2}/\d{2}/', href):
                                        continue
                                    
                                    # Check if already processed
                                    if any(a['url'] == href for a in articles):
                                        continue
                                    
                                    async with session.get(href, headers=get_random_headers(), timeout=15) as article_response:
                                        if article_response.status == 200:
                                            article_html = await article_response.text()
                                            article_soup = BeautifulSoup(article_html, 'lxml')
                                            
                                            # Extract metadata
                                            title = article_soup.find('meta', property='og:title') or \
                                                    article_soup.find('h1')
                                            title = title['content'] if hasattr(title, 'get') else getattr(title, 'text', '').strip()
                                            
                                            content = article_soup.find('div', itemprop='articleBody') or \
                                                    article_soup.find('div', class_=re.compile(r'(article|story)-body'))
                                            
                                            if content:
                                                paragraphs = [p.text.strip() for p in content.find_all('p') if p.text.strip()]
                                                full_text = ' '.join(paragraphs)
                                                
                                                # Content validation
                                                if len(full_text) < 100 or \
                                                    any(term.lower() in full_text.lower() for term in SEARCH_TERMS):
                                                    articles.append({
                                                        'title': title[:200] + '...' if len(title) > 200 else title,
                                                        'content': full_text[:500] + '...' if len(full_text) > 500 else full_text,
                                                        'url': href,
                                                        'date': 'Recent',
                                                        'author': 'Nation Africa',
                                                        'source': 'Daily Nation'
                                                    })
                                                    if len(articles) >= 5:
                                                        break
                                    
                                except Exception as e:
                                    logger.error(f"Article processing error: {str(e)}")
                                    continue
                                    
                except Exception as e:
                    logger.error(f"URL error {base_url}: {str(e)}")
                    continue
                    
    except Exception as e:
        logger.error(f"Scraping error: {str(e)}")
    
    return articles


@app.get("/api/content")
async def get_content():
    try:
        # Run scraping tasks concurrently
        nation_articles, tweets = await asyncio.gather(
            scrape_nation_articles(),
            scrape_twitter_profile("HonKangata")
        )
        
        # Convert to Pydantic models
        formatted_articles = [ArticleContent(**article) for article in nation_articles]
        formatted_tweets = [TweetContent(**tweet) for tweet in tweets]
        
        logger.info(f"Successfully scraped {len(formatted_articles)} articles and {len(formatted_tweets)} tweets")
        
        return ScrapedContent(
            articles=formatted_articles,
            tweets=formatted_tweets
        )
    
    except Exception as e:
        logger.error(f"Main error in get_content: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)