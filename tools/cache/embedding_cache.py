"""
Resume Embedding Cache System

Caches parsed resume and embeddings to avoid:
- Re-parsing LaTeX on every run
- Re-computing 25 embeddings on every run

Saves ~30 seconds and 25 API calls per run.
"""

import json
import hashlib
from pathlib import Path
from typing import Dict, Optional, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class EmbeddingCache:
    """Cache for resume embeddings."""

    def __init__(self, cache_dir: str = "cache", model: Optional[str] = None):
        """
        Args:
            cache_dir: Where resume_embeddings.json lives
            model: Embedding model the cached vectors were produced by.
                   Entries produced by any other model are treated as a miss.
                   Passed in rather than read from config so this module
                   stays config-free, matching llm_cache.py.
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "resume_embeddings.json"
        self.model = model

    def _compute_file_hash(self, file_path: Path) -> str:
        """Compute SHA256 hash of file content."""
        with open(file_path, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()
    
    def get(self, resume_path: Path) -> Optional[Dict]:
        """
        Get cached embeddings if resume hasn't changed.
        
        Returns:
            Cached data or None if cache miss/invalid
        """
        if not self.cache_file.exists():
            logger.debug("📦 No embedding cache found")
            return None
        
        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            # Check if resume file has changed
            current_hash = self._compute_file_hash(resume_path)
            cached_hash = cache_data.get('resume_hash')
            
            if current_hash != cached_hash:
                logger.debug("📦 Resume file changed, cache invalid")
                return None

            # Vectors from different embedding models are not comparable, even
            # at the same dimensionality. Serving them together produces a
            # plausible-looking ranking that is quietly wrong — no error, no
            # warning. Treat a model change (or a pre-R11 entry with no model
            # recorded) as a miss and re-embed. See R11 in known_questions.md.
            if self.model is not None:
                cached_model = cache_data.get('embedding_model')

                if cached_model != self.model:
                    logger.info(
                        f"📦 Embedding model changed "
                        f"({cached_model or 'unrecorded'} → {self.model}), "
                        f"cache invalid — re-embedding"
                    )
                    return None

            # Check cache age (optional: expire after 7 days)
            cached_date = cache_data.get('cached_at')
            logger.info(f"✅ Using cached embeddings from {cached_date}")
            
            return cache_data
            
        except Exception as e:
            logger.warning(f"⚠️  Failed to load cache: {e}")
            return None
    
    def set(self, resume_path: Path, parsed_data: Dict, embeddings: Dict):
        """
        Save parsed resume and embeddings to cache.
        
        Args:
            resume_path: Path to master resume
            parsed_data: Parsed resume structure (experiences, projects, skills)
            embeddings: Dict mapping component IDs to embedding vectors
        """
        try:
            cache_data = {
                'resume_hash': self._compute_file_hash(resume_path),
                'embedding_model': self.model,
                'cached_at': datetime.now().isoformat(),
                'resume_path': str(resume_path),
                'parsed_data': parsed_data,
                'embeddings': embeddings
            }
            
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2)
            
            logger.info(f"💾 Saved embeddings to cache ({self.cache_file})")
            
        except Exception as e:
            logger.warning(f"⚠️  Failed to save cache: {e}")
    
    def clear(self):
        """Clear the cache."""
        if self.cache_file.exists():
            self.cache_file.unlink()
            logger.info("🗑️  Cleared embedding cache")