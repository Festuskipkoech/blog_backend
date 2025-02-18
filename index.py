from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from google import genai
import requests
import feedparser
from datetime import datetime
import time
from typing import List
from pydantic import BaseModel
from urllib.parse import urlparse, parse_qs, quote
import trafilatura
import json  # Added for JSON parsing

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GEMINI_API_KEY = "AIzaSy..."
genai.Client(api_key=GEMINI_API_KEY)
model = "gemini-2.0-flash"

class Article(BaseModel):
    title: str
    content: str
    url: str
    author: str
    date: str

class ContentResponse(BaseModel):
    articles: List[Article]

def get_final_redirect_url(google_news_url: str, headers: dict) -> str:
    try:
        r = requests.get(google_news_url, headers=headers, allow_redirects=True, timeout=10)
        r.raise_for_status()
        return r.url
    except Exception as e:
        print(f"Redirect error: {str(e)}")
        return google_news_url

async def get_article_content(url: str, headers: dict) -> dict:
    max_retries = 3
    base_delay = 2

    for i in range(max_retries):
        try:
            if "news.google.com/rss/articles" in url:
                parsed_url = urlparse(url)
                query_params = parse_qs(parsed_url.query)
                
                if 'url' in query_params:
                    real_article_url = query_params['url'][0]
                else:
                    real_article_url = get_final_redirect_url(url, headers)
            else:
                real_article_url = url

            downloaded = trafilatura.fetch_url(real_article_url)
            
            if downloaded:
                extracted_doc = trafilatura.extract(
                    downloaded,
                    output_format='json',
                    with_metadata=True,
                    date_extraction_params={'extensive_search': True, 'original_date': True}
                )
                
                if extracted_doc:
                    # Safely parse JSON instead of using eval()
                    doc = json.loads(extracted_doc)
                    
                    content = doc.get('text', '')
                    if not content or len(content.strip()) < 100:
                        raise ValueError("Insufficient content extracted")

                    return {
                        'content': content,
                        'title': doc.get('title', ''),
                        'authors': doc.get('author', '').split(', ') if doc.get('author') else [],
                        'publish_date': doc.get('date', ''),
                        'url': real_article_url
                    }

            raise ValueError("No content could be extracted")

        except Exception as e:
            print(f"Attempt {i+1} failed for URL {url}: {str(e)}")
            if i < max_retries - 1:
                time.sleep(base_delay ** i)
            continue

    return {
        'content': "Content not available",
        'title': "",
        'authors': [],
        'publish_date': None,
        'url': url
    }

async def fetch_google_news(query: str = "Irungu Kang'ata site:the-star.co.ke", limit: int = 10) -> List[Article]:
    articles = []
    try:
        encoded_query = quote(query)
        rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-KE&gl=KE&ceid=KE:en"
        feed = feedparser.parse(rss_url)
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }

        for entry in feed.entries[:limit]:
            try:
                article_data = await get_article_content(entry.link, headers)
                
                # Handle date parsing with proper error handling
                publish_date = article_data.get('publish_date')
                entry_date = entry.get('published')
                date = None

                if publish_date:
                    try:
                        date = datetime.fromisoformat(publish_date)
                    except:
                        pass
                
                if not date and entry_date:
                    try:
                        date = datetime.strptime(entry_date, '%a, %d %b %Y %H:%M:%S %Z')
                    except:
                        pass
                
                if not date:
                    date = datetime.now()

                articles.append(Article(
                    title=article_data['title'] or entry.title,
                    content=article_data['content'],
                    url=article_data['url'],
                    author=', '.join(article_data['authors']) if article_data['authors'] else "The Star",
                    date=date.isoformat()
                ))
                
                time.sleep(1)
                
            except Exception as e:
                print(f"Error processing entry: {str(e)}")
                continue

    except Exception as e:
        print(f"Google News error: {str(e)}")

    return articles

@app.get("/api/content", response_model=ContentResponse)
async def get_content():
    try:
        articles = await fetch_google_news()
        return {"articles": articles}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)