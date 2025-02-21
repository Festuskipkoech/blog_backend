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
    "host": "localhost",
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
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# ------------------------
# Scraper configuration
# ------------------------

sources = [
    {
        "name": "The Star Kenya",
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

def get_webdriver():
    """Set up and return a headless Chrome webdriver."""
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.84 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.4 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:102.0) Gecko/20100101 Firefox/102.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.54 Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 15_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.5 Mobile/15E148 Safari/604.1"
    ]
    chrome_options.add_argument(f"user-agent={random.choice(user_agents)}")
    try:
        return webdriver.Chrome(ChromeDriverManager().install(), options=chrome_options)
    except Exception as e:
        print(f"Error setting up WebDriver: {str(e)}")
        print("Trying alternative setup method...")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-infobars")
        return webdriver.Chrome(options=chrome_options)

def clean_text(text):
    """Clean up text by removing extra whitespace."""
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).strip()

def scrape_news_with_selenium(source: Dict) -> List[Dict]:
    """Scrape news articles from the given source using Selenium."""
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
                # Extract title and link
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
                # Check relevance (example terms)
                article_text = (title + " " + content).lower()
                if not any(term in article_text for term in ['kang', 'murang', 'governor']):
                    continue
                # Print article info
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
def read_root():
    """Root endpoint - Welcome message"""
    return {
        "message": "Welcome to Irungu Kang'ata News Scraper",
        "endpoints": {
            "GET /": "This welcome message",
            "GET /scrape": "Scrape all news sources and save to MySQL",
            "GET /sources": "List all available news sources",
            "GET /scrape/{source_index}": "Scrape a specific source",
            "GET /health": "Check API health status",
            "GET /api/content": "Get paginated content with background scraping"
        }
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
        if cursor:
            cursor.close()
        if conn:
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

@app.get("/api/content")
async def get_content(
    background_tasks: BackgroundTasks,
    page: int = Query(1, ge=1),
    per_page: int = Query(6, ge=1, le=100)
):
    """
    Get paginated content from the database.
    Also trigger the scraper in the background.
    """
    # 1. Schedule the scraper to run in the background
    background_tasks.add_task(background_scrape_and_save)

    # 2. Immediately fetch content from the database
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        
        # Get total count
        cursor.execute("SELECT COUNT(*) as total FROM articles")
        total_result = cursor.fetchone()
        total = total_result['total'] if total_result else 0

        # Calculate offset
        offset = (page - 1) * per_page

        # Get paginated articles
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

        return {
            "status": "success",
            "articles": articles,
            "total": total,
            "message": "Scraping has started in the background; returning DB content."
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "articles": [],
            "total": 0
        }
    finally:
        if cursor:
            cursor.close()
        if conn:
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

@app.get("/health")
def health_check():
    """Check the health status of the API"""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "sources_configured": len(sources)
    }

@app.get("/stats")
def get_stats():
    """Get statistics about the articles database"""
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
        if cursor:
            cursor.close()
        if conn:
            conn.close()

if __name__ == "__main__":
    print("\033[1;35m" + "=" * 80)
    print("Irungu Kang'ata News Scraper".center(80))
    print("=" * 80 + "\033[0m")
    print("\n\033[1mBefore running, make sure you have installed:\033[0m")
    print("1. Python packages: pip install fastapi uvicorn selenium webdriver-manager mysql-connector-python")
    print("2. Chrome browser must be installed on your system")
    print("\nAvailable endpoints:")
    print("- Main page: http://localhost:8000")
    print("- Scrape all sources: http://localhost:8000/scrape")
    print("- List sources: http://localhost:8000/sources")
    print("- Scrape specific source: http://localhost:8000/scrape/{index}")
    print("- Health check: http://localhost:8000/health")
    print("- Stats: http://localhost:8000/stats")
    uvicorn.run(app, host="0.0.0.0", port=8000)