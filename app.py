from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import httpx
from bs4 import BeautifulSoup
import datetime
import sqlite3
import os
from contextlib import contextmanager
import re
import json
import google.generativeai as genai
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure Gemini API
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable not set")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-pro')

# Database setup
DB_PATH = "news_articles.db"

def create_tables():
    with get_db_connection() as conn:
        conn.execute('''
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            original_content TEXT NOT NULL,
            summarized_content TEXT NOT NULL,
            url TEXT NOT NULL UNIQUE,
            image_url TEXT,
            author TEXT,
            date TEXT,
            category TEXT,
            created_at TEXT NOT NULL
        )
        ''')

@contextmanager
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

# Models
class Article(BaseModel):
    id: int
    title: str
    content: str
    url: str
    image_url: Optional[str] = None
    author: Optional[str] = "Staff Reporter"
    date: str
    category: Optional[str] = "Politics"

class ArticleResponse(BaseModel):
    articles: List[Article]
    total: int

# Initialize FastAPI app
app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create tables at startup
@app.on_event("startup")
async def startup_event():
    create_tables()

# Routes
@app.get("/api/content", response_model=ArticleResponse)
async def get_content(page: int = 1, per_page: int = 6):
    with get_db_connection() as conn:
        offset = (page - 1) * per_page
        
        # Get total count
        total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        
        # Get paginated articles
        rows = conn.execute(
            "SELECT * FROM articles ORDER BY date DESC LIMIT ? OFFSET ?",
            (per_page, offset)
        ).fetchall()
        
        articles = []
        for row in rows:
            articles.append(Article(
                id=row['id'],
                title=row['title'],
                content=row['summarized_content'],
                url=row['url'],
                image_url=row['image_url'],
                author=row['author'] or "Staff Reporter",
                date=row['date'],
                category=row['category'] or "Politics"
            ))
        
        return ArticleResponse(articles=articles, total=total)

@app.get("/api/scrape")
async def scrape_articles(background_tasks: BackgroundTasks):
    """Trigger scraping of new articles in the background"""
    background_tasks.add_task(scrape_and_process_articles)
    return {"status": "Scraping started in background"}

async def scrape_and_process_articles():
    """Scrape, summarize and store articles"""
    try:
        # Scrape articles from the Star
        articles = await scrape_star_articles()
        
        # Process and store each article
        for article in articles:
            await process_article(article)
            
        return len(articles)
    except Exception as e:
        print(f"Error in scraping process: {str(e)}")
        return 0

async def scrape_star_articles():
    """Scrape articles from The Star website's politics section"""
    base_url = "https://www.the-star.co.ke"
    sections="Irungu Kangata"
    politics_url = f"https://www.the-star.co.ke/counties/central/2024-12-02-kangata-care-programme-wins-continental-award-in-kampala"  
    # Removed trailing slash
    
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:  # Added follow_redirects
        # Get politics page
        print(f"Fetching politics page: {politics_url}")
        response = await client.get(politics_url)
        response.raise_for_status()
        
        print(f"Response status: {response.status_code}")
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Debug: Check what we're getting
        page_title = soup.select_one("title")
        print(f"Page title: {page_title.text if page_title else 'Not found'}")
        
        articles = []
        
        # Find article teasers on the page - let's try different selectors
        article_elements = soup.select(".story-teaser, .teaser, article, .node--type-article")
        print(f"Found {len(article_elements)} potential article elements")
        
        for element in article_elements[:10]:  # Limit to first 10 results
            try:
                # Try multiple possible selectors for title
                title_element = (element.select_one("h3 a") or 
                                element.select_one("h2 a") or 
                                element.select_one(".title a") or
                                element.select_one("a[href*='/news/']"))
                
                if not title_element:
                    print("No title element found in article")
                    continue
                    
                title = title_element.get_text(strip=True)
                url = title_element.get('href', '')
                
                print(f"Found potential article: {title} | URL: {url}")
                
                if not url.startswith("http"):
                    url = base_url + url
                
                # Filter for articles mentioning Kang'ata
                if "kangata" not in title.lower() and "irungu" not in title.lower():
                    print(f"Article doesn't mention target in title, checking content...")
                    # Fetch article to check content for mentions
                    article_response = await client.get(url)
                    article_soup = BeautifulSoup(article_response.text, 'html.parser')
                    
                    # Try different content selectors
                    content_element = (article_soup.select_one(".field--name-body") or 
                                      article_soup.select_one(".node__content") or
                                      article_soup.select_one("article"))
                    
                    if content_element:
                        content_text = content_element.get_text().lower()
                        if "kangata" not in content_text and "irungu" not in content_text:
                            print("Target not mentioned in content, skipping")
                            continue
                    else:
                        print("No content element found, skipping")
                        continue
                
                # Check if article already exists
                with get_db_connection() as conn:
                    existing = conn.execute("SELECT id FROM articles WHERE url = ?", (url,)).fetchone()
                    if existing:
                        print(f"Article already exists in DB: {url}")
                        continue
                
                # Fetch the full article
                print(f"Fetching full article: {url}")
                article_response = await client.get(url)
                article_soup = BeautifulSoup(article_response.text, 'html.parser')
                
                # Extract content - try multiple selectors
                content_element = (article_soup.select_one(".field--name-body") or 
                                  article_soup.select_one(".node__content") or
                                  article_soup.select_one("article .content"))
                
                content = ""
                if content_element:
                    paragraphs = content_element.select("p")
                    if paragraphs:
                        content = " ".join([p.get_text(strip=True) for p in paragraphs])
                    else:
                        # Fallback to get all text
                        content = content_element.get_text(strip=True)
                
                # Extract date with multiple selectors
                date_element = (article_soup.select_one(".created-date") or
                              article_soup.select_one(".date") or
                              article_soup.select_one("time"))
                              
                date_str = date_element.get_text(strip=True) if date_element else datetime.datetime.now().strftime("%B %d, %Y")
                
                # Extract author with multiple selectors
                author_element = (article_soup.select_one(".author-name") or
                                article_soup.select_one(".byline") or
                                article_soup.select_one("[rel='author']"))
                                
                author = author_element.get_text(strip=True) if author_element else "Staff Reporter"
                
                # Extract image with multiple selectors
                image_element = (article_soup.select_one(".field--name-field-image img") or
                               article_soup.select_one(".article-image img") or
                               article_soup.select_one("article img"))
                               
                image_url = image_element.get('src') if image_element else None
                
                print(f"Successfully processed article: {title}")
                
                articles.append({
                    "title": title,
                    "url": url,
                    "content": content,
                    "date": date_str,
                    "author": author,
                    "image_url": image_url
                })
                
            except Exception as e:
                print(f"Error extracting article: {str(e)}")
                continue
                
        print(f"Total valid articles found: {len(articles)}")
        return articles
async def summarize_with_gemini(content, title):
    """Use Gemini to summarize article content"""
    try:
        prompt = f"""
        Please summarize this news article about Governor Irungu Kang'ata. 
        Focus on key events, quotes, and policy decisions.
        Keep the summary informative but concise (150-200 words).
        
        Title: {title}
        
        Article content:
        {content}
        """
        
        response = model.generate_content(prompt)
        summary = response.text.strip()
        
        # Fallback if summary is too short
        if len(summary) < 50 and len(content) > 200:
            return content[:200] + "..."
            
        return summary
    except Exception as e:
        print(f"Error summarizing with Gemini: {str(e)}")
        # Fallback to simple truncation if AI summarization fails
        if len(content) > 200:
            return content[:200] + "..."
        return content

async def process_article(article_data):
    """Process and store a single article"""
    try:
        # Skip if content is too short
        if len(article_data["content"]) < 50:
            return False
            
        # Generate summary using Gemini
        summary = await summarize_with_gemini(article_data["content"], article_data["title"])
        
        # Store in database
        with get_db_connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO articles 
                (title, original_content, summarized_content, url, image_url, author, date, category, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    article_data["title"],
                    article_data["content"],
                    summary,
                    article_data["url"],
                    article_data.get("image_url"),
                    article_data.get("author", "Staff Reporter"),
                    article_data.get("date", datetime.datetime.now().strftime("%Y-%m-%d")),
                    "Politics",  # Default category
                    datetime.datetime.now().isoformat()
                )
            )
            conn.commit()
            
        return True
    except Exception as e:
        print(f"Error processing article: {str(e)}")
        return False

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)