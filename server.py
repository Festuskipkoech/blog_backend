from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import tweepy
from transformers import pipeline
from pydantic import BaseModel
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Twitter API client
twitter_client = tweepy.Client(
    bearer_token=os.getenv("TWITTER_BEARER_TOKEN"),
    wait_on_rate_limit=True
)

# Initialize summarizer
summarizer = pipeline("summarization", model="facebook/bart-large-cnn")

class ArticleContent(BaseModel):
    title: str
    content: str
    url: str
    date: str

class ScrapedContent(BaseModel):
    daily_nation_articles: list[ArticleContent]
    tweets: list[dict]

@app.get("/scrape/content")
async def scrape_content(daily_nation_account: str = "dailynation", twitter_account: str = None):
    try:
        # Scrape Daily Nation articles from their account page
        articles = []
        url = f"https://nation.africa/kenya/author-profiles/{daily_nation_account}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find all article links (adjust selectors based on actual HTML structure)
        article_links = soup.find_all('article')
        
        for article in article_links[:5]:  # Get latest 5 articles
            try:
                article_url = article.find('a')['href']
                if not article_url.startswith('http'):
                    article_url = f"https://nation.africa{article_url}"
                
                # Scrape individual article
                article_response = requests.get(article_url, headers=headers)
                article_soup = BeautifulSoup(article_response.text, 'html.parser')
                
                title = article_soup.find('h1').text.strip()
                content = ""
                article_body = article_soup.find('article')
                if article_body:
                    paragraphs = article_body.find_all('p')
                    content = ' '.join([p.text.strip() for p in paragraphs])
                
                date = article_soup.find('time')['datetime'] if article_soup.find('time') else "No date"
                
                # Generate summary if content is long enough
                if len(content) > 100:
                    content = summarizer(content, max_length=130, min_length=30, do_sample=False)[0]['summary_text']
                
                articles.append(ArticleContent(
                    title=title,
                    content=content,
                    url=article_url,
                    date=date
                ))
            except Exception as e:
                print(f"Error scraping article: {str(e)}")
                continue
        
        # Get tweets if account is provided
        tweets = []
        if twitter_account:
            try:
                user = twitter_client.get_user(username=twitter_account)
                if user.data:
                    user_tweets = twitter_client.get_users_tweets(
                        user.data.id,
                        max_results=10,
                        tweet_fields=['created_at', 'public_metrics']
                    )
                    if user_tweets.data:
                        tweets = [{
                            'text': tweet.text,
                            'created_at': tweet.created_at,
                            'metrics': tweet.public_metrics
                        } for tweet in user_tweets.data]
            except Exception as e:
                print(f"Error fetching tweets: {str(e)}")
        
        return ScrapedContent(
            daily_nation_articles=articles,
            tweets=tweets
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)