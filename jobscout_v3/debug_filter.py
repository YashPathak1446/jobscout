"""
Debug script to see why jobs are being filtered out.

Run this to see exactly what the filter sees for each job.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from tools.profile import load_profile
from tools.search import search_serper
import os

# Load profile
profile = load_profile('yash_pathak')
print("✅ Profile loaded")
print(f"Exclude keywords: {profile.job_preferences.exclude_keywords}")
print()

# Test with a few Serper results
if not os.getenv('SERPER_API_KEY'):
    print("❌ SERPER_API_KEY not set")
    print("Run: $env:SERPER_API_KEY='your_key'")
    sys.exit(1)

print("🔎 Searching Serper for 'Software Engineer new grad site:greenhouse.io'...")
jobs = search_serper("Software Engineer new grad site:greenhouse.io", max_results=5)
print(f"Found {len(jobs)} jobs\n")

# Test filtering on each job
for i, job in enumerate(jobs, 1):
    print(f"{'='*80}")
    print(f"Job {i}: {job.title}")
    print(f"Company: {job.company}")
    print(f"URL: {job.apply_url}")
    print(f"Description: {job.description}")
    print()
    
    # Test the filter
    should_exclude, reason = profile.should_exclude_job(job.title, job.description)
    
    if should_exclude:
        print(f"❌ EXCLUDED: {reason}")
    else:
        print(f"✅ KEPT")
    
    # Show what text the filter sees
    text = f"{job.title} {job.description}".lower()
    print(f"\nFilter sees: {text[:200]}...")
    
    # Check each exclude keyword
    print("\nChecking exclude keywords:")
    for keyword in profile.job_preferences.exclude_keywords:
        if keyword.lower() in text:
            print(f"  ❌ MATCHED: '{keyword}'")
    
    # Check senior indicators
    senior_indicators = ['senior', 'sr.', 'sr ', 'staff', 'principal', 'lead', 'director', 'manager', 'head of']
    print("\nChecking senior indicators:")
    for indicator in senior_indicators:
        if indicator in text:
            print(f"  ❌ MATCHED: '{indicator}'")
    
    print()

print(f"{'='*80}")
print("\n✅ Debug complete!")