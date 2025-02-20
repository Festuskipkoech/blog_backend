from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from pydantic import BaseModel
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import re
from newspaper import Article
import nltk
from typing import List, Optional
import asyncio
import schedule
import time
import threading
from urllib.parse import urlparse

# Download nltk data for summarization
nltk.download('punkt')

# Database setup
DATABASE_URL = "mysql+pymysql://root:password@localhost/news_db"  # Change credentials as needed
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# SQLAlchemy Model
class NewsArticle(Base):
    __tablename__ = "articles"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), index=True)
    url = Column(String(255), unique=True, index=True)
    source = Column(String(100))
    published_date = Column(DateTime, nullable=True)
    original_content = Column(Text)
    summary = Column(Text)
    created_at = Column(DateTime, default=func.now())

# Create tables
Base.metadata.create_all(bind=engine)

# Pydantic models for API
class ArticleBase(BaseModel):
    title: str
    url: str
    source: str
    summary: str
    published_date: Optional[datetime] = None

class ArticleCreate(ArticleBase):
    original_content: str

class ArticleResponse(ArticleBase):
    id: int
    created_at: datetime
    
    class Config:
        orm_mode = True

class PaginatedResponse(BaseModel):
    total: int
    page: int
    per_page: int
    total_pages: int
    data: List[ArticleResponse]

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# FastAPI app
app = FastAPI(title="Targeted News Scraper for Irungu Kangata")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this to your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Functions for scraping The Star
def extract_date(date_text):
    try:
        return datetime.strptime(date_text.strip(), '%d %b %Y - %H:%M')
    except:
        return datetime.now()  # Fallback to current time if parsing fails

def scrape_star_newspaper():
    articles = []
    search_urls = [
        "https://www.the-star.co.ke/search/?q=Irungu+Kangata",
        "https://www.the-star.co.ke/search/?q=Kiambu+Governor",
        "https://www.the-star.co.ke/counties/central/"
    ]
    
    for search_url in search_urls:
        try:
            response = requests.get(search_url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Try multiple selector patterns to find articles
            article_links = []
            selectors = [
                'div.card-body h3 a', 
                'div.col-12 h4 a',
                '.article-title a',  # Common pattern in news sites
                '.search-results a',  # Search results specific
                'article h2 a',       # Another common pattern
                'a.article-link'      # Direct article links
            ]
            
            for selector in selectors:
                links = soup.select(selector)
                if links:
                    article_links.extend(links)
                    print(f"Found {len(links)} links with selector: {selector}")
            
            print(f"Total links found on {search_url}: {len(article_links)}")
            
            for link in article_links:
                article_url = link.get('href')
                if not article_url:
                    continue
                
                # Make sure URL is absolute
                if not urlparse(article_url).netloc:
                    article_url = f"https://www.the-star.co.ke{article_url}"
                
                # Skip if we've seen this URL already
                if any(a['url'] == article_url for a in articles):
                    continue
                
                try:
                    print(f"Processing article: {article_url}")
                    
                    # Use newspaper3k to extract article content
                    article = Article(article_url)
                    article.download()
                    article.parse()
                    
                    # Debug the article content
                    if not article.title:
                        print(f"No title found for {article_url}")
                        continue
                        
                    # Check if article is relevant with relaxed criteria
                    if not is_about_irungu_kangata_relaxed(article.title + " " + article.text):
                        print(f"Article not relevant: {article.title}")
                        continue
                    
                    # Do NLP after confirming article is valid
                    article.nlp()
                    
                    # Extract date
                    pub_date = article.publish_date if article.publish_date else datetime.now()
                    
                    articles.append({
                        'title': article.title,
                        'url': article_url,
                        'source': 'The Star',
                        'published_date': pub_date,
                        'original_content': article.text,
                        'summary': article.summary
                    })
                    print(f"Added article: {article.title}")
                except Exception as e:
                    print(f"Error processing article {article_url}: {str(e)}")
                    continue
                
                # Respect the site
                time.sleep(2)
            
        except Exception as e:
            print(f"Error scraping {search_url}: {str(e)}")
    
    print(f"Total articles collected: {len(articles)}")
    return articles

# Relaxed relevance check
def is_about_irungu_kangata_relaxed(text):
    # Check if article mentions Irungu Kangata and related terms
    keywords = [
        'irungu kangata', 'kangata', 'governor kiambu', 
        'kiambu governor', 'kiambu county'
    ]
    text_lower = text.lower()
    
    # Only require one keyword match for greater coverage
    for keyword in keywords:
        if keyword in text_lower:
            return True
    return False
# Save scraped articles to the database
def save_articles_to_db(articles, db: Session):
    new_articles_count = 0
    
    for article_data in articles:
        # Check if article already exists
        existing = db.query(NewsArticle).filter(NewsArticle.url == article_data['url']).first()
        if existing:
            continue
            
        article = NewsArticle(
            title=article_data['title'],
            url=article_data['url'],
            source=article_data['source'],
            published_date=article_data['published_date'],
            original_content=article_data['original_content'],
            summary=article_data['summary']
        )
        db.add(article)
        new_articles_count += 1
    
    if new_articles_count > 0:
        db.commit()
    
    return new_articles_count

# Scheduled scraping function
def run_scheduled_scraping():
    db = SessionLocal()
    try:
        articles = scrape_star_newspaper()
        count = save_articles_to_db(articles, db)
        print(f"Scheduled scraping completed. Added {count} new articles.")
    except Exception as e:
        print(f"Error in scheduled scraping: {str(e)}")
    finally:
        db.close()

# Setup scheduler to run every 6 hours
def start_scheduler():
    schedule.every(6).hours.do(run_scheduled_scraping)
    
    while True:
        schedule.run_pending()
        time.sleep(60)

# Start the scheduler in a separate thread
scheduler_thread = threading.Thread(target=start_scheduler, daemon=True)
scheduler_thread.start()

# API Routes
@app.get("/api/content", response_model=PaginatedResponse)
def get_articles(
    page: int = Query(1, gt=0),
    per_page: int = Query(10, gt=0, le=100),
    db: Session = Depends(get_db)
):
    # Calculate pagination
    total = db.query(NewsArticle).count()
    skip = (page - 1) * per_page
    
    # Get articles sorted by published date (newest first)
    articles = db.query(NewsArticle).order_by(
        NewsArticle.published_date.desc()
    ).offset(skip).limit(per_page).all()
    
    total_pages = (total + per_page - 1) // per_page  # Ceiling division
    
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "data": articles
    }

@app.get("/api/scrape")
async def trigger_scrape(db: Session = Depends(get_db)):
    try:
        articles = scrape_star_newspaper()
        count = save_articles_to_db(articles, db)
        return {"message": f"Scraping completed. Found {len(articles)} articles, added {count} new ones."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scraping failed: {str(e)}")

@app.get("/api/articles/{article_id}", response_model=ArticleResponse)
def get_article(article_id: int, db: Session = Depends(get_db)):
    article = db.query(NewsArticle).filter(NewsArticle.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return article

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)