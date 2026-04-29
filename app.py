import streamlit as st
from utils import (
    extract_text_from_pdf,
    extract_text_from_docx,
    extract_text_from_txt,
    analyze_resume,
    fit_color,
    score_color,
)

# ── Page config ───────────────────────────────────────────────
st.set_page_config(
    page_title="AI Resume Screener",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────
st.markdown("""
<style>
    .main-title { font-size:2.4rem; font-weight:800; text-align:center;
                  background:linear-gradient(90deg,#667eea,#764ba2);
                  -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
    .score-box  { text-align:center; padding:1.5rem; border-radius:16px;
                  background:#1e1e2e; }
    .score-num  { font-size:4rem; font-weight:900; }
    .fit-badge  { display:inline-block; padding:.4rem 1.2rem; border-radius:50px;
                  font-size:1.1rem; font-weight:700; color:#fff; margin-top:.5rem; }
    .section-card { background:#f8f9fa; border-left:4px solid #667eea;
                    border-radius:8px; padding:1rem 1.2rem; margin:.6rem 0; }
    .chip       { display:inline-block; padding:.25rem .7rem; margin:.2rem;
                  border-radius:20px; font-size:.82rem; font-weight:600; }
    .chip-green { background:#d4edda; color:#155724; }
    .chip-red   { background:#f8d7da; color:#721c24; }
    .rec-box    { padding:1rem; border-radius:10px; text-align:center;
                  font-size:1.1rem; font-weight:700; color:#fff; margin-top:1rem; }
</style>
""", unsafe_allow_html=True)

# ── Resolve API key (secrets → sidebar fallback) ──────────────
api_key = st.secrets.get("GEMINI_API_KEY", "") if hasattr(st, "secrets") else ""

# ── Sidebar ───────────────────────────────────────────────────
with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/find-matching-job.png", width=80)
    st.markdown("## ⚙️ Configuration")
    if api_key:
        st.success("🔑 Gemini API key loaded from secrets.", icon="✅")
    else:
        api_key = st.text_input(
            "🔑 Google Gemini API Key", type="password",
            help="Your key is never stored — used only for this session.",
        )
        st.markdown("[🔗 Get a free API key →](https://aistudio.google.com/apikey)",
                    unsafe_allow_html=True)
    st.divider()
    st.markdown("### 📋 How to use")
    st.markdown("""
1. Upload the **resume** (PDF / DOCX)
2. Provide the **Job Description**
3. Hit **Analyse Resume** and wait ~10 s
4. Review the detailed AI feedback
    """)
    st.divider()
    st.info("Supports **PDF** and **DOCX** resume formats.\nJD can also be uploaded or pasted.")

# ── Title ─────────────────────────────────────────────────────
st.markdown('<p class="main-title">🎯 AI-Powered Resume Screener</p>', unsafe_allow_html=True)
st.markdown("<p style='text-align:center;color:gray;'>Screen candidates instantly against any Job Description using Google Gemini AI</p>",
            unsafe_allow_html=True)
st.divider()

# ── Input columns ─────────────────────────────────────────────
col1, col2 = st.columns(2, gap="large")

with col1:
    st.subheader("📄 Candidate Resume")
    resume_file = st.file_uploader("Upload Resume", type=["pdf", "docx"],
                                   label_visibility="collapsed")
    resume_text = ""
    if resume_file:
        if resume_file.name.lower().endswith(".pdf"):
            resume_text = extract_text_from_pdf(resume_file)
        else:
            resume_text = extract_text_from_docx(resume_file)
        st.success(f"✅ **{resume_file.name}** loaded ({len(resume_text):,} chars)")
        with st.expander("🔍 Preview extracted text"):
            st.text(resume_text[:1500] + ("\n…[truncated]" if len(resume_text) > 1500 else ""))

with col2:
    st.subheader("💼 Job Description")
    jd_tab1, jd_tab2 = st.tabs(["✏️ Paste Text", "📎 Upload File"])
    jd_text = ""
    with jd_tab1:
        jd_text_input = st.text_area("Paste JD here", height=220,
                                     placeholder="Copy-paste the full job description…",
                                     label_visibility="collapsed")
        jd_text = jd_text_input
    with jd_tab2:
        jd_file = st.file_uploader("Upload JD", type=["pdf", "docx", "txt"],
                                   key="jd_up", label_visibility="collapsed")
        if jd_file:
            if jd_file.name.lower().endswith(".pdf"):
                jd_text = extract_text_from_pdf(jd_file)
            elif jd_file.name.lower().endswith(".docx"):
                jd_text = extract_text_from_docx(jd_file)
            else:
                jd_text = extract_text_from_txt(jd_file)
            st.success(f"✅ **{jd_file.name}** loaded ({len(jd_text):,} chars)")

st.divider()
analyse = st.button("🔍 Analyse Resume", type="primary", use_container_width=True)

# ── Analysis & Results ────────────────────────────────────────
if analyse:
    if not api_key:
        st.error("❌ Please enter your Google Gemini API key in the sidebar.")
    elif not resume_text:
        st.error("❌ Please upload a resume (PDF or DOCX).")
    elif not jd_text.strip():
        st.error("❌ Please provide a Job Description.")
    else:
        with st.spinner("🤖 Detecting available models & analysing… (~10–20 s)"):
            result, err = analyze_resume(resume_text, jd_text, api_key)

        if not result:
            st.error("❌ Analysis failed.")
            if err:
                # Quota errors come back as formatted markdown — render them properly
                if "quota" in err.lower() or "RESOURCE_EXHAUSTED" in err:
                    st.warning(err)
                else:
                    st.error(f"🔍 Details: {err}")
                    st.info("💡 Make sure your API key is valid. "
                            "Get a free key at https://aistudio.google.com/apikey")
            st.stop()

        # ── Score & Fit header ─────────────────────────────────
        st.markdown("## 📊 Analysis Results")
        h1, h2, h3 = st.columns([1, 1, 1])
        score  = result.get("overall_score", 0)
        fit    = result.get("fit_level", "N/A")
        rec    = result.get("recommendation", "N/A")
        sc     = score_color(score)
        fc     = fit_color(fit)

        rec_colors = {"Strongly Recommend": "#28a745", "Recommend": "#17a2b8",
                      "Consider": "#ffc107", "Do Not Recommend": "#dc3545"}

        with h1:
            st.markdown(f"""
            <div class="score-box">
              <div style="color:gray;font-size:.9rem;">MATCH SCORE</div>
              <div class="score-num" style="color:{sc};">{score}<span style="font-size:1.5rem">/100</span></div>
              <div class="fit-badge" style="background:{fc};">{fit}</div>
            </div>""", unsafe_allow_html=True)
        with h2:
            st.markdown(f"""
            <div class="section-card">
              <b>🧭 Experience Match</b><br>{result.get('experience_match','N/A')}
            </div>
            <div class="section-card">
              <b>🎓 Education Match</b><br>{result.get('education_match','N/A')}
            </div>""", unsafe_allow_html=True)
        with h3:
            rc = rec_colors.get(rec, "#6c757d")
            st.markdown(f"""
            <div class="score-box">
              <div style="color:gray;font-size:.9rem;">HR RECOMMENDATION</div>
              <div class="rec-box" style="background:{rc};">{rec}</div>
              <div style="margin-top:.8rem;font-size:.85rem;color:#aaa;">
                {result.get('overall_feedback','')}
              </div>
            </div>""", unsafe_allow_html=True)

        st.divider()
        # ── Skills breakdown ───────────────────────────────────
        sk1, sk2 = st.columns(2)
        with sk1:
            st.markdown("### ✅ Matched Skills")
            chips = "".join(f'<span class="chip chip-green">✔ {s}</span>'
                            for s in result.get("matched_skills", []))
            st.markdown(chips or "_None identified_", unsafe_allow_html=True)
        with sk2:
            st.markdown("### ❌ Missing Skills")
            chips = "".join(f'<span class="chip chip-red">✘ {s}</span>'
                            for s in result.get("missing_skills", []))
            st.markdown(chips or "_None identified_", unsafe_allow_html=True)

        st.divider()
        # ── Strengths & Gaps ───────────────────────────────────
        g1, g2 = st.columns(2)
        with g1:
            st.markdown("### 💪 Strengths")
            for item in result.get("strengths", []):
                st.markdown(f'<div class="section-card">✅ {item}</div>',
                            unsafe_allow_html=True)
        with g2:
            st.markdown("### 🔧 Areas for Improvement")
            for item in result.get("areas_for_improvement", []):
                st.markdown(f'<div class="section-card">⚠️ {item}</div>',
                            unsafe_allow_html=True)

        st.divider()
        st.markdown("### 📝 Overall Feedback")
        st.info(result.get("overall_feedback", "No feedback generated."))
        st.markdown("---\n<p style='text-align:center;color:gray;font-size:.8rem;'>"
                    "Powered by Google Gemini AI • Built with Streamlit</p>",
                    unsafe_allow_html=True)
