# main.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import httpx
from bs4 import BeautifulSoup
import os
from dotenv import load_dotenv
import asyncio

# Load environment variables
load_dotenv()

app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Models
class Article(BaseModel):
    title: str
    url: str
    date: str
    content: Optional[str] = None
    author: str = "The Star"

class NewsResponse(BaseModel):
    articles: List[Article]

# Constants
STAR_URL = "https://www.the-star.co.ke/search/?q=irungu+kangata"
GEMINI_API_KEY = "AIzaSyAgODODTcnhBdWGA4bWszvVUz9teA_BLz8"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent"

async def scrape_star_news():
    """Scrape news articles from The Star website."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(STAR_URL)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            articles = []
            
            # Adjust selectors based on The Star's actual HTML structure
            for article in soup.select('.article-item'):
                title_elem = article.select_one('.article-title')
                url_elem = article.select_one('a')
                date_elem = article.select_one('.article-date')
                
                if title_elem and url_elem:
                    articles.append(Article(
                        title=title_elem.text.strip(),
                        url=f"https://www.the-star.co.ke{url_elem['href']}",
                        date=date_elem.text.strip() if date_elem else "N/A",
                        author="The Star"
                    ))
            
            return articles
            
        except httpx.RequestError as e:
            raise HTTPException(status_code=500, detail=f"Failed to scrape news articles: {str(e)}")

async def get_article_content(url: str):
    """Extract content from a specific article URL."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            # Adjust selector based on The Star's article content structure
            content_paragraphs = soup.select('.article-content p')
            content = '\n'.join([p.text.strip() for p in content_paragraphs])
            
            return content
            
        except httpx.RequestError as e:
            raise HTTPException(status_code=500, detail=f"Failed to extract article content: {str(e)}")

async def summarize_with_gemini(content: str):
    """Generate summary using Gemini API."""
    async with httpx.AsyncClient() as client:
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {GEMINI_API_KEY}"
            }
            
            payload = {
                "contents": [{
                    "parts": [{
                        "text": f"Summarize this news article in 2-3 sentences: {content}"
                    }]
                }]
            }
            
            response = await client.post(
                GEMINI_URL,
                headers=headers,
                json=payload
            )
            response.raise_for_status()
            
            summary = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            return summary
            
        except httpx.RequestError as e:
            raise HTTPException(status_code=500, detail=f"Failed to generate summary: {str(e)}")

@app.get("/api/content", response_model=NewsResponse)
async def get_content():
    """Main endpoint to get scraped and summarized news articles."""
    try:
        # Get articles
        articles = await scrape_star_news()
        
        # Process only first 5 articles
        articles = articles[:5]
        
        # Create tasks for concurrent processing
        async def process_article(article):
            content = await get_article_content(article.url)
            summary = await summarize_with_gemini(content)
            article.content = summary
            return article
        
        # Process articles concurrently
        tasks = [process_article(article) for article in articles]
        processed_articles = await asyncio.gather(*tasks)
        
        return NewsResponse(articles=processed_articles)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)