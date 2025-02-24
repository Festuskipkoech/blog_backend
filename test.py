from fastapi import FastAPI, BackgroundTasks, Query
import uvicorn
import time
import random
import re
import hashlib
from typing import List, Dict, Optional
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
import mysql.connector 
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Irungu Kang'ata News Scraper with Selenium and MySQL")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------
# MySQL Database Settings
# ------------------------

db_config = {
    "host": "127.1.0.0",
    "user": "root", 
    "password": "", 
    "database": "news_scraper" 
}

def init_db():
    """Initializes the database and creates the articles table if it doesn't exist."""
    try:
        # First, create the database if it doesn't exist
        conn = mysql.connector.connect(
            host=db_config["host"],
            user=db_config["user"],
            password=db_config["password"]
        )
        cursor = conn.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {db_config['database']}")
        conn.commit()
        cursor.close()
        conn.close()

        # Now connect to the created database and create the table
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id INT AUTO_INCREMENT PRIMARY KEY,
            title VARCHAR(255),
            date VARCHAR(255),
            content TEXT,
            author VARCHAR(255),
            link VARCHAR(511),
            source VARCHAR(255),
            content_hash VARCHAR(64) UNIQUE
        )
        """)
        conn.commit()
        cursor.close()
        conn.close()
        print("Database and table initialized successfully.")
    except Exception as e:
        print("Error initializing database:", e)

# Initialize the database at startup
init_db()

def generate_content_hash(article: Dict) -> str:
    """Generate a unique hash based on title and content to identify duplicate articles."""
    content_string = f"{article.get('title', '')}{article.get('content', '')}"
    return hashlib.sha256(content_string.encode()).hexdigest()

def save_to_db(articles: List[Dict]):
    """Save scraped articles to MySQL database with duplicate prevention."""
    conn = None
    cursor = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        inserted_count = 0
        duplicate_count = 0
        
        for article in articles:
            # Generate a unique hash for this article
            content_hash = generate_content_hash(article)
            article['content_hash'] = content_hash
            
            # Check if this article already exists in the database
            check_query = "SELECT id FROM articles WHERE content_hash = %s"
            cursor.execute(check_query, (content_hash,))
            exists = cursor.fetchone()
            
            if not exists:
                # Insert new article
                query = """
                INSERT INTO articles (title, date, content, author, link, source, content_hash)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """
                values = (
                    article.get("title"),
                    article.get("date"),
                    article.get("content"),
                    article.get("author"),
                    article.get("link"),
                    article.get("source"),
                    content_hash
                )
                cursor.execute(query, values)
                conn.commit()
                inserted_count += 1
            else:
                duplicate_count += 1
                
        print(f"Inserted {inserted_count} new articles into the database.")
        print(f"Skipped {duplicate_count} duplicate articles.")
    except Exception as e:
        print("Error saving to database:", e)
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()

# ------------------------
# Scraper configuration
# ------------------------

sources = [
    {
        "name": "The Star Kenya",
        "url": "https://www.the-star.co.ke/search/?q=Irungu+Kang%27ata",
        "article_selector": "div.c-search-result__item, article, .article",
        "title_selector": ".c-search-result__headline a, h3.c-search-result__headline, .article-title a",
        "date_selector": "time.c-timestamp, .date, time",
        "content_selector": "div.c-search-result__text, .article-story-content, .story-content, .summary",
        "author_selector": "span.c-article__author, .author, .byline",
        "mobile_only": False
    },

    {
        "name": "Citizen Digital",
        "url": "https://www.citizen.digital/search?q=Irungu+Kang%27ata",
        "article_selector": "div.article, article, .story",
        "title_selector": ".article-title a, h3 a, .story-title a",
        "date_selector": "span.date, time, .published-date",
        "content_selector": "div.article-content, .story-content, .excerpt",
        "author_selector": "span.author, .byline, .writer",
        "mobile_only": True
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
    },
    # Additional News Sources
    {
        "name": "Nation Africa",
        "url": "https://nation.africa/kenya/search?q=Irungu+Kang%27ata",
        "article_selector": "div.teaser-item, article.article-box",
        "title_selector": "h3.teaser-title a, h2.article-title a",
        "date_selector": "span.date-display-single, time",
        "content_selector": "div.teaser-text, div.field-summary",
        "author_selector": "div.byline, span.author",
        "wait_time": 6
    },
    {
        "name": "Standard Media",
        "url": "https://www.standardmedia.co.ke/search/Irungu%20Kang'ata",
        "article_selector": "div.article-wrapper, div.search-result-item",
        "title_selector": "h3.article-title a, h2 a",
        "date_selector": "span.article-date, time",
        "content_selector": "div.article-summary, p.summary",
        "author_selector": "span.author-name, div.article-author",
        "wait_time": 6
    },
    {
        "name": "The East African",
        "url": "https://www.theeastafrican.co.ke/tea/search?query=Irungu+Kang%27ata",
        "article_selector": "div.article-teaser, article.story",
        "title_selector": "h3.article-title a, h2.article-title a",
        "date_selector": "span.date, time.article-date",
        "content_selector": "div.article-summary, p.summary",
        "author_selector": "span.author, div.article-byline",
        "wait_time": 6
    },
    {
        "name": "K24 TV",
        "url": "https://www.k24tv.co.ke/?s=Irungu+Kang%27ata",
        "article_selector": "article.post, div.jeg_posts article",
        "title_selector": "h2.entry-title a, h3.jeg_post_title a",
        "date_selector": "time.entry-date, div.jeg_meta_date",
        "content_selector": "div.entry-content p, div.jeg_post_excerpt",
        "author_selector": "span.author-name, a.jeg_meta_author",
        "wait_time": 5
    }
]

def get_webdriver(source_name: str):
    """Set up and return a headless Chrome webdriver with site-specific configurations."""
    chrome_options = Options()
    
    # Basic options
    chrome_options.add_argument("--headless=new")  # Use new headless mode
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--window-size=1920,1080")
    
    # Anti-detection measures
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    # Site-specific configurations
    if "nation.africa" in source_name.lower():
        chrome_options.add_argument("--disable-javascript")
    elif "the-star.co.ke" in source_name.lower():
        chrome_options.add_argument("--disable-web-security")
    elif "citizen.digital" in source_name.lower():
        chrome_options.add_argument("--disable-features=IsolateOrigins,site-per-process")
    
    # Modern user agents for each site
    user_agents = {
        "The Star Kenya": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Citizen Digital": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2.1 Safari/605.1.15",
        "Nation Africa": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
        "Standard Media": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
        "default": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    }
    
    user_agent = user_agents.get(source_name, user_agents["default"])
    chrome_options.add_argument(f'user-agent={user_agent}')
    
    try:
        driver = webdriver.Chrome(options=chrome_options)
        
        # Additional anti-detection measures
        driver.execute_cdp_cmd('Network.setUserAgentOverride', {"userAgent": user_agent})
        
        # Execute stealth JavaScript
        driver.execute_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)
        
        return driver
    except Exception as e:
        print(f"Error setting up WebDriver for {source_name}: {str(e)}")
        raise

def scrape_news_with_selenium(source: Dict) -> List[Dict]:
    """Scrape news articles with enhanced anti-detection and site-specific handling."""
    print(f"\n\033[1mScraping from {source['name']}...\033[0m")
    results = []
    driver = None
    max_retries = 3
    current_retry = 0
    
    while current_retry < max_retries:
        try:
            if driver is not None:
                driver.quit()
            
            driver = get_webdriver(source['name'])
            print(f"Loading {source['url']}... (Attempt {current_retry + 1}/{max_retries})")
            
            # Site-specific loading strategies
            if "nation.africa" in source['url']:
                # Use requests first to get cookies
                import requests
                session = requests.Session()
                headers = {'User-Agent': driver.execute_script("return navigator.userAgent;")}
                response = session.get(source['url'], headers=headers)
                cookies = response.cookies.get_dict()
                for cookie in cookies:
                    driver.add_cookie({'name': cookie, 'value': cookies[cookie]})
                
            elif "the-star.co.ke" in source['url']:
                # Add referrer and modify URL parameters
                driver.execute_cdp_cmd('Network.setExtraHTTPHeaders', {
                    'headers': {
                        'Referer': 'https://www.google.com/'
                    }
                })
                
            elif "citizen.digital" in source['url']:
                # Use mobile user agent
                driver.execute_cdp_cmd('Network.setUserAgentOverride', {
                    "userAgent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1"
                })
            
            # Load the page with extended timeout
            driver.set_page_load_timeout(45)
            driver.get(source['url'])
            
            # Wait for content with multiple strategies
            wait = WebDriverWait(driver, 20)
            try:
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, source['article_selector'])))
            except TimeoutException:
                # Try alternative selectors
                alternative_selectors = [
                    'article', 
                    '.article',
                    '.story',
                    '.post',
                    'div[class*="article"]',
                    'div[class*="story"]'
                ]
                for selector in alternative_selectors:
                    try:
                        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                        source['article_selector'] = selector
                        break
                    except TimeoutException:
                        continue
            
            # Scroll and wait
            for _ in range(3):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight/4);")
                time.sleep(2)
            
            # Find articles
            articles = driver.find_elements(By.CSS_SELECTOR, source['article_selector'])
            
            if not articles:
                raise TimeoutException("No articles found")
            
            print(f"Found {len(articles)} potential article elements")
            
            # Process articles (rest of the processing code remains the same)
            for idx, article in enumerate(articles[:5]):
                try:
                    # ... (existing article processing code)
                    # Your existing code for processing individual articles goes here
                    pass
                    
                except Exception as e:
                    print(f"Error processing article {idx+1}: {str(e)}")
                    continue
            
            # If we get here successfully, break the retry loop
            if results:
                break
            else:
                current_retry += 1
                
        except TimeoutException:
            current_retry += 1
            print(f"Timeout loading content from {source['name']} (Attempt {current_retry}/{max_retries})")
            if current_retry == max_retries:
                print(f"Failed to load {source['name']} after {max_retries} attempts")
        except Exception as e:
            print(f"Error scraping {source['name']}: {str(e)}")
            current_retry += 1
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except:
                    pass
                
    return results
def clean_text(text):
    """Clean up text by removing extra whitespace."""
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).strip()
def run_all_scrapers_selenium():
    """Run all scrapers using Selenium and return combined results."""
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

# ------------------------
# FastAPI Endpoints
# ------------------------


@app.get("/")
async def read_root():
    """Root endpoint with API information."""
    return {
        "status": "success",
        "version": "2.0.0",
        "environment": os.getenv("ENVIRONMENT", "production"),
        "documentation": "/docs",
        "health_check": "/health"
    }
@app.get("/scrape")
async def scrape_endpoint(
    background_tasks: BackgroundTasks,
    page: int = Query(1, ge=1),
    per_page: int = Query(6, ge=1, le=100)
):
    # Schedule the scraping process to run in the background
    background_tasks.add_task(background_scrape_and_save)
    
    # Immediately fetch content from the database
    conn = None
    cursor = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        # Get total count
        cursor.execute("SELECT COUNT(*) as total FROM articles")
        total_result = cursor.fetchone()
        total = total_result['total'] if total_result else 0
        
        # Calculate offset based on the page
        offset = (page - 1) * per_page
        query = """
        SELECT 
            id,
            title,
            date,
            content,
            author,
            link as url,
            source
        FROM articles
        ORDER BY date DESC
        LIMIT %s OFFSET %s
        """
        cursor.execute(query, (per_page, offset))
        articles = cursor.fetchall()
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "articles": [],
            "total": 0
        }
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()
    
    return {
        "status": "success",
        "articles_found": len(articles),
        "data": articles,
        "message": "Scraping initiated in background. Fetched content from database."
    }

def background_scrape_and_save():
    """Run the scraper and save results to the database in the background."""
    results = run_all_scrapers_selenium()
    save_to_db(results)


@app.get("/health")
async def health_check():
    """Enhanced health check endpoint."""
    try:
        # Check database connection
        conn = mysql.connector.connect(**db_config)
        conn.close()
        db_status = "healthy"
    except Exception as e:
        db_status = "unhealthy"
        logger.error(f"Database health check failed: {str(e)}")

    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "environment": os.getenv("ENVIRONMENT", "production"),
        "database": db_status,
        "version": "2.0.0"
    }

@app.get("/api/content")
async def get_content(
    background_tasks: BackgroundTasks,
    page: int = Query(1, ge=1),
    per_page: int = Query(6, ge=1, le=100)
):
    """Get paginated content with background scraping."""
    try:
        # Schedule background scraping
        background_tasks.add_task(background_scrape_and_save)
        
        # Fetch content from database
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        
        # Get total count
        cursor.execute("SELECT COUNT(*) as total FROM articles")
        total = cursor.fetchone()['total']
        
        # Calculate pagination
        offset = (page - 1) * per_page
        
        # Fetch articles
        cursor.execute("""
            SELECT id, title, date, content, author, link as url, source
            FROM articles
            ORDER BY date DESC
            LIMIT %s OFFSET %s
        """, (per_page, offset))
        articles = cursor.fetchall()
        
        return {
            "status": "success",
            "total": total,
            "page": page,
            "per_page": per_page,
            "articles": articles
        }
    except Exception as e:
        logger.error(f"Content retrieval error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()

@app.get("/sources")
def list_sources():
    """List all configured news sources"""
    return {
        "status": "success",
        "count": len(sources),
        "sources": [
            {
                "index": i,
                "name": source["name"],
                "url": source["url"]
            } for i, source in enumerate(sources)
        ]
    }

@app.get("/scrape/{source_index}")
async def scrape_specific_source(source_index: int, background_tasks: BackgroundTasks):
    """Scrape a specific source by index and save results to MySQL."""
    try:
        if source_index < 0 or source_index >= len(sources):
            return {
                "status": "error",
                "message": f"Invalid source index. Must be between 0 and {len(sources)-1}"
            }
        specific_source = sources[source_index]
        results = scrape_news_with_selenium(specific_source)
        background_tasks.add_task(save_to_db, results)
        return {
            "status": "success",
            "source": specific_source["name"],
            "articles_found": len(results),
            "data": results
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

@app.get("/stats")
def get_stats():
    """Get statistics about the articles database"""
    conn = None
    cursor = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        
        # Get total count
        cursor.execute("SELECT COUNT(*) as total FROM articles")
        total_result = cursor.fetchone()
        total = total_result['total'] if total_result else 0
        
        # Get counts by source
        cursor.execute("SELECT source, COUNT(*) as count FROM articles GROUP BY source ORDER BY count DESC")
        source_stats = cursor.fetchall()
        
        # Get date range
        cursor.execute("SELECT MIN(date) as oldest, MAX(date) as newest FROM articles")
        date_range = cursor.fetchone()
        
        return {
            "status": "success",
            "total_articles": total,
            "source_distribution": source_stats,
            "date_range": date_range
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()

if __name__ == "__main__":
    # Create logs directory if it doesn't exist
    os.makedirs("logs", exist_ok=True)
    
    # Start the server
    port = int(os.getenv("PORT", 8001))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        workers=int(os.getenv("WORKERS", 1)),
        access_log=True
    )