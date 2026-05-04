"""
Analysis Agent - Score Jobs and Select Resume Components

Takes enriched jobs from Enrichment Agent and:
1. Scores each job against the resume (embedding similarity)
2. Selects which experiences/projects to include (profile rules + scores)
3. Returns analysis results for each job

Location: jobscout_v3/agents/analysis_agent.py
"""

import os
import sys
import logging
from pathlib import Path
from typing import List, Dict
import json

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.profile import load_profile, UserProfile
from tools.resume import ResumeParser

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class AnalysisAgent:
    """
    Job Analysis Agent - Scores jobs and selects resume components.
    
    The agent:
    1. Loads master resume and computes embeddings
    2. For each enriched job, scores how well resume matches
    3. Applies profile selection rules to choose components
    4. Returns analysis results with scores and selected components
    """
    
    def __init__(self, profile: UserProfile, resume_path: str):
        """
        Initialize Analysis Agent.
        
        Args:
            profile: User profile with selection rules
            resume_path: Path to master resume (.tex file)
        """
        self.profile = profile
        self.resume_path = Path(resume_path)
        
        logger.info("📊 Initializing Analysis Agent...")
        logger.info(f"Profile: {profile.personal_info.name}")
        logger.info(f"Resume: {self.resume_path.name}")
        
        # Parse resume and compute embeddings
        self.resume_parser = ResumeParser(str(self.resume_path))
        
        logger.info(f"✅ Ready to analyze jobs")
    
    def analyze_jobs(self, enriched_jobs: List[Dict]) -> List[Dict]:
        """
        Analyze enriched jobs - score and select components.
        
        Args:
            enriched_jobs: List of enriched job dicts from Enrichment Agent
            
        Returns:
            List of analysis results, each containing:
                - job: Original job data
                - score: EmbeddingScore object
                - selected_components: Dict with experiences, projects, skills
                - reasoning: Why these components were selected
                
        Example:
            >>> agent = AnalysisAgent(profile, "data/master_resumes/yash_pathak.tex")
            >>> results = agent.analyze_jobs(enriched_jobs)
            >>> print(results[0]['score'].overall_score)
        """
        logger.info(f"📊 Analyzing {len(enriched_jobs)} jobs...")
        
        results = []
        threshold = self.profile.agent_preferences.scoring_threshold
        
        for i, job in enumerate(enriched_jobs, 1):
            job_id = job.get('id', f'job_{i}')
            title = job.get('title', 'Unknown')
            company = job.get('company', 'Unknown')
            full_jd = job.get('full_jd', job.get('short_description', ''))
            
            logger.info(f"📄 Analyzing {i}/{len(enriched_jobs)}: {title} @ {company}")
            
            try:
                # Score the job
                score = self.resume_parser.score_job(
                    jd_text=full_jd,
                    job_id=job_id,
                    title=title,
                    company=company,
                )
                
                if not score:
                    logger.warning(f"   ⚠️  Scoring failed, skipping")
                    continue
                
                logger.info(f"   Score: {score.overall_score:.1f}%")
                
                # Check threshold
                if score.overall_score < threshold:
                    logger.info(f"   ⬇️  Below threshold ({threshold}%), skipping")
                    continue
                
                # Select components using profile rules
                selected = self.resume_parser.select_components(
                    jd_text=full_jd,
                    profile=self.profile,
                    embedding_score=score,
                )
                
                logger.info(f"   Selected: {len(selected['experiences'])} exp, "
                          f"{len(selected['projects'])} proj")
                
                # Generate reasoning
                reasoning = self._generate_reasoning(
                    job, score, selected
                )
                
                # Create analysis result
                result = {
                    'job': job,
                    'score': {
                        'overall': score.overall_score,
                        'best_experience_ids': score.best_experience_ids,
                        'best_project_ids': score.best_project_ids,
                        'experience_scores': score.experience_scores,
                        'project_scores': score.project_scores,
                    },
                    'selected_components': selected,
                    'reasoning': reasoning,
                }
                
                results.append(result)
                
            except Exception as e:
                logger.error(f"   ❌ Analysis failed: {e}")
                continue
        
        logger.info(f"✅ Analysis complete: {len(results)} jobs passed threshold")
        
        # Sort by score (highest first)
        results.sort(key=lambda x: x['score']['overall'], reverse=True)
        
        return results
    
    def _generate_reasoning(
        self,
        job: Dict,
        score,
        selected: Dict[str, List[str]]
    ) -> Dict[str, str]:
        """
        Generate human-readable reasoning for component selection.
        
        Args:
            job: Job dict
            score: EmbeddingScore object
            selected: Selected components dict
            
        Returns:
            Dict with reasoning for each selection
        """
        reasoning = {}
        
        # Explain experience selection
        exp_reasons = []
        for exp_id in selected['experiences'][:3]:  # Top 3
            exp = self.resume_parser.get_experience_by_id(exp_id)
            if exp:
                # Check if it was always_include
                if exp_id in self.profile.resume_preferences.experiences.always_include:
                    reason = f"Always included (profile rule)"
                # Check if conditional
                elif exp_id in self.profile.get_experience_selection_rules(job.get('full_jd', ''))['conditional']:
                    reason = f"Conditional match (JD keywords)"
                # Otherwise it's score-based
                else:
                    exp_score = score.experience_scores.get(exp_id, 0)
                    reason = f"High relevance score ({exp_score:.2f})"
                
                exp_reasons.append(f"{exp.title} @ {exp.company}: {reason}")
        
        reasoning['experiences'] = exp_reasons
        
        # Explain project selection
        proj_reasons = []
        for proj_id in selected['projects'][:3]:  # Top 3
            proj = self.resume_parser.get_project_by_id(proj_id)
            if proj:
                # Check if it was always_include
                if proj_id in self.profile.resume_preferences.projects.always_include:
                    reason = f"Always included (profile rule)"
                # Check if high_priority
                elif proj_id in self.profile.resume_preferences.projects.high_priority:
                    reason = f"High priority (profile)"
                # Otherwise score-based
                else:
                    proj_score = score.project_scores.get(proj_id, 0)
                    reason = f"High relevance score ({proj_score:.2f})"
                
                proj_reasons.append(f"{proj.name}: {reason}")
        
        reasoning['projects'] = proj_reasons
        
        # Overall reasoning
        reasoning['overall'] = (
            f"Score: {score.overall_score:.1f}% | "
            f"{len(selected['experiences'])} experiences, "
            f"{len(selected['projects'])} projects selected"
        )
        
        return reasoning


def main():
    """CLI for testing Analysis Agent."""
    import argparse
    from agents.discovery_agent import DiscoveryAgent
    from agents.enrichment_agent import EnrichmentAgent
    
    parser = argparse.ArgumentParser(description="JobScout V3 - Analysis Agent")
    parser.add_argument(
        "--profile",
        default="yash_pathak",
        help="Profile name (default: yash_pathak)"
    )
    parser.add_argument(
        "--resume",
        help="Path to master resume .tex file (default: from profile)"
    )
    parser.add_argument(
        "--input",
        help="JSON file with enriched jobs (optional)"
    )
    parser.add_argument(
        "--output",
        default="analysis_results.json",
        help="Output file for analysis results (default: analysis_results.json)"
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=10,
        help="Maximum jobs to analyze (default: 10)"
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use mock data for entire pipeline"
    )
    
    args = parser.parse_args()
    
    # Load profile
    print(f"📋 Loading profile: {args.profile}")
    profile = load_profile(args.profile)
    print(f"✅ Profile loaded: {profile.personal_info.name}\n")
    
    # Determine resume path
    if args.resume:
        resume_path = args.resume
    else:
        resume_path = profile.resume_preferences.master_resume_path
        if not resume_path.startswith('/'):
            # Make it relative to project root
            resume_path = Path(__file__).parent.parent / resume_path
    
    print(f"📄 Using resume: {resume_path}\n")
    
    # Get enriched jobs
    if args.input:
        # Load from file
        print(f"📂 Loading enriched jobs from {args.input}")
        with open(args.input, 'r') as f:
            enriched_jobs = json.load(f)
        print(f"✅ Loaded {len(enriched_jobs)} enriched jobs\n")
    else:
        # Run discovery + enrichment first
        print("🔍 Running Discovery Agent...")
        discovery = DiscoveryAgent(profile, mock_mode=args.mock)
        jobs = discovery.discover_jobs(max_jobs=args.max_jobs)
        print(f"✅ Found {len(jobs)} jobs\n")
        
        print("📝 Running Enrichment Agent...")
        enrichment = EnrichmentAgent(mock_mode=True)  # Always mock enrichment for now
        enriched_jobs = enrichment.enrich_jobs(jobs)
        print(f"✅ Enriched {len(enriched_jobs)} jobs\n")
    
    # Analyze jobs
    print("📊 Running Analysis Agent...")
    agent = AnalysisAgent(profile, str(resume_path))
    results = agent.analyze_jobs(enriched_jobs[:args.max_jobs])
    
    # Save results
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    
    print()
    print("=" * 80)
    print(f"🎉 ANALYSIS COMPLETE")
    print("=" * 80)
    print(f"Jobs analyzed: {len(enriched_jobs[:args.max_jobs])}")
    print(f"Jobs passing threshold: {len(results)}")
    print(f"Saved to: {output_path}")
    print()
    
    # Show top 3 results
    if results:
        print("🏆 Top 3 Matches:\n")
        for i, result in enumerate(results[:3], 1):
            job = result['job']
            score = result['score']
            selected = result['selected_components']
            
            print(f"{i}. [{score['overall']:.1f}%] {job['title']} @ {job['company']}")
            print(f"   Location: {job['location']}")
            print(f"   Selected: {', '.join(selected['experiences'][:2])}")
            print(f"   Projects: {', '.join(selected['projects'][:2])}")
            print()


if __name__ == "__main__":
    main()