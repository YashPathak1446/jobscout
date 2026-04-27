"""
JobScout — Streamlit Web UI
A simple frontend for demoing the multi-agent pipeline.

Run with: streamlit run jobscout/app.py
"""

import asyncio
import os
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="JobScout", page_icon="🔍", layout="wide")

st.title("🔍 JobScout")
st.markdown("**Multi-Agent Job Research & Fit Analyzer** — powered by Google ADK")
st.markdown("---")

# Check for API key
api_key = os.getenv("GOOGLE_API_KEY", "")
if not api_key:
    st.warning(
        "⚠️ GOOGLE_API_KEY not set. Add it to your `.env` file. "
        "Get one free at [Google AI Studio](https://aistudio.google.com/app/apikey)."
    )

col1, col2 = st.columns(2)

with col1:
    st.subheader("📄 Job Description")
    jd_text = st.text_area(
        "Paste the job description here",
        height=400,
        placeholder="Software Engineer at Stripe\n\nAbout the role...",
    )

with col2:
    st.subheader("📝 Your Resume")
    resume_text = st.text_area(
        "Paste your resume text here",
        height=400,
        placeholder="YASH PATHAK\nREDACTED-EMAIL\n\nEDUCATION...",
    )

st.markdown("---")

if st.button("🚀 Analyze Job Fit", type="primary", use_container_width=True):
    if not jd_text.strip():
        st.error("Please paste a job description.")
    elif not resume_text.strip():
        st.error("Please paste your resume.")
    elif not api_key:
        st.error("Please set your GOOGLE_API_KEY in the .env file.")
    else:
        with st.spinner("🔍 Running multi-agent analysis... This takes 30-60 seconds."):
            try:
                from google.genai import types as genai_types
                from google.adk.runners import Runner
                from google.adk.sessions import InMemorySessionService
                from jobscout.agents.orchestrator import build_orchestrator

                async def run_analysis():
                    session_service = InMemorySessionService()
                    orchestrator = build_orchestrator()
                    runner = Runner(
                        agent=orchestrator,
                        app_name="jobscout",
                        session_service=session_service,
                    )
                    session = await session_service.create_session(
                        app_name="jobscout", user_id="streamlit_user"
                    )

                    prompt = f"""Analyze this job opportunity for me.

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
                        parts=[genai_types.Part(text=prompt)],
                    )

                    responses = []
                    async for event in runner.run_async(
                        user_id="streamlit_user",
                        session_id=session.id,
                        new_message=content,
                    ):
                        if event.content and event.content.parts:
                            for part in event.content.parts:
                                if hasattr(part, "text") and part.text:
                                    responses.append(part.text)
                    return "\n\n---\n\n".join(responses) if responses else "No response generated."

                report = asyncio.run(run_analysis())

                st.success("✅ Analysis complete!")
                st.markdown("## 📋 JobScout Report")
                st.markdown(report)

                # Download button
                st.download_button(
                    label="📥 Download Report",
                    data=report,
                    file_name="jobscout_report.md",
                    mime="text/markdown",
                )

            except Exception as e:
                st.error(f"Error running analysis: {e}")
                st.info(
                    "Make sure you've installed all dependencies: "
                    "`pip install -e '.[ui]'`"
                )

st.markdown("---")
st.markdown(
    "<div style='text-align: center; color: gray;'>"
    "Built with Google ADK · Gemini · Python"
    "</div>",
    unsafe_allow_html=True,
)
