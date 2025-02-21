from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy import create_engine, Column, String, DateTime, Text, Boolean, desc
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai
from typing import List, Dict, Optional, AsyncGenerator
from pydantic import BaseModel
import asyncio
import json
from fastapi.middleware.cors import CORSMiddleware
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
import time
import random
import uuid
import re
from contextlib import asynccontextmanager

# Database configuration
SQLALCHEMY_DATABASE_URL = "mysql+mysqlconnector://root:@localhost/news"
engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Configure Gemini API
genai.configure(api_key='AIzaSyBpoSvB_OWE2FMSUePJGpmj89yHOcNUmu0')
model = genai.GenerativeModel('gemini-pro')

# Database Model
class Article(Base):
    __tablename__ = "articles"
    
    id = Column(String(36), primary_key=True)
    title = Column(String(500), unique=True, index=True)
    content = Column(Text)
    url = Column(String(500))
    author = Column(String(100))
    date = Column(DateTime, default=datetime.utcnow)
    is_processed = Column(Boolean, default=False)

# Create tables
Base.metadata.create_all(bind=engine)

# Pydantic models
class ArticleBase(BaseModel):
    title: str
    content: str
    url: str
    author: str
    date: datetime

    class Config:
        orm_mode = True

class ArticleResponse(BaseModel):
    articles: List[ArticleBase]
    total: int

# Global queue for streaming processed articles
article_queue = asyncio.Queue()

# Context manager for database sessions
@asynccontextmanager
async def get_db_async():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# FastAPI app
app = FastAPI()

# Add CORS middleware with correct configuration for SSE
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Type"],
)

# Database dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

sources = [
    {
        "name": "Kenyan News",
        "url": "https://www.the-star.co.ke/search/?q=Irungu+Kang%27ata",
        "article_selector": "div.c-search-result__item",
        "title_selector": ".c-search-result__headline a, h3.c-search-result__headline",
        "date_selector": "time.c-timestamp",
        "content_selector": "div.c-search-result__text",
        "author_selector": "span.c-article__author",
        "wait_time": 5
    },
    {
        "name": "Citizen Digital",
        "url": "https://www.citizen.digital/search?q=Irungu+Kang%27ata",
        "article_selector": "div.article",
        "title_selector": ".article-title a, .article-title, h3 a",
        "date_selector": "span.date",
        "content_selector": "div.article-content",
        "author_selector": "span.author",
        "wait_time": 5
    },
    {
        "name": "Kenya News Agency",
        "url": "https://www.kenyanews.go.ke/search/kangata",
        "article_selector": "article",
        "title_selector": ".entry-title a, .entry-title",
        "date_selector": "time.entry-date",
        "content_selector": "div.entry-content",
        "author_selector": "span.author vcard",
        "wait_time": 5
    },
    {
        "name": "Capital News",
        "url": "https://www.capitalfm.co.ke/news/?s=Irungu+Kang%27ata",
        "article_selector": "div.jeg_posts article",
        "title_selector": ".jeg_post_title a, .jeg_post_title",
        "date_selector": "div.jeg_meta_date",
        "content_selector": "div.jeg_post_excerpt p",
        "author_selector": "div.jeg_meta_author",
        "wait_time": 5
    }
]

def get_webdriver():
    """Set up and return a headless Chrome webdriver"""
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.84 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.4 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:102.0) Gecko/20100101 Firefox/102.0"
    ]
    chrome_options.add_argument(f"user-agent={random.choice(user_agents)}")
    
    try:
        return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    except Exception as e:
        print(f"Error setting up WebDriver: {str(e)}")
        print("Trying alternative setup method...")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-infobars")
        return webdriver.Chrome(options=chrome_options)

async def summarize_with_gemini(text: str) -> str:
    try:
        prompt = f"Summarize this article in 2-3 paragraphs: {text}"
        response = await asyncio.to_thread(
            lambda: model.generate_content(prompt).text
        )
        return response
    except Exception as e:
        print(f"Error in Gemini summarization: {str(e)}")
        # Return a truncated version of the original text as fallback
        return text[:500] + "..." if len(text) > 500 else text

async def scrape_and_stream(db: Session):
    """Scrape articles and process them in parallel, adding to queue for streaming"""
    try:
        # Send initial status update
        await article_queue.put({"status": "started", "message": "Starting article scraping..."})
        
        # Run the Selenium scrapers in a background thread
        scraped_articles = await asyncio.to_thread(run_all_scrapers_selenium)
        print(f"Scraped {len(scraped_articles)} articles, processing now...")
        
        # Update status
        await article_queue.put({"status": "processing", "message": f"Processing {len(scraped_articles)} articles..."})
        
        # Process articles concurrently
        tasks = []
        for art in scraped_articles:
            task = asyncio.create_task(process_article(art, db))
            tasks.append(task)
        
        # Counter for processed articles
        processed_count = 0
        
        # As each article processing completes, add to queue
        for completed_task in asyncio.as_completed(tasks):
            processed_article = await completed_task
            if processed_article:
                await article_queue.put(processed_article)
                processed_count += 1
                
                # Send periodic progress updates
                if processed_count % 5 == 0:
                    await article_queue.put({
                        "status": "progress", 
                        "message": f"Processed {processed_count}/{len(tasks)} articles"
                    })
        
        # Send final status update
        await article_queue.put({
            "status": "complete", 
            "message": f"Completed processing {processed_count} articles"
        })
        
        # Signal that we're done (this is our completion marker)
        await article_queue.put(None)
        
        print(f"Processing complete! Processed {processed_count} articles")
    
    except Exception as e:
        print(f"Error in scrape_and_stream: {str(e)}")
        # Send error status
        await article_queue.put({
            "status": "error", 
            "message": f"Error during processing: {str(e)}"
        })
        # Signal completion even on error
        await article_queue.put(None)
def clean_text(text):
    """Clean up text by removing extra whitespace"""
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).strip()

def scrape_news_with_selenium(source: Dict) -> List[Dict]:
    """Scrape news articles from the given source using Selenium"""
    print(f"\n\033[1mScraping from {source['name']}...\033[0m")
    results = []
    driver = None
        
    try:
        driver = get_webdriver()
        print(f"Loading {source['url']}...")
        driver.get(source['url'])
        
        wait_time = source.get('wait_time', 5)
        WebDriverWait(driver, wait_time).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, source['article_selector']))
        )
        
        time.sleep(random.uniform(2, 4))
        
        articles = driver.find_elements(By.CSS_SELECTOR, source['article_selector'])
        print(f"Found {len(articles)} potential article elements")
        
        for idx, article in enumerate(articles[:5]):
            try:
                # Extract title and URL
                try:
                    title_element = article.find_element(By.CSS_SELECTOR, source['title_selector'])
                    title = clean_text(title_element.text)
                    link = title_element.get_attribute('href')
                except NoSuchElementException:
                    title = f"[Article {idx+1}]"
                    link = ""
                
                # Extract date
                try:
                    date_element = article.find_element(By.CSS_SELECTOR, source['date_selector'])
                    date = clean_text(date_element.text)
                except NoSuchElementException:
                    date = "Date not available"
                
                # Extract content
                try:
                    content_element = article.find_element(By.CSS_SELECTOR, source['content_selector'])
                    content = clean_text(content_element.text)
                except NoSuchElementException:
                    content = "Content not available"
                
                # Extract author
                try:
                    author_element = article.find_element(By.CSS_SELECTOR, source['author_selector'])
                    author = clean_text(author_element.text)
                except NoSuchElementException:
                    author = "Author not available"
                
                # Skip if no meaningful content found
                if (title == f"[Article {idx+1}]" or not title) and not link and content == "Content not available":
                    continue
                
                # Check relevance (using keywords as example)
                article_text = (title + " " + content).lower()
                if not any(term in article_text for term in ['kang', 'murang', 'governor']):
                    continue
                
                print(f"\033[1;32m{title}\033[0m")
                print(f"\033[0;36m{date} | By: {author}\033[0m")
                print(f"{content[:150]}..." if len(content) > 150 else content)
                if link:
                    print(f"\033[0;34m{link}\033[0m")
                print("-" * 80)
                
                results.append({
                    "title": title,
                    "date": date,
                    "content": content,
                    "author": author,
                    "link": link,
                    "source": source['name']
                })
                
            except Exception as e:
                print(f"Error processing article {idx+1}: {str(e)}")
                continue
        
    except TimeoutException:
        print(f"Timeout loading content from {source['name']}")
    except Exception as e:
        print(f"Error scraping {source['name']}: {str(e)}")
    finally:
        if driver:
            driver.quit()
    
    return results

def run_all_scrapers_selenium():
    """Run all scrapers using Selenium and return combined results"""
    all_results = []
    
    for source in sources:
        try:
            results = scrape_news_with_selenium(source)
            if results:
                all_results.extend(results)
            time.sleep(random.uniform(3, 5))
        except Exception as e:
            print(f"Failed to scrape {source['name']}: {str(e)}")
    
    return all_results
async def process_article(art: Dict, db: Session) -> Optional[Dict]:
    """Process a single article and return it if successful"""
    try:
        # Check for duplicate by title
        existing_article = db.query(Article).filter(Article.title == art["title"]).first()
        if existing_article:
            print(f"Skipping duplicate article: {art['title']}")
            return None

        # Use Gemini to summarize the scraped content
        try:
            summary = await summarize_with_gemini(art["content"])
        except Exception as e:
            print(f"Error summarizing article '{art['title']}': {str(e)}")
            summary = art["content"]  # Fallback to original content if summarization fails

        # Convert date string to datetime, fallback to now if conversion fails
        try:
            if isinstance(art["date"], str):
                # Try different date formats
                date_formats = [
                    "%Y-%m-%dT%H:%M:%S.%f", 
                    "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%d %H:%M:%S",
                    "%d %b %Y"
                ]
                article_date = None
                for fmt in date_formats:
                    try:
                        article_date = datetime.strptime(art["date"], fmt)
                        break
                    except ValueError:
                        continue
                
                if article_date is None:
                    article_date = datetime.now()
            else:
                article_date = datetime.now()
        except Exception as e:
            print(f"Date parsing error: {e}")
            article_date = datetime.now()

        article_id = str(uuid.uuid4())
        
        # Create article object
        new_article = Article(
            id=article_id,
            title=art["title"],
            content=summary,
            url=art["link"],
            author=art["author"],
            date=article_date,
            is_processed=True
        )
        
        # Add to database and commit
        db_success = False
        try:
            db.add(new_article)
            db.commit()
            db_success = True
            print(f"Successfully saved article: {art['title']}")
        except Exception as e:
            db.rollback()
            print(f"Database error saving article: {str(e)}")
        
        # Return processed article for streaming regardless of DB success
        # This ensures the frontend gets the article even if DB write fails
        processed_article = {
            "id": article_id,
            "title": art["title"],
            "content": summary,
            "url": art["link"],
            "author": art["author"],
            "date": article_date.isoformat(),
            "saved_to_db": db_success
        }
        
        print(f"Article processed and prepared for streaming: {art['title']}")
        return processed_article
        
    except Exception as e:
        print(f"Error processing article: {str(e)}")
        return None
async def stream_generator() -> AsyncGenerator[str, None]:
    """Generate SSE stream for processed articles and status updates"""
    try:
        # Send a connection established message
        yield "event: connected\ndata: {\"status\": \"connected\"}\n\n"
        
        while True:
            try:
                # Get processed article or status update from queue with timeout
                item = await asyncio.wait_for(article_queue.get(), timeout=1.0)
                
                if item is None:  # None is our signal that scraping is complete
                    yield "event: complete\ndata: {\"status\": \"complete\"}\n\n"
                    break
                    
                # Check if this is a status update or an article
                if isinstance(item, dict) and "status" in item:
                    # This is a status update
                    yield f"event: {item['status']}\ndata: {json.dumps(item)}\n\n"
                else:
                    # This is an article
                    yield f"event: article\ndata: {json.dumps(item)}\n\n"
                
            except asyncio.TimeoutError:
                # Send keep-alive comment to maintain connection
                yield ": keepalive\n\n"
                continue
                
    except asyncio.CancelledError:
        print("Stream connection closed")
        yield "event: close\ndata: {\"status\": \"closed\"}\n\n"
    except Exception as e:
        print(f"Error in stream generator: {str(e)}")
        yield f"event: error\ndata: {{\"status\": \"error\", \"message\": \"{str(e)}\"}}\n\n"
async def scrape_and_stream(db: Session):
    """Scrape articles and process them in parallel, adding to queue for streaming"""
    try:
        # Run the Selenium scrapers in a background thread
        scraped_articles = await asyncio.to_thread(run_all_scrapers_selenium)
        print(f"Scraped {len(scraped_articles)} articles, processing now...")
        
        # Process articles concurrently
        tasks = []
        for art in scraped_articles:
            task = asyncio.create_task(process_article(art, db))
            tasks.append(task)
        
        # As each article processing completes, add to queue
        for completed_task in asyncio.as_completed(tasks):
            processed_article = await completed_task
            if processed_article:
                await article_queue.put(processed_article)
        
        # Signal that we're done
        await article_queue.put(None)
        
        print(f"Processing complete!")
    
    except Exception as e:
        print(f"Error in scrape_and_stream: {str(e)}")
        # Signal completion even on error
        await article_queue.put(None)

@app.get("/api/content", response_model=ArticleResponse)
async def get_articles(
    page: int = 1,
    per_page: int = 4,
    db: Session = Depends(get_db)
):
    try:
        print(f"Fetching articles page {page} with {per_page} per page")
        offset = (page - 1) * per_page
        articles = db.query(Article).order_by(desc(Article.date)).offset(offset).limit(per_page).all()
        total = db.query(Article).count()
        print(f"Found {total} total articles, returning {len(articles)} for current page")
        
        # Convert ORM objects to dictionaries first
        article_dicts = []
        for article in articles:
            article_dict = {
                "title": article.title,
                "content": article.content,
                "url": article.url,
                "author": article.author,
                "date": article.date
            }
            article_dicts.append(article_dict)
        
        return {
            "articles": article_dicts,
            "total": total
        }
    except Exception as e:
        print(f"Error fetching articles: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
@app.get("/api/stream-scrape")
async def stream_scrape(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Stream articles as they are processed"""
    # Clear queue from any previous runs
    while not article_queue.empty():
        await article_queue.get()
    
    # Start scraping in the background
    background_tasks.add_task(scrape_and_stream, db)
    
    # Return streaming response
    return StreamingResponse(
        stream_generator(), 
        media_type="text/event-stream",
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'
        }
    )

@app.get("/api/scrape")
async def scrape_new_articles(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Legacy endpoint for non-streaming scrape"""
    # Clear the queue first
    while not article_queue.empty():
        await article_queue.get()
        
    # Start the scraping process
    background_tasks.add_task(scrape_and_stream, db)
    
    # Count how many articles were processed
    count = 0
    while True:
        article = await article_queue.get()
        if article is None:
            break
        count += 1
        
    return {"message": f"Processed {count} new articles"}

@app.on_event("startup")
async def startup_event():
    print("Starting up FastAPI application")
    async with get_db_async() as db:
        background_tasks = BackgroundTasks()
        background_tasks.add_task(scrape_and_stream, db)
        print("Initial scraping started in background")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)