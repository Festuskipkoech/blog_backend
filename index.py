from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from sqlalchemy import create_engine, Column, String, DateTime, Text, Boolean, desc
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai
from typing import List
import os
from pydantic import BaseModel
import asyncio
from fastapi.middleware.cors import CORSMiddleware

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

    class Config:
        orm_mode = True

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
        from_attributes = True  
        orm_mode = True

class ArticleResponse(BaseModel):
    articles: List[ArticleBase]
    total: int

# FastAPI app
app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def summarize_with_gemini(text: str) -> str:
    prompt = f"Summarize this article in 2-3 paragraphs: {text}"
    response = await asyncio.to_thread(
        lambda: model.generate_content(prompt).text
    )
    return response
async def scrape_article(url: str) -> dict:
    try:
        print(f"Starting to scrape URL: {url}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers)
        print(f"Response status code: {response.status_code}")
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Improved title selection - try multiple possible selectors
        title = ''
        title_selectors = [
            'h1.article-title',
            'h1.story-title',
            'article h1',
            '.article-header h1'
        ]
        for selector in title_selectors:
            title_elem = soup.select_one(selector)
            if title_elem:
                title = title_elem.text.strip()
                break
        print(f"Found title: {title}")
        
        # Improved content selection - try multiple possible selectors
        content = ''
        content_selectors = [
            '.story-content',
            '.article-content',
            'article .content',
            '.main-content'
        ]
        for selector in content_selectors:
            content_div = soup.select_one(selector)
            if content_div:
                # Exclude unwanted elements
                for unwanted in content_div.select('.advertisement, .social-share, .related-articles'):
                    unwanted.decompose()
                
                paragraphs = content_div.find_all('p')
                if paragraphs:
                    content = ' '.join([p.text.strip() for p in paragraphs])
                    break
        
        print(f"Content length: {len(content)} characters")
        
        # Improved author selection
        author = 'Unknown Author'
        author_selectors = [
            '.article-author',
            '.story-author',
            '.author-name',
            'span[itemprop="author"]'
        ]
        for selector in author_selectors:
            author_elem = soup.select_one(selector)
            if author_elem:
                author = author_elem.text.strip()
                break
        print(f"Found author: {author}")
        
        # Improved date selection
        date = datetime.now().isoformat()
        date_selectors = [
            'time[datetime]',
            '.article-date',
            '.story-date',
            'meta[property="article:published_time"]'
        ]
        for selector in date_selectors:
            date_elem = soup.select_one(selector)
            if date_elem:
                if 'datetime' in date_elem.attrs:
                    date = date_elem['datetime']
                elif 'content' in date_elem.attrs:
                    date = date_elem['content']
                else:
                    date = date_elem.text.strip()
                break
        
        return {
            "title": title,
            "content": content,
            "url": url,
            "date": date,
            "author": author
        }
    except Exception as e:
        print(f"Error in scrape_article: {str(e)}")
        raise
async def scrape_and_store(background_tasks: BackgroundTasks, db: Session):
    try:
        print("Starting scrape_and_store function")
        search_terms = ["Irungu Kang'ata", "Governor Kang'ata", "Murang'a Governor"]
        new_articles = 0
        
        # APPROACH 1: Try to get recent articles directly from the news sections
        sections = [
            "https://www.the-star.co.ke/news/",
            "https://www.the-star.co.ke/counties/",
            "https://www.the-star.co.ke/news/politics/",
            "https://www.the-star.co.ke/news/realtime/"
        ]
        
        article_urls = []
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
        
        # Try to get article URLs from main sections
        print("Fetching articles from main news sections")
        for section_url in sections:
            try:
                print(f"Checking section: {section_url}")
                response = requests.get(section_url, headers=headers)
                if response.status_code != 200:
                    print(f"Failed to get section {section_url}, status: {response.status_code}")
                    continue
                    
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Look for article cards/links with multiple selector patterns
                article_selectors = [
                    'a.article-card', 'a.news-card', '.article-list a', 
                    '.news-list a', '.story-card a', 'article a', 
                    '.headline a', '.card a', 'h2 a', 'h3 a'
                ]
                
                for selector in article_selectors:
                    links = soup.select(selector)
                    if links:
                        print(f"Found {len(links)} links with selector '{selector}'")
                        for link in links:
                            href = link.get('href')
                            if href and '/news/' in href and href.count('/') >= 3:
                                if not href.startswith('http'):
                                    href = 'https://www.the-star.co.ke' + href
                                article_urls.append(href)
                
                # If no links found with selectors, try a more general approach
                if not article_urls:
                    all_links = soup.find_all('a', href=True)
                    for link in all_links:
                        href = link.get('href', '')
                        # Check if it looks like an article URL (has multiple segments)
                        if '/news/' in href and href.count('/') >= 3 and not any(x in href for x in ['/tag/', '/author/', '/category/']):
                            if not href.startswith('http'):
                                href = 'https://www.the-star.co.ke' + href
                            article_urls.append(href)
                
            except Exception as e:
                print(f"Error processing section {section_url}: {str(e)}")
        
        # APPROACH 2: Try to get RSS feed if available
        try:
            rss_urls = [
                "https://www.the-star.co.ke/rss/",
                "https://www.the-star.co.ke/news/rss.xml",
                "https://www.the-star.co.ke/feed/"
            ]
            
            for rss_url in rss_urls:
                print(f"Trying RSS feed: {rss_url}")
                rss_response = requests.get(rss_url, headers=headers)
                if rss_response.status_code == 200:
                    try:
                        # Parse the RSS feed
                        rss_soup = BeautifulSoup(rss_response.content, 'xml')
                        items = rss_soup.find_all('item')
                        print(f"Found {len(items)} items in RSS feed")
                        
                        for item in items:
                            link_tag = item.find('link')
                            if link_tag and link_tag.text:
                                article_urls.append(link_tag.text)
                    except Exception as e:
                        print(f"Error parsing RSS feed: {str(e)}")
            
        except Exception as e:
            print(f"Error accessing RSS feeds: {str(e)}")
        
        # APPROACH 3: Try to get sitemap if available
        try:
            sitemap_urls = [
                "https://www.the-star.co.ke/sitemap.xml",
                "https://www.the-star.co.ke/sitemap_index.xml",
                "https://www.the-star.co.ke/sitemap-news.xml"
            ]
            
            for sitemap_url in sitemap_urls:
                print(f"Trying sitemap: {sitemap_url}")
                sitemap_response = requests.get(sitemap_url, headers=headers)
                if sitemap_response.status_code == 200:
                    try:
                        # Parse the sitemap
                        sitemap_soup = BeautifulSoup(sitemap_response.content, 'xml')
                        # For sitemap index
                        sitemaps = sitemap_soup.find_all('sitemap')
                        if sitemaps:
                            print(f"Found sitemap index with {len(sitemaps)} sitemaps")
                            for sitemap in sitemaps[:1]:  # Just check the first sitemap
                                loc = sitemap.find('loc')
                                if loc:
                                    sub_sitemap_url = loc.text
                                    sub_response = requests.get(sub_sitemap_url, headers=headers)
                                    if sub_response.status_code == 200:
                                        sub_soup = BeautifulSoup(sub_response.content, 'xml')
                                        urls = sub_soup.find_all('url')
                                        for url in urls:
                                            loc = url.find('loc')
                                            if loc and '/news/' in loc.text:
                                                article_urls.append(loc.text)
                        
                        # For regular sitemap
                        urls = sitemap_soup.find_all('url')
                        if urls:
                            print(f"Found {len(urls)} URLs in sitemap")
                            for url in urls[:100]:  # Limit to first 100
                                loc = url.find('loc')
                                if loc and '/news/' in loc.text:
                                    article_urls.append(loc.text)
                    except Exception as e:
                        print(f"Error parsing sitemap: {str(e)}")
            
        except Exception as e:
            print(f"Error accessing sitemaps: {str(e)}")
        
        # Remove duplicates and filter
        article_urls = list(set(article_urls))
        print(f"Found {len(article_urls)} total unique article URLs")
        
        # Process articles and filter for relevant ones
        processed_count = 0
        for url in article_urls[:30]:  # Process up to 30 most recent articles
            try:
                print(f"\nProcessing article URL: {url}")
                
                # Check if article already exists
                existing = db.query(Article).filter(Article.url == url).first()
                if existing:
                    print(f"Article already exists in database: {url}")
                    continue
                
                # Scrape article
                article_data = await scrape_article_improved(url)
                
                # Validate scraped content
                if not article_data['title'] or len(article_data['content']) < 100:
                    print("Missing or insufficient content, skipping")
                    continue
                
        # REPLACE THIS SECTION in scrape_and_store function:
                # Check if article mentions any search terms
                content_lower = article_data['content'].lower()
                title_lower = article_data['title'].lower()
                combined_text = content_lower + " " + title_lower

                # Print entire content for debugging
                print(f"Full article content: {content_lower}")

                mentioned_terms = []
                for term in search_terms:
                    # Normalize and create variations of the search term
                    base_term = term.lower().replace("'", "").replace("'", "").replace("'", "")
                    
                    # Alternative versions with just parts of the name
                    alt_terms = []
                    if "kang" in base_term:
                        alt_terms.extend(["kang", "kangata"])
                    if "murang" in base_term:
                        alt_terms.extend(["murang", "muranga"])
                    if "governor" in base_term:
                        alt_terms.append("governor")
                    if "irungu" in base_term:
                        alt_terms.append("irungu")
                    
                    # Check both title and content with flexible matching
                    found = False
                    for check_term in [base_term] + alt_terms:
                        if check_term in combined_text:
                            mentioned_terms.append(term)
                            print(f"MATCH FOUND: '{check_term}' in article")
                            found = True
                            break
                            
                    if not found:
                        print(f"No match found for '{term}' or its variations")

                if not mentioned_terms:
                    print("Article doesn't mention any search terms, skipping")
                    continue
                
                print(f"Article mentions these search terms: {mentioned_terms}")
                
                print("Summarizing article with Gemini")
                summary = await summarize_with_gemini(article_data['content'])
                
                # Store the article
                new_article = Article(
                    id=os.urandom(16).hex(),
                    title=article_data['title'],
                    content=summary,
                    url=article_data['url'],
                    author=article_data['author'],
                    date=datetime.fromisoformat(article_data['date']) if isinstance(article_data['date'], str) else article_data['date'],
                    is_processed=True
                )
                
                db.add(new_article)
                db.commit()
                print(f"Successfully added article: {article_data['title']}")
                new_articles += 1
                
                processed_count += 1
                if processed_count >= 5:  # Early exit after processing 5 articles successfully
                    break
                
            except Exception as e:
                db.rollback()
                print(f"Error processing article: {str(e)}")
                continue
            
        print(f"\nFinished scraping. Added {new_articles} new articles")
        return new_articles
        
    except Exception as e:
        print(f"Error in scrape_and_store: {str(e)}")
        raise

async def scrape_article_improved(url: str) -> dict:
    try:
        print(f"Starting to scrape URL: {url}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers)
        print(f"Response status code: {response.status_code}")
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # For debugging: Print the first 500 chars of HTML
        html_preview = soup.prettify()[:500].replace('\n', ' ')
        print(f"HTML preview: {html_preview}")
        
        # Check for article schema JSON
        article_json = None
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'NewsArticle':
                    article_json = data
                    break
                # Handle array of schemas
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'NewsArticle':
                            article_json = item
                            break
            except Exception as e:
                print(f"Error parsing JSON-LD: {str(e)}")
                continue
                
        # Extract from JSON if available
        if article_json:
            print("Found article schema JSON")
            title = article_json.get('headline', '')
            
            # Handle different author formats in JSON-LD
            author = article_json.get('author', {})
            if isinstance(author, dict):
                author = author.get('name', 'Unknown Author')
            elif isinstance(author, list) and len(author) > 0:
                if isinstance(author[0], dict):
                    author = author[0].get('name', 'Unknown Author') 
                else:
                    author = str(author[0])
            else:
                author = 'Unknown Author'
                
            date_published = article_json.get('datePublished', datetime.now().isoformat())
            
            # For content, we still need to parse the HTML
            content = ''
        else:
            # Title - expand selectors
            title = ''
            title_selectors = [
                'h1.article-title', 'h1.story-title', 'article h1', '.article-header h1',
                'h1.entry-title', 'h1.headline', 'h1[itemprop="headline"]', 
                'h1.title', 'header h1', 'main h1',
                '.article h1', '.story h1', '.post h1', 'h1', '.title'
            ]
            for selector in title_selectors:
                try:
                    title_elem = soup.select_one(selector)
                    if title_elem:
                        title = title_elem.text.strip()
                        print(f"Found title with selector '{selector}': {title[:50]}")
                        break
                except Exception as e:
                    print(f"Error with title selector '{selector}': {str(e)}")
            
            # Author - expand selectors
            author = 'Unknown Author'
            author_selectors = [
                '.article-author', '.story-author', '.author-name', 'span[itemprop="author"]',
                '.byline', '.author', 'a[rel="author"]', '[itemprop="author"] a',
                '.article-meta .author', '.meta .author', '.entry-meta .author',
                'p.byline', 'div.byline', '.reporter', '[class*="author"]', '[class*="byline"]'
            ]
            for selector in author_selectors:
                try:
                    author_elem = soup.select_one(selector)
                    if author_elem:
                        author = author_elem.text.strip()
                        print(f"Found author with selector '{selector}': {author}")
                        break
                except Exception as e:
                    print(f"Error with author selector '{selector}': {str(e)}")
            
            # Date - expand selectors
            date_published = datetime.now().isoformat()
            date_selectors = [
                'time[datetime]', '.article-date', '.story-date', 'meta[property="article:published_time"]',
                '[itemprop="datePublished"]', '.published-date', '.post-date',
                '.entry-date', 'time.entry-date', '.timestamp', '.publication-date',
                'meta[name="pubdate"]', 'meta[name="DC.date.published"]', 
                '[class*="date"]', 'time'
            ]
            for selector in date_selectors:
                try:
                    date_elem = soup.select_one(selector)
                    if date_elem:
                        if 'datetime' in date_elem.attrs:
                            date_published = date_elem['datetime']
                        elif 'content' in date_elem.attrs:
                            date_published = date_elem['content']
                        else:
                            date_published = date_elem.text.strip()
                        print(f"Found date with selector '{selector}': {date_published}")
                        break
                except Exception as e:
                    print(f"Error with date selector '{selector}': {str(e)}")
        
        # Content extraction with expanded selectors
        content = ''
        content_selectors = [
            '.story-content', '.article-content', 'article .content', '.main-content',
            '.entry-content', '[itemprop="articleBody"]', '.article-body', '.story-body',
            '.post-content', '#article-body', 'main article', 'article > div',
            '.article', '.story', '.post', '.content', '#content-main',
            'main .content', '.article-container', 'main', 'article'
        ]
        
        for selector in content_selectors:
            try:
                content_div = soup.select_one(selector)
                if content_div:
                    print(f"Found content container with selector '{selector}'")
                    # Exclude unwanted elements
                    for unwanted in content_div.select('aside, .advertisement, .social-share, .related-articles, .newsletter, script, style, .sidebar, nav, footer, header'):
                        if unwanted:
                            unwanted.decompose()
                    
                    paragraphs = content_div.find_all('p')
                    if paragraphs:
                        content = ' '.join([p.text.strip() for p in paragraphs])
                        if len(content) > 100:  # Minimum length check
                            break
            except Exception as e:
                print(f"Error with content selector '{selector}': {str(e)}")
        
        # If still no content, try direct article extraction
        if not content or len(content) < 100:
            try:
                print("Using fallback method for content extraction")
                all_paragraphs = soup.find_all('p')
                # Filter out short paragraphs that are likely not article content
                article_paragraphs = [p.text.strip() for p in all_paragraphs if len(p.text.strip()) > 40]
                if article_paragraphs:
                    content = ' '.join(article_paragraphs)
            except Exception as e:
                print(f"Error in fallback content extraction: {str(e)}")
        
        print(f"Title: {title[:50]}..." if title else "No title found")
        print(f"Content length: {len(content)} characters")
        print(f"Author: {author}")
        
        # Try to clean up/format the date
        try:
            if isinstance(date_published, str):
                # Remove any timezone designator if present
                date_published = date_published.split('+')[0].split('Z')[0].strip()
                # If it's just a date, add time
                if len(date_published) <= 10:
                    date_published += 'T00:00:00'
                # Ensure ISO format
                date_obj = datetime.fromisoformat(date_published)
                date_published = date_obj.isoformat()
        except Exception as e:
            print(f"Error formatting date, using current time: {str(e)}")
            date_published = datetime.now().isoformat()
        
        return {
            "title": title,
            "content": content,
            "url": url,
            "date": date_published,
            "author": author
        }
    except Exception as e:
        print(f"Error in scrape_article_improved: {str(e)}")
        # Return default values instead of raising exception
        return {
            "title": "Failed to extract title",
            "content": "",
            "url": url,
            "date": datetime.now().isoformat(),
            "author": "Unknown Author"
        }
@app.on_event("startup")
async def startup_event():
    print("Starting up FastAPI application")
    db = SessionLocal()
    try:
        background_tasks = BackgroundTasks()
        articles_added = await scrape_and_store(background_tasks, db)
        print(f"Startup completed. Added {articles_added} articles")
    except Exception as e:
        print(f"Error during startup: {str(e)}")
    finally:
        db.close()

# Add logging to the content endpoint
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
        
        return {
            "articles": [ArticleBase.from_orm(article) for article in articles],
            "total": total
        }
    except Exception as e:
        print(f"Error fetching articles: {str(e)}")
        raise
@app.get("/api/scrape")
async def scrape_new_articles(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    new_articles = await scrape_and_store(background_tasks, db)
    return {"message": f"Processed {new_articles} new articles"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


