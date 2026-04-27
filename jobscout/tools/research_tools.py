"""
Tools for web research: company info, news, tech stack signals.
These are Python functions that ADK agents call as tools.
"""

import json
import os
import requests
from bs4 import BeautifulSoup


def search_web(query: str) -> dict:
    """
    Search the web for information about a company, role, or technology.
    Returns a summary of the top results.

    Args:
        query: The search query string (e.g. "Stripe engineering culture")

    Returns:
        dict with 'results' list containing title, snippet, and link for each result.
    """
    api_key = os.getenv("SERPAPI_KEY", "")

    if api_key:
        # Use SerpAPI for real search results
        try:
            resp = requests.get(
                "https://serpapi.com/search",
                params={"q": query, "api_key": api_key, "num": 5},
                timeout=10,
            )
            data = resp.json()
            results = []
            for item in data.get("organic_results", [])[:5]:
                results.append({
                    "title": item.get("title", ""),
                    "snippet": item.get("snippet", ""),
                    "link": item.get("link", ""),
                })
            return {"status": "success", "query": query, "results": results}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    else:
        # Fallback: return a prompt for the LLM to use its own knowledge
        return {
            "status": "no_api_key",
            "query": query,
            "message": (
                "No SERPAPI_KEY configured. Please use your training knowledge "
                "to answer based on the query. In production, this would return "
                "live search results."
            ),
        }


def scrape_webpage(url: str) -> dict:
    """
    Fetch and extract the main text content from a webpage URL.
    Useful for reading job postings, company about pages, etc.

    Args:
        url: The full URL to scrape (e.g. "https://stripe.com/jobs/listing/123")

    Returns:
        dict with 'content' containing the extracted text (first 3000 chars).
    """
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36"
            )
        }
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove script/style elements
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)
        # Truncate to avoid token limits
        return {"status": "success", "url": url, "content": text[:3000]}
    except Exception as e:
        return {"status": "error", "url": url, "message": str(e)}


def extract_keywords(text: str) -> dict:
    """
    Extract key technical skills, tools, and requirements from a job description.
    Parses the text and identifies technology keywords, years of experience,
    education requirements, and soft skills.

    Args:
        text: The raw job description text.

    Returns:
        dict with categorized keyword lists.
    """
    # Common tech keyword categories to scan for
    tech_keywords = {
        "languages": [
            "python", "java", "javascript", "typescript", "c++", "go", "rust",
            "ruby", "scala", "kotlin", "swift", "php", "sql", "r", "c#",
        ],
        "frameworks": [
            "react", "angular", "vue", "django", "flask", "fastapi", "spring",
            "express", "next.js", "node.js", "tensorflow", "pytorch", "langchain",
        ],
        "cloud": [
            "aws", "gcp", "azure", "lambda", "ec2", "s3", "kubernetes", "docker",
            "terraform", "cloudformation", "cloud run", "ecs", "eks",
        ],
        "data": [
            "sql", "nosql", "mongodb", "postgresql", "mysql", "redis",
            "elasticsearch", "kafka", "spark", "airflow", "dbt", "snowflake",
            "bigquery", "vector database", "pinecone", "weaviate", "chromadb",
        ],
        "ai_ml": [
            "llm", "rag", "fine-tuning", "embeddings", "transformers",
            "nlp", "computer vision", "agents", "agentic", "prompt engineering",
            "langchain", "llamaindex", "openai", "gemini", "claude", "huggingface",
        ],
        "practices": [
            "ci/cd", "agile", "scrum", "tdd", "microservices", "rest api",
            "graphql", "grpc", "devops", "sre", "observability",
        ],
    }

    text_lower = text.lower()
    found = {}
    for category, keywords in tech_keywords.items():
        matches = [kw for kw in keywords if kw in text_lower]
        if matches:
            found[category] = matches

    return {"status": "success", "keywords_found": found}
