import os
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from bs4 import BeautifulSoup
from google import genai
import uvicorn

app = FastAPI()

class ArticleRequest(BaseModel):
    url: str = None
    account: str = None

def scrape_daily_nation(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; MyScraper/1.0; +http://example.com/bot)"
    }
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        raise HTTPException(status_code=404, detail="Article not found!")
    soup = BeautifulSoup(response.text, "html.parser")
    article_div = soup.find("div", class_="article_content")
    if not article_div:
        raise HTTPException(status_code=404, detail="Article not found")
    text = article_div.get_text(separator=" ", strip=True)
    return text

def scrape_x_account(account: str) -> str:
    url = f"https://twitter.com/{account}"
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; MyScraper/1.0; +http://example.com/bot)"
    }
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        raise HTTPException(status_code=404, detail="X article not found!")
    soup = BeautifulSoup(response.text, "html.parser")
    tweets = soup.find_all("div", class_="tweets_text")
    if not tweets:
        raise HTTPException(status_code=404, detail="No tweets found or unable to parse/analyse")
    tweets_text = " ".join(tweet.get_text(separator=" ", strip=True) for tweet in tweets)
    return tweets_text

def summarize_text(text: str) -> str:
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    if not gemini_api_key:
        raise HTTPException(status_code=500, detail="Gemini API key not configured.")
    genai.configure(api_key=gemini_api_key)
    
    # Call the Gemini API using genai.chat
    response = genai.chat(
        messages=[
            {"author": "system", "content": "You are a helpful assistant that summarizes text."},
            {"author": "user", "content": f"Summarize the following text:\n\n{text}"}
        ],
        model="models/chat-bison-001",  
        # adjust this if necessary for your Gemini model
        temperature=0.7,
        max_output_tokens=150,
    )
    
    summary = response.last.strip()  # 'response.last' contains the model's reply
    return summary

@app.post("/summarize")
def summarize_article(request: ArticleRequest):
    if request.url:
        content = scrape_daily_nation(request.url)
    elif request.account:
        content = scrape_x_account(request.account)
    else:
        raise HTTPException(status_code=400, detail="Provide either a url or an account")
    summary = summarize_text(content)
    return {"summary": summary}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
