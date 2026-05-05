"""
JobScout V3 Orchestrator - Main Entry Point

Coordinates all agents in the job application pipeline:
1. Discovery Agent - Find relevant jobs
2. Enrichment Agent - Scrape full job descriptions
3. Analysis Agent - Score & select resume components
4. Generation Agent - Create tailored resumes

Features:
- Human checkpoints (review before proceeding)
- Progress tracking (save state between steps)
- Summary generation (markdown report)
- Error handling (graceful recovery)

Location: jobscout_v3/orchestrator.py
"""

import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed, skip

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from tools.profile import load_profile
from tools.resume import ResumeParser
from agents import DiscoveryAgent, EnrichmentAgent, AnalysisAgent, GenerationAgent

logger = logging.getLogger(__name__)


class JobScoutOrchestrator:
    """
    Main orchestrator for JobScout V3 pipeline.
    
    Coordinates all agents and provides:
    - Progress tracking
    - Human checkpoints
    - State persistence
    - Summary generation
    """
    
    def __init__(
        self,
        profile_name: str,
        output_dir: str = "outputs",
        checkpoint: bool = False,
        mock_mode: bool = False,
        mock_generation: bool = False,
    ):
        """
        Initialize orchestrator.
        
        Args:
            profile_name: Name of profile to load
            output_dir: Base output directory
            checkpoint: If True, pause for human review between stages
            mock_mode: If True, use mock data for entire pipeline
            mock_generation: If True, use mock for generation only
        """
        self.profile_name = profile_name
        self.checkpoint = checkpoint
        self.mock_mode = mock_mode
        self.mock_generation = mock_generation
        
        # Load profile
        logger.info(f"📋 Loading profile: {profile_name}")
        self.profile = load_profile(profile_name)
        logger.info(f"✅ Loaded profile: {self.profile.personal_info.name}")
        
        # Setup output directory
        timestamp = datetime.now().strftime("%Y-%m-%d")
        self.output_path = Path(output_dir) / timestamp
        self.output_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"📁 Output directory: {self.output_path}")
        
        # State tracking
        self.state = {
            'profile': profile_name,
            'timestamp': timestamp,
            'discovered_jobs': [],
            'enriched_jobs': [],
            'analysis_results': [],
            'generation_results': [],
        }
        
        # Resume parser (shared across agents)
        resume_path = self.profile.resume_preferences.master_resume_path
        if not resume_path.startswith('/'):
            resume_path = Path(__file__).parent / resume_path
        
        logger.info(f"📄 Loading resume: {resume_path}")
        self.resume_parser = ResumeParser(str(resume_path))
        logger.info(f"✅ Resume loaded: {len(self.resume_parser.get_experiences())} exp, "
                   f"{len(self.resume_parser.get_projects())} proj")
    
    def run(self, max_jobs: int = 20) -> Dict:
        """
        Run the full pipeline.
        
        Args:
            max_jobs: Maximum number of jobs to process
            
        Returns:
            Final state dict with all results
        """
        logger.info("=" * 80)
        logger.info("🚀 STARTING JOBSCOUT V3 PIPELINE")
        logger.info("=" * 80)
        logger.info(f"Profile: {self.profile.personal_info.name}")
        logger.info(f"Max jobs: {max_jobs}")
        logger.info(f"Checkpoints: {'Enabled' if self.checkpoint else 'Disabled'}")
        logger.info(f"Mock mode: {self.mock_mode}")
        logger.info("")
        
        try:
            # Stage 1: Discovery
            self._run_discovery(max_jobs)
            
            # Stage 2: Enrichment
            self._run_enrichment()
            
            # Stage 3: Analysis
            self._run_analysis()
            
            # Stage 4: Generation
            self._run_generation()
            
            # Generate summary
            self._generate_summary()
            
            # Final report
            self._print_final_report()
            
            return self.state
            
        except KeyboardInterrupt:
            logger.warning("\n\n⚠️  Pipeline interrupted by user")
            self._save_state()
            logger.info(f"💾 State saved to: {self.output_path / 'state.json'}")
            raise
        except Exception as e:
            logger.error(f"\n\n❌ Pipeline failed: {e}")
            import traceback
            traceback.print_exc()
            self._save_state()
            raise
    
    def _run_discovery(self, max_jobs: int):
        """Stage 1: Discover jobs."""
        logger.info("=" * 80)
        logger.info("🔍 STAGE 1: DISCOVERY")
        logger.info("=" * 80)
        
        agent = DiscoveryAgent(self.profile, mock_mode=self.mock_mode)
        jobs = agent.discover_jobs(max_jobs=max_jobs)
        
        self.state['discovered_jobs'] = jobs
        logger.info(f"✅ Discovered {len(jobs)} jobs")
        
        if self.checkpoint and jobs:
            self._checkpoint_review_jobs(jobs, "discovery")
        
        self._save_state()
    
    def _run_enrichment(self):
        """Stage 2: Enrich jobs with full JDs."""
        logger.info("\n" + "=" * 80)
        logger.info("📝 STAGE 2: ENRICHMENT")
        logger.info("=" * 80)
        
        jobs = self.state['discovered_jobs']
        if not jobs:
            logger.warning("⚠️  No jobs to enrich")
            return
        
        agent = EnrichmentAgent(mock_mode=True)  # Always mock for now
        enriched = agent.enrich_jobs(jobs)
        
        self.state['enriched_jobs'] = enriched
        logger.info(f"✅ Enriched {len(enriched)} jobs")
        
        # Save enriched jobs
        enriched_path = self.output_path / "enriched_jobs.json"
        with open(enriched_path, 'w') as f:
            json.dump(enriched, f, indent=2, default=str)
        logger.info(f"💾 Saved to: {enriched_path}")
        
        if self.checkpoint and enriched:
            self._checkpoint_review_jobs(enriched, "enrichment")
        
        self._save_state()
    
    def _run_analysis(self):
        """Stage 3: Analyze jobs and select components."""
        logger.info("\n" + "=" * 80)
        logger.info("📊 STAGE 3: ANALYSIS")
        logger.info("=" * 80)
        
        jobs = self.state['enriched_jobs']
        if not jobs:
            logger.warning("⚠️  No jobs to analyze")
            return
        
        agent = AnalysisAgent(
            self.profile,
            str(self.resume_parser.resume_path)
        )
        results = agent.analyze_jobs(jobs)
        
        self.state['analysis_results'] = results
        logger.info(f"✅ Analyzed {len(results)} jobs passing threshold")
        
        # Save analysis results
        analysis_path = self.output_path / "analysis_results.json"
        with open(analysis_path, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        logger.info(f"💾 Saved to: {analysis_path}")
        
        if self.checkpoint and results:
            self._checkpoint_review_analysis(results)
        
        self._save_state()
    
    def _run_generation(self):
        """Stage 4: Generate tailored resumes."""
        logger.info("\n" + "=" * 80)
        logger.info("📝 STAGE 4: GENERATION")
        logger.info("=" * 80)
        
        analysis_results = self.state['analysis_results']
        if not analysis_results:
            logger.warning("⚠️  No jobs to generate resumes for")
            return
        
        mock_gen = self.mock_mode or self.mock_generation
        agent = GenerationAgent(
            self.profile,
            self.resume_parser,
            mock_mode=mock_gen
        )
        results = agent.generate_resumes(
            analysis_results,
            output_dir=str(self.output_path)
        )
        
        self.state['generation_results'] = results
        logger.info(f"✅ Generated {len(results)} resumes")
        
        self._save_state()
    
    def _checkpoint_review_jobs(self, jobs: List, stage: str):
        """Pause for human review of discovered/enriched jobs."""
        print("\n" + "=" * 80)
        print(f"🔍 CHECKPOINT: Review {stage.upper()} results")
        print("=" * 80)
        
        print(f"\nFound {len(jobs)} jobs:\n")
        
        for i, job in enumerate(jobs[:10], 1):  # Show first 10
            # Handle both JobListing objects and dicts
            if hasattr(job, 'title'):
                # JobListing object
                print(f"{i}. [{job.source}] {job.title} @ {job.company}")
                print(f"   Location: {job.location}")
                if job.salary_min:
                    print(f"   Salary: ${job.salary_min:,.0f} - ${job.salary_max:,.0f}")
            else:
                # Dict
                print(f"{i}. [{job.get('source', 'unknown')}] {job['title']} @ {job['company']}")
                print(f"   Location: {job['location']}")
                if 'salary_min' in job and job['salary_min']:
                    print(f"   Salary: ${job['salary_min']:,.0f} - ${job['salary_max']:,.0f}")
            print()
        
        if len(jobs) > 10:
            print(f"... and {len(jobs) - 10} more\n")
        
        response = input("Continue to next stage? (y/n): ").strip().lower()
        if response != 'y':
            logger.info("⚠️  Pipeline stopped by user")
            self._save_state()
            sys.exit(0)
    
    def _checkpoint_review_analysis(self, results: List[Dict]):
        """Pause for human review of analysis results."""
        print("\n" + "=" * 80)
        print("📊 CHECKPOINT: Review ANALYSIS results")
        print("=" * 80)
        
        print(f"\n{len(results)} jobs passed threshold:\n")
        
        for i, result in enumerate(results[:5], 1):  # Show top 5
            job = result['job']
            score = result['score']
            selected = result['selected_components']
            
            print(f"{i}. [{score['overall']:.1f}%] {job['title']} @ {job['company']}")
            print(f"   Location: {job['location']}")
            print(f"   Selected: {len(selected['experiences'])} exp, {len(selected['projects'])} proj")
            print(f"   Top exp: {', '.join(selected['experiences'][:2])}")
            print()
        
        if len(results) > 5:
            print(f"... and {len(results) - 5} more\n")
        
        response = input("Continue to generation? (y/n): ").strip().lower()
        if response != 'y':
            logger.info("⚠️  Pipeline stopped by user")
            self._save_state()
            sys.exit(0)
    
    def _save_state(self):
        """Save current state to JSON."""
        state_path = self.output_path / "state.json"
        with open(state_path, 'w') as f:
            json.dump(self.state, f, indent=2, default=str)
    
    def _generate_summary(self):
        """Generate markdown summary report."""
        logger.info("\n" + "=" * 80)
        logger.info("📄 GENERATING SUMMARY")
        logger.info("=" * 80)
        
        summary_path = self.output_path / "summary.md"
        
        with open(summary_path, 'w') as f:
            f.write(f"# JobScout V3 - Pipeline Summary\n\n")
            f.write(f"**Profile:** {self.profile.personal_info.name}\n")
            f.write(f"**Date:** {self.state['timestamp']}\n")
            f.write(f"**Email:** {self.profile.personal_info.email}\n\n")
            
            f.write("---\n\n")
            
            # Discovery summary
            f.write("## 🔍 Discovery\n\n")
            jobs = self.state['discovered_jobs']
            f.write(f"**Jobs found:** {len(jobs)}\n\n")
            
            if jobs:
                f.write("### Top Jobs:\n\n")
                for i, job in enumerate(jobs[:10], 1):
                    # Handle both JobListing objects and dicts
                    if hasattr(job, 'title'):
                        # JobListing object
                        f.write(f"{i}. **{job.title}** @ **{job.company}**\n")
                        f.write(f"   - Location: {job.location}\n")
                        f.write(f"   - Source: {job.source}\n")
                        if job.salary_min:
                            f.write(f"   - Salary: ${job.salary_min:,.0f} - ${job.salary_max:,.0f}\n")
                        f.write(f"   - URL: {job.apply_url}\n\n")
                    else:
                        # Dict
                        f.write(f"{i}. **{job['title']}** @ **{job['company']}**\n")
                        f.write(f"   - Location: {job['location']}\n")
                        f.write(f"   - Source: {job.get('source', 'unknown')}\n")
                        if 'salary_min' in job and job['salary_min']:
                            f.write(f"   - Salary: ${job['salary_min']:,.0f} - ${job['salary_max']:,.0f}\n")
                        f.write(f"   - URL: {job.get('apply_url', 'N/A')}\n\n")
            
            f.write("\n---\n\n")
            
            # Analysis summary
            f.write("## 📊 Analysis\n\n")
            results = self.state['analysis_results']
            f.write(f"**Jobs analyzed:** {len(self.state['enriched_jobs'])}\n")
            f.write(f"**Jobs passing threshold:** {len(results)}\n")
            f.write(f"**Threshold:** {self.profile.agent_preferences.scoring_threshold}%\n\n")
            
            if results:
                f.write("### Top Matches:\n\n")
                for i, result in enumerate(results[:10], 1):
                    job = result['job']
                    score = result['score']
                    selected = result['selected_components']
                    
                    f.write(f"{i}. **[{score['overall']:.1f}%] {job['title']}** @ **{job['company']}**\n")
                    f.write(f"   - Location: {job['location']}\n")
                    f.write(f"   - Selected: {len(selected['experiences'])} experiences, {len(selected['projects'])} projects\n")
                    f.write(f"   - Top experiences: {', '.join(selected['experiences'][:2])}\n")
                    f.write(f"   - Top projects: {', '.join(selected['projects'][:2])}\n\n")
            
            f.write("\n---\n\n")
            
            # Generation summary
            f.write("## 📝 Generation\n\n")
            gen_results = self.state['generation_results']
            f.write(f"**Resumes generated:** {len(gen_results)}\n\n")
            
            if gen_results:
                f.write("### Generated Files:\n\n")
                for i, result in enumerate(gen_results, 1):
                    job = result['job']
                    latex_path = Path(result['latex_path'])
                    validation = result['validation']
                    
                    status = "✅" if validation['valid'] else "⚠️"
                    f.write(f"{i}. {status} **{job['company']}** - {job['title']}\n")
                    f.write(f"   - File: `{latex_path.name}`\n")
                    if validation['errors']:
                        f.write(f"   - Validation errors: {len(validation['errors'])}\n")
                    f.write("\n")
            
            f.write("\n---\n\n")
            f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        
        logger.info(f"✅ Summary saved: {summary_path}")
    
    def _print_final_report(self):
        """Print final report to console."""
        print("\n\n")
        print("=" * 80)
        print("🎉 PIPELINE COMPLETE!")
        print("=" * 80)
        print()
        print(f"Profile: {self.profile.personal_info.name}")
        print(f"Output directory: {self.output_path}")
        print()
        print("📊 Results:")
        print(f"  • Jobs discovered: {len(self.state['discovered_jobs'])}")
        print(f"  • Jobs enriched: {len(self.state['enriched_jobs'])}")
        print(f"  • Jobs analyzed: {len(self.state['analysis_results'])}")
        print(f"  • Resumes generated: {len(self.state['generation_results'])}")
        print()
        print("📁 Output files:")
        print(f"  • Summary: {self.output_path / 'summary.md'}")
        print(f"  • Analysis: {self.output_path / 'analysis_results.json'}")
        print(f"  • Resumes: {self.output_path / '*.tex'}")
        print()
        
        if self.state['generation_results']:
            print("📄 Generated resumes:")
            for result in self.state['generation_results'][:5]:
                job = result['job']
                print(f"  • {job['company']} - {job['title']}")
            
            if len(self.state['generation_results']) > 5:
                print(f"  ... and {len(self.state['generation_results']) - 5} more")
        
        print()
        print("=" * 80)
        print()


def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="JobScout V3 - Multi-agent job application pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run full pipeline with 20 jobs
  python orchestrator.py --profile yash_pathak --max-jobs 20
  
  # Run with checkpoints (human review at each stage)
  python orchestrator.py --profile yash_pathak --max-jobs 20 --checkpoint
  
  # Run in mock mode (no API calls)
  python orchestrator.py --profile yash_pathak --max-jobs 10 --mock
  
  # Use real discovery, mock generation
  python orchestrator.py --profile yash_pathak --max-jobs 15 --mock-generation
        """
    )
    
    parser.add_argument(
        "--profile",
        default="yash_pathak",
        help="Profile name (default: yash_pathak)"
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=20,
        help="Maximum jobs to process (default: 20)"
    )
    parser.add_argument(
        "--output",
        default="outputs",
        help="Output directory (default: outputs/)"
    )
    parser.add_argument(
        "--checkpoint",
        action="store_true",
        help="Enable human checkpoints between stages"
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use mock mode for entire pipeline"
    )
    parser.add_argument(
        "--mock-generation",
        action="store_true",
        help="Use mock for generation only"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(levelname)s:%(name)s:%(message)s'
    )
    
    # Run orchestrator
    orchestrator = JobScoutOrchestrator(
        profile_name=args.profile,
        output_dir=args.output,
        checkpoint=args.checkpoint,
        mock_mode=args.mock,
        mock_generation=args.mock_generation,
    )
    
    orchestrator.run(max_jobs=args.max_jobs)


if __name__ == "__main__":
    main()