from fastapi import FastAPI, BackgroundTasks
import uvicorn
import time
import random
from typing import List, Dict
import re
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager

app = FastAPI(title="Irungu Kang'ata News Scraper with Selenium")

# Updated news sources with new selectors
sources = [
    {
        "name": "Kenyan News",
        "url": "https://www.the-star.co.ke/search/?q=Irungu+Kang%27ata",
        "article_selector": "div.c-search-result__item",
        "title_selector": ".c-search-result__headline a, h3.c-search-result__headline",  # Added alternative
        "date_selector": "time.c-timestamp",
        "content_selector": "div.c-search-result__text",
        "author_selector": "span.c-article__author",
        "wait_time": 5
    },
    {
        "name": "Citizen Digital",
        "url": "https://www.citizen.digital/search?q=Irungu+Kang%27ata",
        "article_selector": "div.article",
        "title_selector": ".article-title a, .article-title, h3 a",  # Added more options
        "date_selector": "span.date",
        "content_selector": "div.article-content",
        "author_selector": "span.author",
        "wait_time": 5
    },
    {
        "name": "Kenya News Agency",
        "url": "https://www.kenyanews.go.ke/search/kangata",
        "article_selector": "article",
        "title_selector": ".entry-title a, .entry-title",  # Simplified selector
        "date_selector": "time.entry-date",
        "content_selector": "div.entry-content",
        "author_selector": "span.author vcard",
        "wait_time": 5
    },
    {
        "name": "Capital News",
        "url": "https://www.capitalfm.co.ke/news/?s=Irungu+Kang%27ata",
        "article_selector": "div.jeg_posts article",
        "title_selector": ".jeg_post_title a, .jeg_post_title",  # Added alternative
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
        return webdriver.Chrome(ChromeDriverManager().install(), options=chrome_options)
    except Exception as e:
        print(f"Error setting up WebDriver: {str(e)}")
        print("Trying alternative setup method...")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-infobars")
        return webdriver.Chrome(options=chrome_options)

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
                # Extract title
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
                
                # Check relevance
                article_text = (title + " " + content).lower()
                if not any(term in article_text for term in ['kang', 'murang', 'governor']):
                    continue
                
                # Format and print results
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

# FastAPI Endpoints

@app.get("/")
def read_root():
    """Root endpoint - Welcome message"""
    return {
        "message": "Welcome to Irungu Kang'ata News Scraper",
        "endpoints": {
            "GET /": "This welcome message",
            "GET /scrape": "Scrape all news sources",
            "GET /sources": "List all available news sources",
            "GET /scrape/{source_index}": "Scrape a specific source",
            "GET /health": "Check API health status"
        }
    }

@app.get("/api/scrape")
async def scrape_endpoint():
    """Endpoint to scrape all sources"""
    try:
        results = run_all_scrapers_selenium()
        return {
            "status": "success",
            "articles_found": len(results),
            "data": results
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

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
from fastapi import FastAPI, BackgroundTasks, Query
import uvicorn
import time
import random
from typing import List, Dict, Optional
import re
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager

# Define a global variable to store the last scraped results
# This will serve as a simple in-memory cache
last_scraped_results = []
last_scrape_time = None

# Add these functions after your existing scraping functions

def get_cached_results():
    """Return the cached results and the time since last scrape"""
    global last_scraped_results, last_scrape_time
    
    current_time = time.time()
    time_since_scrape = None
    
    if last_scrape_time:
        time_since_scrape = current_time - last_scrape_time
    
    return {
        "results": last_scraped_results,
        "time_since_scrape": time_since_scrape
    }

def update_cache_with_results(results):
    """Update the in-memory cache with new results"""
    global last_scraped_results, last_scrape_time
    
    last_scraped_results = results
    last_scrape_time = time.time()

# Add this endpoint to your existing FastAPI application

@app.get("/api/content")
async def get_content(
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(10, ge=1, le=50, description="Items per page")
):
    """
    Get articles with pagination support from the cached results.
    If cache is empty or older than 30 minutes, it triggers a new scrape.
    """
    global last_scraped_results, last_scrape_time
    
    # Check if we need to scrape (empty cache or older than 30 minutes)
    cache_data = get_cached_results()
    need_scrape = (
        not cache_data["results"] or 
        not cache_data["time_since_scrape"] or 
        cache_data["time_since_scrape"] > 1800  # 30 minutes
    )
    
    if need_scrape:
        try:
            # Run scraper to get fresh data
            results = run_all_scrapers_selenium()
            update_cache_with_results(results)
        except Exception as e:
            # If scraping fails but we have cached results, use them
            if cache_data["results"]:
                print(f"Scraping failed, using cached results. Error: {str(e)}")
            else:
                return {
                    "status": "error",
                    "message": f"Failed to retrieve content: {str(e)}",
                    "articles": [],
                    "pagination": {
                        "current_page": page,
                        "per_page": per_page,
                        "total_items": 0,
                        "total_pages": 0
                    }
                }
    
    # Get the current set of results (either freshly scraped or from cache)
    all_articles = last_scraped_results
    
    # Calculate pagination details
    total_items = len(all_articles)
    total_pages = max(1, (total_items + per_page - 1) // per_page)
    
    # Ensure page is within valid range
    page = min(max(1, page), total_pages)
    
    # Calculate slice indices
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    
    # Get the slice of articles for the requested page
    paged_articles = all_articles[start_idx:end_idx]
    
    # Add cache age information
    cache_age_minutes = None
    if cache_data["time_since_scrape"]:
        cache_age_minutes = round(cache_data["time_since_scrape"] / 60, 1)
    
    return {
        "status": "success",
        "articles": paged_articles,
        "cache_info": {
            "age_minutes": cache_age_minutes,
            "fresh": need_scrape
        },
        "pagination": {
            "current_page": page,
            "per_page": per_page,
            "total_items": total_items,
            "total_pages": total_pages
        }
    }

@app.get("/api/scrape")
async def scrape_endpoint(background_tasks: BackgroundTasks):
    """
    Endpoint to scrape all sources and update the cache.
    Returns immediately with status and runs scraping in background.
    """
    try:
        # Run in background to avoid timeout for long-running scrapes
        background_tasks.add_task(scrape_and_update_cache)
        
        return {
            "status": "success",
            "message": "Scraping started in background. Use /api/content to get results.",
            "current_cache_size": len(last_scraped_results)
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

def scrape_and_update_cache():
    """Background task to scrape and update the cache"""
    try:
        results = run_all_scrapers_selenium()
        update_cache_with_results(results)
        print(f"Background scrape completed successfully. Found {len(results)} articles.")
    except Exception as e:
        print(f"Background scrape failed: {str(e)}")
@app.get("/health")
def health_check():
    """Check the health status of the API"""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "sources_configured": len(sources)
    }

if __name__ == "__main__":
    print("\033[1;35m" + "=" * 80)
    print("Irungu Kang'ata News Scraper".center(80))
    print("=" * 80 + "\033[0m")
    
    print("\n\033[1mBefore running, make sure you have installed:\033[0m")
    print("1. Python packages: pip install fastapi uvicorn selenium webdriver-manager")
    print("2. Chrome browser must be installed on your system")
    print("\nAvailable endpoints:")
    print("- Main page: http://localhost:8000")
    print("- Scrape all sources: http://localhost:8000/scrape")
    print("- List sources: http://localhost:8000/sources")
    print("- Scrape specific source: http://localhost:8000/scrape/{index}")
    print("- Health check: http://localhost:8000/health")
    
    uvicorn.run(app, host="0.0.0.0", port=8000)