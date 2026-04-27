"""
JobScout — Multi-Agent Job Research & Fit Analyzer
Main entry point. Runs the orchestrator pipeline via CLI.

Usage:
    python -m jobscout.main --jd path/to/jd.txt --resume path/to/resume.txt
    python -m jobscout.main --jd-text "We are hiring a..." --resume path/to/resume.txt
"""

import argparse
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from google.genai import types as genai_types
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from jobscout.agents.orchestrator import build_orchestrator

console = Console()


def load_text(path: str) -> str:
    """Read a text file and return its contents."""
    return Path(path).read_text(encoding="utf-8")


async def run_jobscout(jd_text: str, resume_text: str) -> str:
    """
    Run the full JobScout pipeline:
    Research → Fit Analysis → Interview Prep

    Args:
        jd_text: The job description text.
        resume_text: The candidate's resume text.

    Returns:
        The final combined report as a string.
    """
    console.print(Panel("🔍 JobScout — Starting Analysis", style="bold cyan"))
    console.print("[dim]Running: Research → Fit Analysis → Interview Prep[/dim]\n")

    session_service = InMemorySessionService()
    orchestrator = build_orchestrator()

    runner = Runner(
        agent=orchestrator,
        app_name="jobscout",
        session_service=session_service,
    )

    session = await session_service.create_session(
        app_name="jobscout",
        user_id="user",
    )

    # Build the prompt that flows through all three agents
    user_message = f"""Analyze this job opportunity for me.

=== JOB DESCRIPTION ===
{jd_text}

=== MY RESUME ===
{resume_text}

Run all analysis agents and produce a comprehensive report covering:
1. Company & role research
2. Resume fit analysis with scores
3. Interview prep materials and cover letter draft
"""

    content = genai_types.Content(
        role="user",
        parts=[genai_types.Part(text=user_message)],
    )

    final_response = ""
    agent_responses = []

    async for event in runner.run_async(
        user_id="user",
        session_id=session.id,
        new_message=content,
    ):
        # Collect responses from each agent in the sequence
        if event.content and event.content.parts:
            for part in event.content.parts:
                if hasattr(part, "text") and part.text:
                    agent_responses.append(part.text)

        if event.is_final_response() and event.content and event.content.parts:
            final_response = event.content.parts[0].text

    # If sequential agent didn't produce a single final, combine all
    if not final_response and agent_responses:
        final_response = "\n\n---\n\n".join(agent_responses)

    return final_response


def save_report(report: str, output_dir: str = "outputs") -> str:
    """Save the report to a markdown file."""
    os.makedirs(output_dir, exist_ok=True)
    from datetime import datetime

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(output_dir, f"jobscout_report_{timestamp}.md")
    Path(filepath).write_text(report, encoding="utf-8")
    return filepath


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="JobScout — AI-powered Job Fit Analyzer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m jobscout.main --jd job_posting.txt --resume my_resume.txt
  python -m jobscout.main --jd-text "Software Engineer at Stripe..." --resume my_resume.txt
        """,
    )
    parser.add_argument("--jd", help="Path to job description text file")
    parser.add_argument("--jd-text", help="Job description as inline text")
    parser.add_argument("--resume", required=True, help="Path to resume text file")
    parser.add_argument(
        "--output", default="outputs", help="Output directory (default: outputs/)"
    )
    args = parser.parse_args()

    if not args.jd and not args.jd_text:
        parser.error("Provide either --jd (file path) or --jd-text (inline text)")

    # Validate API key
    if not os.getenv("GOOGLE_API_KEY"):
        console.print(
            "[bold red]Error:[/bold red] GOOGLE_API_KEY not set. "
            "Copy .env.example to .env and add your Gemini API key.\n"
            "Get one free at: https://aistudio.google.com/app/apikey"
        )
        return

    jd_text = args.jd_text if args.jd_text else load_text(args.jd)
    resume_text = load_text(args.resume)

    console.print(f"[green]✓[/green] Loaded JD ({len(jd_text)} chars)")
    console.print(f"[green]✓[/green] Loaded Resume ({len(resume_text)} chars)\n")

    # Run the pipeline
    report = asyncio.run(run_jobscout(jd_text, resume_text))

    # Display results
    console.print("\n")
    console.print(Panel("📋 JobScout Report", style="bold green"))
    console.print(Markdown(report))

    # Save to file
    filepath = save_report(report, args.output)
    console.print(f"\n[green]✓[/green] Report saved to: {filepath}")


if __name__ == "__main__":
    main()
